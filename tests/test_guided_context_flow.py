"""Self-authored node integration checks for guided prompt context wiring."""

import copy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from agent.context.prompts import TemplateRenderer
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


if __name__ == "__main__":
    unittest.main()
