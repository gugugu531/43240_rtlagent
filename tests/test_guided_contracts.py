"""guided_verify flat plan, checker table, and adjudication contracts."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from agent.domain.rtl.guided_adjudicate import AdjudicationError, parse_adjudication
from agent.domain.rtl.guided_checker import (
    CheckerError,
    evaluate_checker,
    parse_checker,
)
from agent.domain.rtl.guided_plan import PlanError, parse_plan
from agent.domain.rtl.observation import TraceRun, sampling_hash
from agent.domain.rtl.task import TaskSpec
from agent.kit import State
from agent.context.prompts import TemplateRenderer
from agent.domain.knowledge import guided as knowledge
from agent.orchestration.nodes import guided


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
    plan = checker.plan
    rows = []
    for ci, case in enumerate(plan["cases"]):
        tick = 0
        for si, step in enumerate(case["steps"]):
            for phase in ("pre", "post"):
                if phase == "post":
                    tick += 1
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
                        expected = checker.cases[ci].expected.get(si, {}).get(name, 0)
                        values[name] = {"bits": expected, "known": full, "width": width}
                rows.append({
                    "case_id": case["id"], "case_index": ci, "step": si,
                    "clock_tick": tick, "phase": phase, "sample": True,
                    "edge": step["edge"], "values": values,
                })
    return rows


class GuidedContractTests(unittest.TestCase):
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
                "Reset sets q to 1; load sets q to data; otherwise hold.",
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
        data = {
            "settings": {
                "checker": {"timeout_s": 1, "max_tokens": 1},
                "first_tools_s": 1,
                "max_cases": 4,
                "max_steps_per_case": 8,
                "init_cycles": 2,
            },
            "plan": {"focus": []},
            "checker_rebuild_context": None,
            "checker_rebuilds": 0,
        }
        artifacts = {}
        ctx = SimpleNamespace(
            task=task(),
            store={"guided": data},
            record=SimpleNamespace(
                write_json=lambda name, value: artifacts.update({name: value}),
                emit=lambda *args, **kwargs: None,
            ),
        )
        reply = SimpleNamespace(
            content="case empty\n", finish_reason="stop", call_id="m1"
        )
        with patch.object(guided, "_request", return_value=reply):
            state = guided.build_checker(ctx, State())
        self.assertEqual(state["checker_status"], "invalid")
        self.assertEqual(
            artifacts["guided/checker-error.json"]["status"], "invalid"
        )

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

    def test_repeated_repairs_use_distinct_stage_names(self):
        self.assertEqual(guided._attempt_stage("repair", 1), "repair")
        self.assertEqual(guided._attempt_stage("repair", 2), "repair_2")

        parent = SimpleNamespace(id="c1", code_hash="h")
        child = SimpleNamespace(id="c2", code_hash="h2")
        data = {
            "settings": {
                "solve": {"timeout_s": 1, "max_tokens": 1},
                "first_tools_s": 1,
            },
            "assessments": {"c1": {"checks": {}}},
            "structure_repairs": 0,
            "behavior_repairs": 0,
            "behavior": {"failed": [], "unknown": []},
            "checker_text": "",
        }
        ctx = SimpleNamespace(
            store={"guided": data},
            candidates=SimpleNamespace(get=lambda candidate_id: parent),
            prompts=SimpleNamespace(
                render=lambda *args, **kwargs: [{"role": "user", "content": "x"}]
            ),
            task=object(),
        )
        stages = []

        def fake_request(ctx_arg, stage, *args, **kwargs):
            stages.append(stage)
            return SimpleNamespace(
                call_id=stage, content="", finish_reason="stop"
            )

        with patch.object(guided, "_request", side_effect=fake_request), \
             patch.object(guided, "_candidate", return_value=child):
            guided.repair_structure(ctx, State({"target_id": "c1"}))
            guided.repair_structure(ctx, State({"target_id": "c1"}))
            guided.repair_behavior(ctx, State({"target_id": "c1"}))
            guided.repair_behavior(ctx, State({"target_id": "c1"}))
        self.assertEqual(
            stages,
            [
                "repair_structure",
                "repair_structure_2",
                "repair_behavior",
                "repair_behavior_2",
            ],
        )

    def test_finish_does_not_mix_child_behavior_with_parent_structure(self):
        data = {
            "method": "table",
            "assessments": {
                "parent": {"structural_passed": True},
                "child": {"structural_passed": False},
            },
            "behaviors": {
                "parent": {
                    "checker_hash": "checker",
                    "behavior": {"status": "failed"},
                },
                "child": {
                    "checker_hash": "checker",
                    "behavior": {"status": "passed", "compared_bits": 2},
                },
            },
            "checker_hash": "checker",
            "checker_status": "valid",
            "structure_repairs": 1,
            "behavior_repairs": 1,
            "checker_rebuilds": 0,
            "adjudications": 1,
            "request_outcomes": {},
            "ledger": SimpleNamespace(snapshot=lambda: {}),
        }
        artifacts = {}
        ctx = SimpleNamespace(
            store={
                "guided": data,
                "submission": SimpleNamespace(
                    finalize=lambda reason: {
                        "final": {"published": True, "target_id": "parent"}
                    }
                ),
            },
            candidates=SimpleNamespace(
                selected_id="parent",
                select=lambda candidate_id, reason: setattr(
                    ctx.candidates, "selected_id", candidate_id
                ),
            ),
            record=SimpleNamespace(
                write_json=lambda name, value: artifacts.update({name: value}),
                emit=lambda *args, **kwargs: None,
            ),
        )
        state = guided.finish(ctx, State({"target_id": "child"}))
        result = artifacts["guided/result.json"]
        self.assertEqual(state["status"], "stopped")
        self.assertEqual(result["selected_id"], "parent")
        self.assertEqual(result["evidence_candidate_id"], "parent")
        self.assertFalse(result["functional_passed"])
        self.assertEqual(result["behavior"]["status"], "failed")

    def test_finish_reports_the_published_child_not_the_selected_parent(self):
        data = {
            "method": "structural",
            "assessments": {
                "parent": {"structural_passed": True},
                "child": {"structural_passed": False},
            },
            "behaviors": {},
            "checker_hash": None,
            "checker_status": "not_requested",
            "structure_repairs": 1,
            "behavior_repairs": 0,
            "checker_rebuilds": 0,
            "adjudications": 0,
            "request_outcomes": {},
            "ledger": SimpleNamespace(snapshot=lambda: {}),
        }
        artifacts = {}
        ctx = SimpleNamespace(
            store={
                "guided": data,
                "submission": SimpleNamespace(
                    finalize=lambda reason: {
                        "final": {"published": True, "target_id": "child"}
                    }
                ),
            },
            candidates=SimpleNamespace(selected_id="parent"),
            record=SimpleNamespace(
                write_json=lambda name, value: artifacts.update({name: value}),
                emit=lambda *args, **kwargs: None,
            ),
        )
        state = guided.finish(ctx, State({"target_id": "child"}))
        result = artifacts["guided/result.json"]
        self.assertEqual(state["status"], "stopped")
        self.assertEqual(result["selected_id"], "parent")
        self.assertEqual(result["evidence_candidate_id"], "child")
        self.assertEqual(result["published_id"], "child")
        self.assertFalse(result["structural_passed"])

    def test_dense_guided_shortlist_uses_embedding(self):
        from agent.domain.knowledge.embedding import settings

        class Response:
            def __init__(self, payload):
                self.payload = payload

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
            record=SimpleNamespace(emit=lambda *args, **kwargs: None),
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
            "plan": None,
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
        # Force one actual value to differ from the expected 0x02.
        trace.rows[1]["values"]["q"]["bits"] = 1
        result = evaluate_checker(checker, trace)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failed"][0]["signal"], "q")

    def test_adjudication_is_flat_and_bounded(self):
        value = parse_adjudication(
            "decision=solution_error\nreason=reset mismatch\nfailed_cases=reset",
            case_ids=["reset"],
        )
        self.assertEqual(value.decision, "solution_error")
        with self.assertRaises(AdjudicationError):
            parse_adjudication("decision=maybe\nreason=x", case_ids=[])


if __name__ == "__main__":
    unittest.main()
