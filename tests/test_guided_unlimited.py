"""Explicit null research allowances retain real deadline and evidence checks."""

import json
from contextlib import contextmanager
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx

from agent.config import load_config
from agent.domain.rtl.result import CheckResult
from agent.kit import State
from agent.llm.client import Client
from agent.observability.recorder import Recorder
from agent.runtime.budget import Budget
from agent.runtime.allowance import CompletionLedger
from agent.orchestration.nodes import guided
from agent.orchestration.workflows.guided_verify import GuidedParameters


class UnlimitedTests(unittest.TestCase):
    def record(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        record = Recorder(directory.name)
        self.addCleanup(record.close)
        return record

    def test_null_settings_and_zero_reserves_preserve_defaults(self):
        names = ("max_calls", "max_output_tokens", "structure_repair_limit",
                 "behavior_repair_limit", "checker_rebuild_limit", "adjudicate_limit",
                 "solve_empty_recovery_limit", "checker_empty_recovery_limit")
        config = GuidedParameters(**dict.fromkeys(names),
                                  solve={"timeout_s": 900, "max_tokens": None},
                                  first_tools_s=0, recheck_tools_s=0,
                                  solve_minimum_s=0, minimum_request_s=0)
        self.assertTrue(all(getattr(config, name) is None for name in names))
        self.assertIsNone(config.solve.max_tokens)
        self.assertEqual(GuidedParameters().max_calls, 8)
        self.assertEqual(GuidedParameters().structure_repair_limit, 1)
        self.assertTrue(guided._under_limit(100, None))
        self.assertFalse(guided._under_limit(1, 1))

    def test_unlimited_calls_and_tokens_still_stop_at_deadline(self):
        remaining = [900.0]
        ledger = CompletionLedger(SimpleNamespace(remaining=lambda: remaining[0]),
                                  self.record(), max_calls=None, max_output_tokens=None)
        for index in range(15):
            permit = ledger.reserve(str(index), None, 900, min_timeout_s=0)
            self.assertIsNone(permit.max_tokens)
            permit._begin()
            permit._sent(str(index), 20000)
            permit._response({"usage": {"prompt_tokens": 3, "completion_tokens": 10000}})
            permit._finish()
        snapshot = ledger.snapshot()
        self.assertEqual(snapshot["calls_sent"], 15)
        self.assertEqual(snapshot["known_output_tokens"], 150000)
        self.assertIsNone(snapshot["calls_remaining"])
        self.assertIsNone(snapshot["output_tokens_remaining"])
        remaining[0] = 0
        self.assertIsNone(ledger.reserve("late", None, 900, min_timeout_s=0))
        self.assertEqual(ledger.last_denial, "insufficient_followup_time")

    def test_finite_total_bounds_null_stage_and_unknown_usage_is_not_free(self):
        ledger = CompletionLedger(SimpleNamespace(remaining=lambda: 900), self.record(),
                                  max_calls=None, max_output_tokens=100)
        permit = ledger.reserve("test", None, 1)
        self.assertEqual(permit.max_tokens, 100)
        permit._begin()
        permit._sent("request", 80)
        permit._response({})
        permit._finish()
        self.assertEqual(ledger.snapshot()["output_tokens_remaining"], 0)
        self.assertIsNone(ledger.reserve("retry", None, 1))
        self.assertEqual(ledger.last_denial, "unknown_usage")

    def test_unlimited_ledger_does_not_bypass_unconfirmed_call(self):
        ledger = CompletionLedger(SimpleNamespace(remaining=lambda: 900), self.record(),
                                  max_calls=None, max_output_tokens=None)
        permit = ledger.reserve("test", None, 1)
        permit._begin()
        permit._sent("request", 80)
        permit._finish()
        self.assertIsNone(ledger.reserve("retry", None, 1, optional=False))
        self.assertEqual(ledger.last_denial, "unconfirmed_completion")

    def test_null_stage_uses_real_context_space(self):
        config, _ = load_config()
        record = self.record()
        budget = Budget(900, 0)
        ledger = CompletionLedger(budget, record, max_calls=None, max_output_tokens=None)
        requests = []

        def transport(request):
            if request.url.path == "/apply-template":
                return httpx.Response(200, json={"prompt": "self-authored"})
            if request.url.path == "/tokenize":
                return httpx.Response(200, json={"tokens": [1, 2, 3]})
            payload = json.loads(request.content)
            requests.append(payload)
            return httpx.Response(200, json={
                "choices": [{"message": {"role": "assistant", "content": "done"},
                             "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 1},
            })

        client = Client(config.services.model, budget, record, {},
                        transport=httpx.MockTransport(transport))
        self.addCleanup(client.close)
        permit = ledger.reserve("test", None, 30)
        with client.permitted(permit):
            client.chat([{"role": "user", "content": "self-authored"}], max_tokens=None)
        self.assertEqual(requests[0]["max_tokens"], config.services.model.max_model_len - 3)
        self.assertEqual(ledger.snapshot()["known_output_tokens"], 1)

    def test_repeated_empty_recovery_uses_distinct_stages(self):
        ctx = SimpleNamespace(record=self.record(), store={"guided": {
            "settings": {"solve_empty_recovery_limit": None, "first_tools_s": 0},
            "request_outcomes": {},
            "ledger": SimpleNamespace(snapshot=lambda: {"permits": []}),
        }})
        empty = SimpleNamespace(content="", finish_reason="stop", call_id="empty")
        final = SimpleNamespace(content="complete", finish_reason="stop", call_id="final")
        with patch.object(guided, "_request", side_effect=[empty, final]) as request:
            result = guided._recover_empty(ctx, "solve", empty,
                lambda: [{"role": "user", "content": "self-authored"}],
                {"max_tokens": None, "timeout_s": 900})
        self.assertIs(result, final)
        self.assertEqual([call.args[1] for call in request.call_args_list],
                         ["solve_recovery", "solve_recovery_2"])
        self.assertEqual(ctx.store["guided"]["solve_recovery_attempts"], 2)

    def test_zero_tool_reserve_still_runs_structure_and_behavior(self):
        record = self.record()
        candidate = SimpleNamespace(id="c", code_hash="self-authored-hash")
        calls = []
        def call(stage, **kwargs):
            calls.append((stage, kwargs))
            return CheckResult("passed", "self-authored stub")
        data = {"settings": {"recheck_tools_s": 0, "adjudicate_limit": None},
                "assessments": {}, "observations": {}, "behaviors": {},
                "checker": SimpleNamespace(plan={}, checked_outputs=["y"], unchecked_outputs=[])}
        ctx = SimpleNamespace(store={"guided": data}, record=record, call=call,
                              budget=SimpleNamespace(remaining=lambda: 30),
                              candidates=SimpleNamespace(get=lambda _: candidate))
        assessment, _ = guided._check_structure(ctx, candidate, 0)
        self.assertTrue(assessment["structural_passed"])
        self.assertEqual([name for name, _ in calls], ["interface", "lint", "synth"])
        self.assertTrue(all(kwargs["timeout_s"] > 0 for _, kwargs in calls[1:]))
        trace = SimpleNamespace(status="error", failure_kind="environment", summary="stub",
                                public_dict=lambda: {"status": "error"})
        with patch.object(guided, "observe", return_value=trace) as observe:
            guided.run_checker(ctx, State({"target_id": "c"}))
        self.assertEqual(observe.call_args.kwargs["timeout_s"], 30)

    def test_stopped_unlimited_repair_does_not_recheck_forever(self):
        ctx = SimpleNamespace(store={"guided": {"settings": {},
                              "repair_request_stopped": True}},
                              candidates=SimpleNamespace(get=lambda _: object()))
        with patch.object(guided, "_check_structure") as check:
            state = guided.structure(ctx, State({"target_id": "c", "method": "table"}))
        self.assertEqual(state["action"], "finish")
        check.assert_not_called()

    def test_unlimited_graph_still_checks_deadline_each_step(self):
        from agent.orchestration import graph
        from agent.runtime.budget import BudgetExhausted
        budget = SimpleNamespace(deadline_s=900)
        budget.timeout = unittest.mock.Mock(side_effect=[900, BudgetExhausted("expired")])
        ctx = SimpleNamespace(config=SimpleNamespace(runtime=SimpleNamespace(max_steps=None)),
                              budget=budget)
        app = SimpleNamespace(step=unittest.mock.Mock(return_value=(
            SimpleNamespace(name="continue"), None, State())))
        with patch.object(graph, "build_graph", return_value=app):
            with self.assertRaises(BudgetExhausted):
                graph.run_graph(ctx)
        self.assertEqual(app.step.call_count, 1)
        self.assertEqual(budget.timeout.call_count, 2)

    def test_empty_recovery_with_real_ledger_stops_when_shared_time_expires(self):
        remaining = [900.0]
        record = self.record()
        ledger = CompletionLedger(SimpleNamespace(remaining=lambda: remaining[0]), record,
                                  max_calls=None, max_output_tokens=None)
        class Model:
            @contextmanager
            def permitted(self, permit):
                self.permit = permit
                permit._begin()
                try:
                    yield
                finally:
                    permit._finish()

            def chat(self, messages, **kwargs):
                self.permit._sent("recovery-completion", 100)
                self.permit._response({"usage": {"prompt_tokens": 2, "completion_tokens": 5}})
                remaining[0] = 0
                return SimpleNamespace(content="", finish_reason="stop", call_id="recovery-completion")

        data = {"settings": {"solve_empty_recovery_limit": None, "first_tools_s": 0,
                             "minimum_request_s": 0, "temperature": 0, "top_p": 1},
                "ledger": ledger, "attempted": set(), "request_outcomes": {}}
        ctx = SimpleNamespace(store={"guided": data}, record=record, llm=Model())
        empty = SimpleNamespace(content="", finish_reason="stop", call_id="initial")
        result = guided._recover_empty(ctx, "solve", empty,
            lambda: [{"role": "user", "content": "self-authored"}],
            {"max_tokens": None, "timeout_s": 900})
        self.assertIsNone(result)
        self.assertEqual(ledger.snapshot()["calls_sent"], 1)
        self.assertEqual(data["solve_recovery_attempts"], 2)
        self.assertEqual(data["solve_recoveries_sent"], 1)
        self.assertEqual(data["request_outcomes"]["solve_recovery_2"],
                         {"status": "not_sent", "reason": "insufficient_followup_time"})

    def test_recovery_denied_by_ledger_does_not_spin(self):
        ctx = SimpleNamespace(record=self.record(), store={"guided": {
            "settings": {"solve_empty_recovery_limit": None, "first_tools_s": 0},
            "ledger": SimpleNamespace(snapshot=lambda: {"permits": []}),
        }})
        empty = SimpleNamespace(content="", finish_reason="length", call_id="empty")
        with patch.object(guided, "_request", return_value=None) as request:
            result = guided._recover_empty(ctx, "solve", empty,
                lambda: [{"role": "user", "content": "self-authored"}], {})
        self.assertIsNone(result)
        self.assertEqual(request.call_count, 1)


if __name__ == "__main__":
    unittest.main()
