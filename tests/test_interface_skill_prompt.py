"""The packaged interface method must preserve guided RTL output instructions."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from agent.context.prompts import TemplateRenderer
from agent.domain.knowledge.assets import load_assets
from agent.domain.rtl.task import TaskSpec
from agent.kit import State
from agent.orchestration.nodes import guided


class InterfaceSkillPromptTests(unittest.TestCase):
    def test_real_generate_and_repair_requests_use_internal_interface_checklist(self):
        identity = "rtl-module-interface-contract"
        assets = load_assets(skills=True)
        task = TaskSpec.from_text(
            "interface-method",
            "Implement module RequiredTop(input a, output y); "
            "Output y must equal the inverse of a. Do not change the top name.",
        )
        self.assertFalse(task.interface)  # Public prompt is sufficient interface evidence.
        parent = SimpleNamespace(
            id="candidate", code_hash="parent-hash",
            code="module RequiredTop(input a, output y); MissingHelper u(a, y); endmodule",
        )
        data = {
            "settings": {"solve": {"timeout_s": 1, "max_tokens": 100}, "first_tools_s": 1},
            "plan": {"skills": [identity], "knowledge": []},
            "skill_assets": assets,
            "structure_repairs": 0,
            "assessments": {parent.id: {"checks": {"lint": {
                "status": "failed", "failure_kind": "code",
                "excerpt": "Module <MissingHelper> not found while processing module instance <u>",
            }}}},
        }
        artifacts = {}
        ctx = SimpleNamespace(
            task=task, prompts=TemplateRenderer(), store={"guided": data},
            candidates=SimpleNamespace(get=lambda identity: parent),
            record=SimpleNamespace(
                emit=lambda *args, **kwargs: None,
                write_json=lambda name, value: artifacts.update({name: value}),
            ),
        )
        requests = []

        def capture(ctx, stage, messages, *args, **kwargs):
            requests.append((stage, messages))
            return None

        with patch.object(guided, "_request", side_effect=capture), \
             patch.object(guided, "_candidate", return_value=None):
            guided.solve(ctx, State({}))
            guided.repair_structure(ctx, State({"target_id": parent.id}))

        self.assertEqual([stage for stage, _ in requests], ["solve", "repair_structure"])
        for stage, messages in requests:
            with self.subTest(stage=stage):
                system, user = (message["content"] for message in messages)
                self.assertIn("exactly one fenced ```verilog code block", system)
                self.assertIn(task.prompt, user)
                self.assertIn(f"[Skill {identity}]", user)
                self.assertIn("This checklist is internal method material", user)
                self.assertIn("with no text outside it", user)
                self.assertIn("check explicit module and", user)
                self.assertIn("functional fixes when the task or current feedback requires them", user)
                self.assertNotIn("Respond with a structured analysis", user)
                self.assertNotIn("report all rules as N/A", user)
                self.assertNotIn("still report all five in the table", user)
        for name in ("guided/material.json", "guided/material-repair_structure.json"):
            self.assertEqual(artifacts[name]["sent"], [identity])
            self.assertEqual(artifacts[name]["cards_sent"], [])
        self.assertIn("MissingHelper", requests[-1][1][-1]["content"])

    def test_packaged_method_distinguishes_missing_helpers_and_tool_limits(self):
        _, body = load_assets(skills=True)["skills"]["rtl-module-interface-contract"]
        self.assertIn("If `X` is a helper", body)
        self.assertIn("preserving the required top", body)
        self.assertNotIn("Rename the module to exactly `X`", body)
        self.assertIn("leave extra ports unconnected without an elaboration error", body)
        self.assertIn("warning or implicit padding/truncation", body)
        self.assertIn("success alone does", body)
        self.assertIn("not prove exact interface agreement or functional correctness", body)
        self.assertNotIn("Every interface fault scores L0", body)


if __name__ == "__main__":
    unittest.main()
