"""Guided role contracts and replay of archived plan, table and attribution formats."""

from contextlib import contextmanager
import copy
import json
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from agent.domain.rtl.candidate import CandidateStore
from agent.domain.rtl.guided_adjudicate import AdjudicationError, parse_adjudication
from agent.domain.rtl.guided_checker import (
    CheckerError,
    evaluate_checker,
    parse_checker,
)
from agent.domain.rtl.guided_plan import PlanError, parse_plan
from agent.domain.rtl.observation import TraceRun, sampling_hash
from agent.domain.rtl.result import CheckResult
from agent.domain.rtl.task import TaskSpec
from agent.kit import State
from agent.context.prompts import TemplateRenderer
from agent.domain.knowledge import guided as knowledge
from agent.orchestration.nodes import guided
from agent.orchestration.workflows.guided_verify import GuidedParameters


PROMPT = """Implement a module named TopModule with the following interface.
 - input clk
 - input reset
 - input load
 - input data (8 bits)
 - output q (8 bits)
On each positive clock edge, reset sets q to 1; load sets q to data;
otherwise q keeps its value."""


TWO_OUTPUT_PROMPT = """Implement a module named TopModule with the following interface.
 - input clk
 - input reset
 - input load
 - input data (8 bits)
 - output q (8 bits)
 - output z (8 bits)
On each positive clock edge, reset sets q and z to 1; load sets q and z to data;
otherwise both keep their values."""


def task():
    return TaskSpec.from_text("guided", PROMPT)


def rows_for(checker):
    """Simulate our public register (reset to one, load data, otherwise hold)."""
    plan = checker.plan
    rows = []
    for ci, case in enumerate(plan["cases"]):
        tick = 0
        stored = None
        for si, step in enumerate(case["steps"]):
            for phase in ("pre", "post"):
                if phase == "post":
                    tick += 1
                    if step["inputs"]["reset"]:
                        stored = 1
                    elif step["inputs"]["load"]:
                        stored = step["inputs"]["data"]
                values = {}
                for name, port in plan["ports"].items():
                    width = port["width"]
                    full = (1 << width) - 1
                    if port["direction"] == "input":
                        if name == plan["clock"]["port"]:
                            number = 1 if phase == "post" else 0
                        else:
                            number = step["inputs"][name] & full
                        values[name] = {"bits": number, "known": full, "width": width}
                    else:
                        values[name] = {"bits": (stored or 0) & full,
                                        "known": full if stored is not None else 0, "width": width}
                rows.append({
                    "case_id": case["id"], "case_index": ci, "step": si,
                    "clock_tick": tick, "phase": phase, "sample": True,
                    "edge": step["edge"], "values": values,
                })
    return rows


class GuidedContractTests(unittest.TestCase):
    def node_context(self, *, max_calls=8):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        artifacts = {}
        record = SimpleNamespace(
            write_json=lambda name, value: artifacts.update({name: copy.deepcopy(value)}),
            write_text=lambda name, value: artifacts.update({name: value}),
            emit=lambda *args, **kwargs: None,
        )
        ctx = SimpleNamespace(
            task=task(), store={}, record=record, artifacts=artifacts, prompts=TemplateRenderer(),
            candidates=CandidateStore(record, directory.name), budget=SimpleNamespace(remaining=lambda: 1000.0),
        )
        guided.initialize(ctx, State({"settings": GuidedParameters(max_calls=max_calls).model_dump()}))
        ctx.store["guided"].update(method="table", plan_source="planner", plan={"skills": [], "knowledge": []})
        return ctx

    def draft(self, ctx, constant, parent=None):
        code = f"module TopModule(input clk, reset, load, input [7:0] data, output [7:0] q); assign q={constant}; endmodule"
        candidate = ctx.candidates.create(code, parent_id=parent.id if parent else None,
                                          round=parent.round + 1 if parent else 1, source_stage="synthetic")
        ctx.store["submission"].register(candidate, reason="synthetic draft")
        return candidate

    def assess(self, ctx, candidate, **checks):
        ctx.call = lambda stage, **kwargs: checks.get(stage, CheckResult("passed", f"synthetic {stage}", rc=0))
        return guided.structure(ctx, State({"target_id": candidate.id, "method": "table"}))

    def test_plan_is_flat_and_ids_are_checked(self):
        plan = parse_plan(
            "method=table\nskills=rtl-sequential-state-update\n"
            "knowledge=card-a\nfocus=reset|load\nreason=sequential",
            skill_ids=["rtl-sequential-state-update"],
            card_ids=["card-a"],
        )
        self.assertEqual(plan.method, "table")
        self.assertEqual(plan.skills, ("rtl-sequential-state-update",))
        self.assertEqual(plan.focus, ("reset", "load"))
        filtered = parse_plan(
            "method=table\nskills=other\nknowledge=missing",
            skill_ids=[], card_ids=[],
        )
        self.assertEqual(filtered.skills, ())
        self.assertEqual(filtered.knowledge, ())
        with self.assertRaises(PlanError):
            parse_plan("{\"method\":\"table\"}", skill_ids=[], card_ids=[])

    def test_checker_requires_init_and_all_non_clock_inputs(self):
        checker = parse_checker(
            "case reset\ninit reset=1 load=0 data=00 q=01\n"
            "step reset=0 load=1 data=a5 q=a5\n",
            task(), init_cycles=2,
        )
        self.assertEqual(checker.cases[0].init_count, 2)
        self.assertIn(1, checker.cases[0].expected)  # after final init edge
        self.assertIn(2, checker.cases[0].expected)
        with self.assertRaises(CheckerError):
            parse_checker("case reset\nstep reset=0 load=0 data=00 q=01\n", task())
        with self.assertRaises(CheckerError):
            parse_checker("case c\ninit reset=1 load=0 q=01\n", task())
        with self.assertRaises(CheckerError):
            parse_checker("case empty\n", task())
        with self.assertRaises(CheckerError):
            parse_checker("case empty\ncase reset\ninit reset=1 load=0 data=00 q=01\n", task())
        with self.assertRaises(CheckerError):
            parse_checker(
                "case c\ninit reset=1 load=0 data=00 q=01\n"
                "step reset=0 load=0 data=00 q=01 z=02\n",
                TaskSpec.from_text(
                    "x", "module TopModule(input clk, input reset, output q, output z); endmodule"
                ),
            )

    def test_checker_evaluation_passes_and_reports_partial_outputs(self):
        checker = parse_checker(
            "case reset\ninit reset=1 load=0 data=00 q=01\n"
            "step reset=0 load=1 data=a5 q=a5\n",
            task(),
        )
        trace = TraceRun(
            "complete", sampling_hash(checker.plan), "a" * 64, "exec",
            rows_for(checker), "ok",
        )
        result = evaluate_checker(checker, trace)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["unchecked_outputs"], [])

        checker = parse_checker(
            "case reset\ninit reset=1 load=0 data=00 q=01\n",
            TaskSpec.from_text(
                "x",
                "Implement a module named TopModule with the following interface.\n"
                " - input clk\n - input reset\n - input load\n"
                " - input data (8 bits)\n - output q (8 bits)\n - output z\n"
                "On each positive clock edge, reset sets q to 1; load sets q to data; otherwise hold.",
            ),
        )
        # z is public but not checked; host must report partial, not full pass.
        trace = TraceRun(
            "complete", sampling_hash(checker.plan), "b" * 64, "exec2",
            rows_for(checker), "ok",
        )
        result = evaluate_checker(checker, trace)
        self.assertEqual(result["status"], "partial_passed")
        self.assertEqual(result["unchecked_outputs"], ["z"])

    def test_empty_case_is_reported_as_invalid_checker(self):
        ctx = self.node_context(max_calls=2)
        reply = SimpleNamespace(
            content="case empty # Reset check.\n", finish_reason="stop", call_id="m1"
        )
        def send(ctx, stage, messages, limits, **kwargs):
            permit = ctx.store["guided"]["ledger"].reserve(stage, **limits)
            permit._begin()
            permit._sent(reply.call_id, limits["max_tokens"])
            permit._response({"usage": {"prompt_tokens": 3, "completion_tokens": 6}})
            permit._finish()
            return reply
        with patch.object(guided, "_request", side_effect=send) as request:
            state = guided.build_checker(ctx, State())
        self.assertEqual(request.call_count, 1)
        self.assertEqual(state["checker_status"], "invalid")
        self.assertEqual(ctx.artifacts["guided/checker-error.json"]["status"], "invalid")
        self.assertIn("case has no lines", ctx.artifacts["guided/checker-error.json"]["reason"])

    def test_partial_outputs_in_any_case_are_not_a_full_pass(self):
        checker = parse_checker(
            "case q_only\ninit reset=1 load=0 data=00 q=01\n"
            "case z_only\ninit reset=1 load=0 data=00 z=01\n",
            TaskSpec.from_text("two", TWO_OUTPUT_PROMPT),
        )
        trace = TraceRun(
            "complete", sampling_hash(checker.plan), "d" * 64, "exec4",
            rows_for(checker), "ok",
        )
        result = evaluate_checker(checker, trace)
        self.assertEqual(result["status"], "partial_passed")
        self.assertEqual(result["unchecked_outputs"], ["q", "z"])


    def test_repeated_structure_repairs_and_author_decisions_use_distinct_permits(self):
        ctx = self.node_context(max_calls=4)
        data = ctx.store["guided"]
        parent = self.draft(ctx, 0)
        rtl = parent.code
        replies = iter([
            rtl.replace("assign q=0", "assign q=1"),
            rtl.replace("assign q=0", "assign q=2"),
            "action=revise\nreason=Drive the requested bit.\n```verilog\n"
            + rtl.replace("assign q=0", "assign q=3") + "\n```",
            "action=submit\nreason=Submit the revised implementation.",
        ])

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
                permit = self.permit
                permit._sent(permit.id, kwargs["max_tokens"])
                permit._response({"usage": {"prompt_tokens": 1, "completion_tokens": 1}})
                return SimpleNamespace(call_id=permit.id, content=next(replies), finish_reason="stop")

        ctx.llm = Model()
        candidate = parent
        for _ in range(2):
            state = self.assess(ctx, candidate, lint=CheckResult("failed", "syntax", rc=1, failure_kind="code"))
            self.assertEqual(state["action"], "repair_structure")
            child_state = guided.repair_structure(ctx, state)
            child = ctx.candidates.get(child_state["target_id"])
            self.assertEqual(child.parent_id, candidate.id)
            self.assertNotEqual(child.code_hash, candidate.code_hash)
            candidate = child

        data.update(checker_status="unavailable", checker_notice="Synthetic checker unavailable.")
        state = self.assess(ctx, candidate)
        self.assertEqual(state["action"], "author_decision")
        revision = guided.author_decision(ctx, state)
        self.assertEqual(revision["action"], "revise")
        child = ctx.candidates.get(revision["target_id"])
        self.assertEqual(child.parent_id, candidate.id)
        state = self.assess(ctx, child)
        self.assertEqual(state["action"], "author_decision")
        submitted = guided.author_decision(ctx, state)
        self.assertEqual(submitted["action"], "submit")
        self.assertEqual(ctx.candidates.selected_id, child.id)
        self.assertEqual(guided.finish(ctx, submitted)["status"], "completed")

        stages = {"repair_structure", "repair_structure_2", "author_decision", "author_decision_2"}
        self.assertEqual(data["attempted"], stages)
        self.assertEqual(data["ledger"].snapshot()["calls_sent"], 4)
        self.assertEqual({row["stage"] for row in data["history"]}, stages)
        self.assertTrue(all(data["request_outcomes"][stage]["status"] == "returned" for stage in stages))
        self.assertTrue(all(f"guided/material-{stage}.json" in ctx.artifacts for stage in stages))
        with self.assertRaisesRegex(ValueError, "may only request once"):
            guided._request(ctx, "author_decision", [], data["settings"]["solve"])

    def test_fallback_uses_only_the_published_parents_current_behavior(self):
        ctx = self.node_context()
        data = ctx.store["guided"]
        table = "case reset # Reset sets q to one.\ninit reset=1 load=0 data=00 q=01"
        guided._set_checker(ctx, parse_checker(table, ctx.task, require_explanations=True), table)
        parent = self.draft(ctx, 1)
        self.assertEqual(self.assess(ctx, parent)["action"], "run_checker")
        child = self.draft(ctx, 0, parent)
        self.assertEqual(self.assess(ctx, child, lint=CheckResult("failed", "syntax", rc=1,
                                                                failure_kind="code"))["action"], "repair_structure")
        for candidate, verdict in ((parent, "failed"), (child, "passed")):
            data["behaviors"][candidate.id] = {
                "candidate_hash": candidate.code_hash, "checker_hash": data["checker_hash"],
                "checker_version": data["checker_version"],
                "behavior": {"status": verdict, "compared_bits": 2},
            }
        state = guided.finish(ctx, State({"target_id": child.id}))
        result = ctx.artifacts["guided/result.json"]
        self.assertEqual(state["status"], "stopped")
        self.assertEqual(result["submission_mode"], "fallback")
        self.assertEqual(result["fallback_basis"], "latest_toolchain_passed")
        self.assertEqual(result["published_id"], parent.id)
        self.assertEqual(result["behavior_candidate_id"], parent.id)
        self.assertEqual(result["evidence_candidate_id"], parent.id)
        self.assertEqual(result["behavior"]["status"], "failed")
        self.assertFalse(result["functional_passed"])
        self.assertEqual((ctx.candidates.output_dir / "solution.v").read_text(), parent.code)

    def test_fallback_publishes_latest_complete_child_without_inheriting_parent_evidence(self):
        ctx = self.node_context()
        parent = self.draft(ctx, 0)
        state = self.assess(ctx, parent, lint=CheckResult("unavailable", "tool unavailable", failure_kind="environment"))
        self.assertEqual(state["action"], "author_decision")
        child = self.draft(ctx, 1, parent)
        state = guided.finish(ctx, State({"target_id": child.id}))
        result = ctx.artifacts["guided/result.json"]
        self.assertEqual(state["status"], "stopped")
        self.assertEqual(result["submission_mode"], "fallback")
        self.assertEqual(result["fallback_basis"], "latest_complete")
        self.assertIsNone(result["selected_id"])
        self.assertEqual(result["evidence_candidate_id"], child.id)
        self.assertEqual(result["published_id"], child.id)
        self.assertIsNone(result["behavior_candidate_id"])
        self.assertFalse(result["structural_passed"])
        self.assertFalse(result["functional_passed"])
        self.assertEqual((ctx.candidates.output_dir / "solution.v").read_text(), child.code)

    def test_dense_guided_shortlist_uses_embedding(self):
        from agent.domain.knowledge.embedding import settings

        class Response:
            def __init__(self, payload):
                self.payload = payload
                self.status_code = 200
                self.text = json.dumps(payload)

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        class Client:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def get(self, url):
                return Response({"data": [{"id": settings()["model_alias"]}]})

            def post(self, url, json):
                return Response({
                    "model": settings()["model_alias"],
                    "data": [{
                        "index": 0,
                        "embedding": [1.0] + [0.0] * (settings()["dimensions"] - 1),
                    }],
                })

        data = {
            "settings": {
                "retrieval_mode": "rag",
                "retrieval_strategy": "dense",
                "embedding_url": "http://127.0.0.1:8020",
                "embedding_timeout_s": 2.0,
                "knowledge_candidates": 3,
            },
            "retrieval": {},
        }
        ctx = SimpleNamespace(
            task=task(),
            store={"guided": data},
            record=SimpleNamespace(
                emit=lambda *args, **kwargs: None,
                write_json=lambda *args, **kwargs: None,
                write_text=lambda *args, **kwargs: None,
            ),
        )
        with patch("agent.domain.knowledge.embedding.httpx.Client", Client):
            skills, cards = guided._shortlist(ctx, 3)
        self.assertTrue(cards)
        self.assertEqual(data["retrieval"]["strategy"], "dense")
        self.assertTrue(data["retrieval"]["selected"])

    def test_selected_knowledge_reaches_the_solve_message(self):
        data = {
            "settings": {
                "planner": {"timeout_s": 1, "max_tokens": 1},
                "solve": {"timeout_s": 1, "max_tokens": 1},
                "first_tools_s": 1,
                "knowledge_candidates": 5,
                "knowledge_select": 3,
                "retrieval_mode": "rag",
                "retrieval_strategy": "bm25",
            },
            "method": "structural",
            "attempted": set(),
            "request_outcomes": {},
            "plan": None,
        }
        artifacts = {}
        ctx = SimpleNamespace(
            task=task(),
            prompts=TemplateRenderer(),
            store={"guided": data},
            record=SimpleNamespace(
                write_json=lambda name, value: artifacts.update({name: value}),
                emit=lambda *args, **kwargs: None,
            ),
        )
        card = guided._shortlist(ctx, 5)[1][0]
        plan_reply = SimpleNamespace(
            content=(
                "method=table\nskills=\n"
                f"knowledge={card['card_id']}\nfocus=reset\nreason=test"
            ),
            call_id="plan-1",
            finish_reason="stop",
        )
        sent = {}

        def fake_request(ctx_arg, stage, messages, *args, **kwargs):
            if stage == "plan":
                return plan_reply
            sent["messages"] = messages
            return SimpleNamespace(
                content="module TopModule; endmodule",
                call_id="solve-1",
                finish_reason="stop",
            )

        with patch.object(guided, "_request", side_effect=fake_request), \
             patch.object(guided, "_candidate", return_value=None):
            guided.plan(ctx, State({}))
            guided.solve(ctx, State({}))
        self.assertEqual(data["plan"]["knowledge"], [card["card_id"]])
        self.assertIn(knowledge.card_text(card), sent["messages"][-1]["content"])

    def test_forbidden_diagnostic_card_is_not_injected_into_first_draft(self):
        forbidden = next(
            card for card in knowledge.load_cards()
            if card["card_id"] == "diag-vrfc-10-1280"
        )
        self.assertFalse(knowledge.card_allowed(forbidden, "pre_generation"))
        data = {
            "plan": {"skills": [], "knowledge": [forbidden["card_id"]]},
            "settings": {"knowledge_select": 3},
        }
        ctx = SimpleNamespace(
            task=task(),
            store={"guided": data},
            prompts=TemplateRenderer(),
        )
        material, selection = guided._skill_and_card_material(ctx)
        self.assertNotIn(knowledge.card_text(forbidden), material)
        self.assertEqual(selection["cards_sent"], [])
        self.assertIn(
            "card_not_injectable_at_pre_generation",
            [row["reason"] for row in selection["rejected"]],
        )

    def test_mismatch_is_failed(self):
        checker = parse_checker(
            "case reset\ninit reset=1 load=0 data=00 q=02\n", task(), init_cycles=1
        )
        trace = TraceRun(
            "complete", sampling_hash(checker.plan), "c" * 64, "exec3",
            rows_for(checker), "ok",
        )
        # The public reset produces 0x01 while this checker incorrectly expects 0x02.
        result = evaluate_checker(checker, trace)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failed"][0]["signal"], "q")

    def test_archived_adjudication_is_flat_and_bounded(self):
        value = parse_adjudication(
            "decision=solution_error\nreason=reset mismatch\nfailed_cases=reset",
            case_ids=["reset"],
        )
        self.assertEqual(value.decision, "solution_error")
        with self.assertRaises(AdjudicationError):
            parse_adjudication("decision=maybe\nreason=x", case_ids=[])

    def test_archived_attribution_accounts_for_all_actual_failed_and_unknown_cases(self):
        for names in ("", "reset", "reset,reset", "reset,other", "reset,unknown,clean"):
            with self.subTest(names=names), self.assertRaises(AdjudicationError):
                parse_adjudication(f"decision=solution_error\nreason=guess\nfailed_cases={names}",
                                   case_ids={"reset", "unknown"})
        result = parse_adjudication("decision=mixed\nreason=two issues\nfailed_cases=unknown,reset",
                                    case_ids={"reset", "unknown"})
        self.assertEqual(result.decision, "mixed")


if __name__ == "__main__":
    unittest.main()
