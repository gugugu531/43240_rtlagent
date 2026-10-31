"""Self-authored node integration checks for guided prompt context wiring."""

import copy
from contextlib import contextmanager
from tempfile import TemporaryDirectory
from pathlib import Path
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from agent.context.prompts import TemplateRenderer
from agent.domain.rtl.candidate import CandidateStore
from agent.llm.types import ModelError, Reply
from agent.runtime.allowance import CompletionLedger
from agent.submission.gateway import SubmissionGateway
from agent.domain.rtl.guided_checker import parse_checker
from agent.domain.rtl.task import TaskSpec
from agent.kit import State
from agent.orchestration.nodes import guided
from agent.orchestration.workflows.guided_verify import GuidedParameters


TABLE = "case reset\ninit reset=1 d=0 q=0\nstep reset=0 d=1 q=1\n"
PROMPT = "On each positive edge of clk, reset sets q to zero; otherwise q takes d."
INTERFACE = "module TopModule(input clk, input reset, input d, output q);"


class MemoryRecord:
    def __init__(self):
        self.artifacts = {}

    def write_text(self, name, value):
        self.artifacts[name] = value
        return name

    def emit(self, *args, **kwargs):
        pass

    def write_json(self, name, value):
        self.artifacts[name] = copy.deepcopy(value)
        return name


class GuidedContextFlowTests(unittest.TestCase):
    def context(self, *, prompt=PROMPT):
        task = TaskSpec.from_text("self-authored-context", prompt, INTERFACE)
        candidate = SimpleNamespace(
            id="candidate-current", code_hash="CURRENT_CANDIDATE_HASH",
            code="module TopModule; /* PRIVATE_CANDIDATE */ endmodule",
        )
        settings = GuidedParameters(max_cases=3, max_steps_per_case=5,
                                    init_cycles=3, knowledge_select=0).model_dump()
        data = {
            "settings": settings, "plan": {"skills": [], "knowledge": [], "focus": ["reset"]},
            "skill_assets": {
                "skills": {"rtl-behavior-check-keycases": (None, "Return a case/init/step table.")},
                "resources": {},
            },
            "assessments": {}, "structure_repairs": 0, "behavior_repairs": 0,
            "adjudications": 0, "checker_rebuilds": 0, "checker_rebuild_context": None,
            "checker": None, "checker_text": "", "checker_status": "not_built",
            "retrieval": {}, "behavior": {"failed": [], "unknown": []},
        }
        return SimpleNamespace(
            task=task, store={"guided": data}, record=MemoryRecord(),
            prompts=TemplateRenderer(), candidates=SimpleNamespace(get=lambda _: candidate),
        )

    def test_structure_repair_receives_root_diagnostics_after_warning_flood(self):
        ctx = self.context()
        data = ctx.store["guided"]
        warnings = "WARNING: unrelated declaration\n" * 200
        root_error = "ERROR: [VRFC 10-4982] syntax error near broken_token"
        diagnostics = {"root_errors": [{"message": root_error, "line": 91}]}
        data["assessments"]["candidate-current"] = {"checks": {
            "lint": {"status": "failed", "failure_kind": "code", "rc": 1,
                     "excerpt": warnings[:2000],
                     "details": {"repair_diagnostics": diagnostics}},
        }}
        with patch.object(guided, "_request", return_value=None) as request:
            guided.repair_structure(ctx, State({"target_id": "candidate-current"}))
        messages = request.call_args.args[2]
        body = messages[-1]["content"]
        self.assertNotIn(root_error, warnings[:2000])
        self.assertIn(root_error, body)
        self.assertIn(json.dumps(diagnostics), body)
        self.assertIn('"candidate_hash": "CURRENT_CANDIDATE_HASH"', body)
        self.assertIn('"candidate_id": "candidate-current"', body)
        self.assertIn("PRIVATE_CANDIDATE", body)

    def test_build_checker_sends_effective_limits_and_uses_same_init_count(self):
        ctx = self.context()
        reply = SimpleNamespace(content=TABLE, call_id="checker-call", finish_reason="stop")
        with patch.object(guided, "_request", return_value=reply) as request:
            state = guided.build_checker(ctx, State())
        self.assertEqual(state["checker_status"], "valid")
        body = request.call_args.args[2][-1]["content"]
        self.assertIn('"configured_limits":{"max_cases":3,"max_steps":5,"init_cycles":3}', body)
        self.assertIn('"max_table_lines_per_case":5', body)
        self.assertIn('"init_repeats":3', body)
        checker = ctx.store["guided"]["checker"]
        self.assertEqual(checker.cases[0].init_count, 3)
        self.assertEqual(set(checker.cases[0].expected), {2, 3})
        self.assertEqual(len(checker.plan["cases"][0]["steps"]), 4)

    def test_checker_rebuild_only_receives_allowed_failure_context(self):
        ctx = self.context()
        data = ctx.store["guided"]
        data.update({
            "checker_rebuilds": 1,
            "checker_rebuild_context": {"checker_text": TABLE, "failed_cases": ["reset"]},
            "behavior": {"failed": [{"actual_bits": "PRIVATE_MEASUREMENT"}]},
            "adjudication": {"decision": "checker_error", "reason": "PRIVATE_DIAGNOSIS"},
        })
        reply = SimpleNamespace(content=TABLE, call_id="rebuild-call", finish_reason="stop")
        with patch.object(guided, "_request", return_value=reply) as request:
            state = guided.build_checker(ctx, State())
        self.assertEqual(state["checker_status"], "valid")
        self.assertEqual(request.call_args.args[1], "checker_rebuild")
        messages = request.call_args.args[2]
        self.assertEqual([m["role"] for m in messages], ["system", "user"])
        body = messages[-1]["content"]
        self.assertIn(TABLE, body)
        self.assertIn("Failed case ids: reset", body)
        self.assertIn("Decision category: checker_error", body)
        self.assertIn('"init_repeats":3', body)
        for marker in ("PRIVATE_CANDIDATE", "PRIVATE_MEASUREMENT", "PRIVATE_DIAGNOSIS"):
            self.assertNotIn(marker, body)

    def test_adjudication_and_behavior_repair_share_execution_not_hidden_history(self):
        ctx = self.context()
        data = ctx.store["guided"]
        checker = parse_checker(TABLE, ctx.task, max_cases=3, max_steps=5, init_cycles=3)
        data.update({"checker": checker, "checker_text": TABLE,
                     "behavior": {"failed": [{"case_id": "reset", "step": 3,
                                                "signal": "q", "expected_bits": 1,
                                                "actual_bits": 0}], "unknown": []}})
        diagnosis = "Stored diagnosis: the load assignment does not update q."
        reply = SimpleNamespace(content="decision=solution_error\nreason=" + diagnosis +
                                "\nfailed_cases=reset", call_id="diagnosis-call", finish_reason="stop")
        with patch.object(guided, "_request", return_value=reply) as request:
            state = guided.adjudicate(ctx, State({"target_id": "candidate-current"}))
        self.assertEqual(state["action"], "repair_behavior")
        adjudication_body = request.call_args.args[2][-1]["content"]
        start = adjudication_body.index("\n\nHost execution contract and expanded sampling plan:\n")
        execution = json.loads(adjudication_body[start:].split("\n", 3)[3].split("\n\nObserved failures:")[0])
        self.assertEqual(execution["sampling_plan"], checker.plan)
        self.assertEqual(execution["contract"]["execution"]["init_repeats"], 3)
        self.assertIn("Zero-based index of the expanded event", adjudication_body)
        self.assertNotIn(diagnosis, adjudication_body)
        with patch.object(guided, "_request", return_value=None) as request:
            guided.repair_behavior(ctx, State({"target_id": "candidate-current"}))
        repair_body = request.call_args.args[2][-1]["content"]
        self.assertIn(json.dumps(execution, ensure_ascii=False), repair_body)
        self.assertIn(diagnosis, repair_body)
        self.assertIn("Prior diagnosis (untrusted hypothesis", repair_body)
        self.assertIn('"step": 3', repair_body)

    def test_host_downgrades_unsupported_table_and_records_capability_reason(self):
        ctx = self.context(prompt="On each negative edge of clk, q takes d.")
        reply = SimpleNamespace(content="method=table\nskills=\nknowledge=\nfocus=\nreason=try table",
                                call_id="plan-call", finish_reason="stop")
        with patch.object(guided, "_shortlist", return_value=([], [])), \
             patch.object(guided, "_request", return_value=reply) as request:
            state = guided.plan(ctx, State())
        self.assertEqual(state["method"], "structural")
        self.assertEqual(ctx.store["guided"]["method"], "structural")
        report = ctx.record.artifacts["guided/plan-capability.json"]
        self.assertEqual(report["requested"], "table")
        self.assertEqual(report["effective"], "structural")
        self.assertIn("falling-edge", report["reason"])
        self.assertIn('"supported":false', request.call_args.args[2][-1]["content"])



class GuidedEmptyRecoveryTests(unittest.TestCase):
    context = GuidedContextFlowTests.context
    RTL = "module TopModule(input clk, input reset, input d, output q); assign q=d; endmodule"

    def run_context(self, replies, *, remaining=840, max_calls=8, max_tokens=65536):
        ctx = self.context()
        data = ctx.store["guided"]
        data.update(attempted=set(), request_outcomes={}, method="structural",
                    observations={}, behaviors={}, checker_hash=None)
        ctx.budget = SimpleNamespace(remaining=lambda: remaining)
        data["ledger"] = CompletionLedger(ctx.budget, ctx.record,
                                           max_calls=max_calls, max_output_tokens=max_tokens)
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        ctx.candidates = CandidateStore(ctx.record, temporary.name)
        ctx.store["submission"] = SubmissionGateway(ctx)
        ctx.sent = []
        pending = iter(replies)

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
                ctx.sent.append((copy.deepcopy(messages), kwargs))
                response = next(pending)
                call = f"m{len(ctx.sent)}"
                if isinstance(response, dict) and "metadata_error" in response:
                    # Real metadata requests have their own call ids but never
                    # call permit._sent; only the completion does so.
                    raise response["metadata_error"]
                self.permit._sent(call, kwargs["max_tokens"])
                if isinstance(response, Exception):
                    self.permit._response({})
                    raise response
                content, finish, usage = response
                self.permit._response({"usage": usage})
                return Reply(call, content, finish,
                             usage.get("prompt_tokens") if usage else None,
                             usage.get("completion_tokens") if usage else None,
                             reasoning={"content": "PRIVATE_REASONING"})

        ctx.llm = Model()
        return ctx

    @staticmethod
    def response(content, finish="stop", usage=True):
        return content, finish, ({"prompt_tokens": 3, "completion_tokens": 7} if usage else None)

    def test_solve_stop_and_length_empty_recover_once_and_bind_actual_answer(self):
        for finish in ("stop", "length"):
            with self.subTest(finish=finish):
                ctx = self.run_context([self.response("", finish), self.response(self.RTL)])
                state = guided.solve(ctx, State())
                candidate = ctx.candidates.get(state["target_id"])
                self.assertEqual(candidate.source_call_id, "m2")
                self.assertEqual(candidate.source_stage, "guided_solve_recovery")
                self.assertEqual(len(ctx.sent), 2)
                self.assertEqual(ctx.store["guided"]["ledger"].snapshot()["calls_sent"], 2)
                self.assertEqual(ctx.store["guided"]["ledger"].snapshot()["known_output_tokens"], 14)
                first, second = (entry[0] for entry in ctx.sent)
                self.assertEqual([x["role"] for x in second], ["system", "user"])
                for marker in ("PRIVATE_REASONING", "PRIVATE_CANDIDATE", "PRIVATE_MEASUREMENT"):
                    self.assertNotIn(marker, str(second))
                self.assertIn(PROMPT, str(second))
                self.assertNotIn("Failure category", str(first))
                self.assertIn(f"Failure category: {finish}_no_final", str(second))
                self.assertEqual(ctx.sent[0][1]["profile"], ctx.sent[1][1]["profile"])
                data = ctx.store["guided"]
                data["assessments"][candidate.id] = {"structural_passed": True}
                guided.finish(ctx, state)
                result = ctx.record.artifacts["guided/result.json"]
                self.assertEqual(result["published_id"], candidate.id)
                self.assertEqual(result["evidence_candidate_id"], candidate.id)
                self.assertEqual(result["solve_recovery_attempts"], 1)
                self.assertEqual(result["solve_recoveries_sent"], 1)
                self.assertEqual(Path(ctx.candidates.output_dir, "solution.v").read_text(), candidate.code)
                self.assertEqual(ctx.record.artifacts["guided/solve-failure.json"]["kind"],
                                 f"{finish}_no_final")

    def test_repeated_empty_is_bounded_and_preserves_both_failures(self):
        for stage in ("solve", "checker"):
            with self.subTest(stage=stage):
                ctx = self.run_context([self.response("", "length"), self.response("", "stop")])
                state = getattr(guided, "build_checker" if stage == "checker" else "solve")(ctx, State())
                self.assertEqual(len(ctx.sent), 2)
                self.assertEqual(ctx.record.artifacts[f"guided/{stage}-failure.json"]["kind"],
                                 "length_no_final")
                self.assertEqual(ctx.record.artifacts[f"guided/{stage}_recovery-failure.json"]["kind"],
                                 "stop_no_final")
                self.assertEqual(ctx.store["guided"][f"{stage}_recovery_attempts"], 1)
                if stage == "checker":
                    self.assertEqual(state["checker_status"], "invalid")
                else:
                    self.assertIsNone(state["target_id"])
                self.assertEqual(len(ctx.candidates.values()), 0)

    def test_checker_recovery_is_independent_of_planner_candidate_and_measurements(self):
        ctx = self.run_context([self.response("", "stop"), self.response(TABLE)])
        data = ctx.store["guided"]
        data["plan"]["focus"] = ["PRIVATE_PLANNER_FORMULA"]
        data["behavior"] = {"actual": "PRIVATE_MEASUREMENT"}
        data["adjudication"] = {"reason": "PRIVATE_DIAGNOSIS"}
        state = guided.build_checker(ctx, State())
        self.assertEqual(state["checker_status"], "valid")
        self.assertEqual(data["checker_rebuilds"], 0)
        self.assertEqual(data["checker_recovery_attempts"], 1)
        self.assertEqual(data["checker_recoveries_sent"], 1)
        for messages, kwargs in ctx.sent:
            self.assertEqual([x["role"] for x in messages], ["system", "user"])
            self.assertIn(PROMPT, str(messages))
            for marker in ("PRIVATE_PLANNER_FORMULA", "PRIVATE_CANDIDATE", "PRIVATE_REASONING",
                           "PRIVATE_MEASUREMENT", "PRIVATE_DIAGNOSIS"):
                self.assertNotIn(marker, str(messages))
        self.assertEqual(ctx.sent[0][1]["profile"], ctx.sent[1][1]["profile"])

    def test_nonempty_invalid_unknown_finish_and_transport_error_do_not_retry(self):
        for stage in ("solve", "checker"):
            for response in (self.response("not a valid artifact"), self.response("", "other"),
                             ModelError("HTTP 500", kind="http", call_id="m1")):
                with self.subTest(stage=stage, response=response):
                    ctx = self.run_context([response])
                    getattr(guided, "build_checker" if stage == "checker" else "solve")(ctx, State())
                    self.assertEqual(len(ctx.sent), 1)
                    self.assertEqual(ctx.store["guided"].get(f"{stage}_recovery_attempts", 0), 0)
                    outcome = ctx.store["guided"]["request_outcomes"][stage]
                    if isinstance(response, Exception):
                        self.assertEqual(outcome["status"], "error")
                        self.assertEqual(outcome["kind"], "http")
                    else:
                        self.assertEqual(outcome["failure_kind"],
                                         "empty_unknown_finish" if not response[0]
                                         else ("invalid_rtl" if stage == "solve" else "invalid_checker"))

    def test_recovery_denied_by_calls_tokens_unknown_usage_and_time(self):
        for stage in ("solve", "checker"):
            for denial in ("call_limit", "output_token_limit", "unknown_usage", "insufficient_followup_time"):
                with self.subTest(stage=stage, denial=denial):
                    ctx = self.run_context([self.response("", usage=denial != "unknown_usage")],
                                           max_calls=1 if denial == "call_limit" else 8,
                                           max_tokens=(16384 if stage == "solve" else 8192)
                                           if denial == "output_token_limit" else 65536)
                    if denial == "insufficient_followup_time":
                        original_chat = ctx.llm.chat
                        def consume_time(*args, **kwargs):
                            reply = original_chat(*args, **kwargs)
                            ctx.budget.remaining = lambda: 139
                            return reply
                        ctx.llm.chat = consume_time
                    getattr(guided, "build_checker" if stage == "checker" else "solve")(ctx, State())
                    self.assertEqual(len(ctx.sent), 1)
                    data = ctx.store["guided"]
                    self.assertEqual(data[f"{stage}_recovery_attempts"], 1)
                    self.assertEqual(data[f"{stage}_recoveries_sent"], 0)
                    self.assertEqual(data["request_outcomes"][f"{stage}_recovery"],
                                     {"status": "not_sent", "reason": denial})

    def test_recovery_metadata_error_call_id_does_not_count_as_sent(self):
        for stage in ("solve", "checker"):
            for operation in ("tokenize", "apply-template"):
                with self.subTest(stage=stage, operation=operation):
                    ctx = self.run_context([
                        self.response(""),
                        {"metadata_error": ModelError(f"{operation} HTTP 500", kind="http",
                                                      call_id="metadata-m2")},
                    ])
                    getattr(guided, "build_checker" if stage == "checker" else "solve")(ctx, State())
                    data = ctx.store["guided"]
                    self.assertEqual(data[f"{stage}_recovery_attempts"], 1)
                    self.assertEqual(data[f"{stage}_recoveries_sent"], 0)
                    outcome = data["request_outcomes"][f"{stage}_recovery"]
                    self.assertEqual(outcome["status"], "error")
                    self.assertEqual(outcome["call_id"], "metadata-m2")
                    ledger = data["ledger"].snapshot()
                    self.assertEqual(ledger["calls_sent"], 1)
                    self.assertEqual(ledger["permits"][-1]["stage"], f"{stage}_recovery")
                    self.assertEqual(ledger["permits"][-1]["state"], "released")
                    self.assertIsNone(ledger["permits"][-1]["call_id"])
                    self.assertEqual(len(ctx.sent), 2)

    def test_recovery_http_error_counts_as_sent_without_another_retry(self):
        for stage in ("solve", "checker"):
            with self.subTest(stage=stage):
                ctx = self.run_context([self.response(""),
                                        ModelError("HTTP 500", kind="http", call_id="m2")])
                getattr(guided, "build_checker" if stage == "checker" else "solve")(ctx, State())
                self.assertEqual(len(ctx.sent), 2)
                data = ctx.store["guided"]
                self.assertEqual(data[f"{stage}_recovery_attempts"], 1)
                self.assertEqual(data[f"{stage}_recoveries_sent"], 1)
                ledger = data["ledger"].snapshot()
                self.assertEqual(ledger["calls_sent"], 2)
                self.assertEqual(ledger["permits"][-1]["state"], "settled")
                self.assertEqual(ledger["permits"][-1]["call_id"], "m2")
                self.assertEqual(data["request_outcomes"][f"{stage}_recovery"]["status"], "error")
                self.assertEqual(ctx.record.artifacts[f"guided/{stage}-failure.json"]["kind"],
                                 "stop_no_final")

    def test_checker_rebuild_empty_does_not_get_an_initial_recovery(self):
        ctx = self.run_context([self.response("")])
        data = ctx.store["guided"]
        data.update(checker_rebuilds=1, checker_rebuild_context={"checker_text": TABLE,
                                                               "failed_cases": ["reset"]})
        state = guided.build_checker(ctx, State())
        self.assertEqual(state["checker_status"], "invalid")
        self.assertEqual(len(ctx.sent), 1)
        self.assertEqual(data.get("checker_recovery_attempts", 0), 0)
        self.assertIn("checker_rebuild", data["request_outcomes"])

    def test_planner_uses_minimum_solve_reserve_not_maximum_stage_timeout(self):
        ctx = self.run_context([self.response(
            "method=table\nskills=\nknowledge=\nfocus=reset\nreason=public reset")])
        settings = ctx.store["guided"]["settings"]
        settings["solve"]["timeout_s"] = 900
        with patch.object(guided, "_shortlist", return_value=([], [])):
            state = guided.plan(ctx, State())
        self.assertEqual(state["method"], "table")
        permit = ctx.store["guided"]["ledger"].snapshot()["permits"][0]
        self.assertEqual(permit["followup_s"], 240)
        self.assertEqual(permit["timeout_s"], 90)
        self.assertLessEqual(permit["timeout_s"] + permit["followup_s"], 840)

    def test_unsupported_public_contract_does_not_send_checker(self):
        ctx = self.run_context([])
        ctx.task = TaskSpec.from_text("negative", "On each negative edge of clk, q takes d.", INTERFACE)
        state = guided.build_checker(ctx, State())
        self.assertEqual(state["checker_status"], "invalid")
        self.assertEqual(ctx.sent, [])
        self.assertEqual(ctx.record.artifacts["guided/checker-error.json"]["status"], "unsupported")

    def test_disabled_recovery_preserves_initial_failure(self):
        for stage in ("solve", "checker"):
            with self.subTest(stage=stage):
                ctx = self.run_context([self.response("")])
                ctx.store["guided"]["settings"][f"{stage}_empty_recovery_limit"] = 0
                getattr(guided, "build_checker" if stage == "checker" else "solve")(ctx, State())
                self.assertEqual(len(ctx.sent), 1)
                self.assertEqual(ctx.store["guided"].get(f"{stage}_recovery_attempts", 0), 0)
                self.assertEqual(ctx.record.artifacts[f"guided/{stage}-failure.json"]["kind"], "stop_no_final")


if __name__ == "__main__":
    unittest.main()
