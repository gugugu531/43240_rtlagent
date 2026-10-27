"""Cross-workflow generation prompt shape: top name and parsed interface delivered.

The three shipped workflows reach generation through two paths:
single_generate keeps the baseline-compatible prompt (raw public task only), while
repair_loop and design_verify_loop render agent/context/prompts/repair.j2 with the public
task, parsed interface and (for design_verify_loop) the host design plan. Neither
initial generation path may receive candidate RTL or a reference answer.
"""

from types import SimpleNamespace
import unittest

from burr.core import State

import baseline as official
from agent.config import ROOT, load_config
from agent.orchestration.nodes.baseline import generate as baseline_generate
from agent.context.prompts import TemplateRenderer
from agent.domain.rtl.task import TaskSpec

PROMPT = """Implement a module named TopModule.

Inputs:
- a: 1-bit input
- b: 1-bit input

Outputs:
- y: 1-bit output

The output y is the logical AND of a and b.
"""
INTERFACE = "module TopModule(input a, input b, output y); endmodule"
CANDIDATE_MARKER = "module TopModule_candidate_marker"
REFERENCE_ANSWER_MARKER = "reference_answer_y_equals_a_and_b"


def task():
    return TaskSpec.from_text("workflow-prompt", PROMPT, INTERFACE)


class CapturingLLM:
    def __init__(self, content="module TopModule(input a, input b, output y); assign y = a & b; endmodule"):
        self.messages = []
        self.content = content

    def chat(self, messages, **kwargs):
        self.messages = [dict(message) for message in messages]
        return SimpleNamespace(call_id="call-1", content=self.content, finish_reason="stop")


def render_repair(plan=None, parent=None, feedback=""):
    messages = TemplateRenderer().render(
        "repair.j2", task=task(), feedback=feedback, parent=parent, plan=plan
    )
    return messages[0]["content"] + "\n" + messages[1]["content"]


class WorkflowPromptTests(unittest.TestCase):
    def assert_public_interface(self, text):
        self.assertIn("Required top module name: `TopModule`. Emit this exact name.", text)
        self.assertIn('"module_name": "TopModule"', text)
        self.assertIn('"name": "a"', text)
        self.assertIn('"name": "b"', text)
        self.assertIn('"name": "y"', text)
        self.assertIn('"direction": "output"', text)
        self.assertIn('"complete": true', text)
        self.assertNotIn(CANDIDATE_MARKER, text)
        self.assertNotIn(REFERENCE_ANSWER_MARKER, text)

    def test_single_generate_keeps_the_baseline_prompt(self):
        config, _ = load_config(ROOT / "config/single_generate.yaml", {})
        # single_generate declares its own baseline_generate node, so a repair.j2
        # rewrite cannot change what this workflow sends.
        self.assertNotIn("generate", config.nodes)
        llm = CapturingLLM()
        ctx = SimpleNamespace(
            task=task(), store={}, llm=llm,
            record=SimpleNamespace(emit=lambda *args, **kwargs: None),
        )
        baseline_generate(ctx, State())
        self.assertEqual(
            llm.messages,
            [
                {"role": "system", "content": official.SYS["rtl"]},
                {"role": "user", "content": PROMPT},
            ],
        )
        combined = "\n".join(message["content"] for message in llm.messages)
        self.assertNotIn("Required top module name:", combined)
        self.assertNotIn('"module_name"', combined)
        self.assertNotIn(CANDIDATE_MARKER, combined)
        self.assertNotIn(REFERENCE_ANSWER_MARKER, combined)

    def test_repair_loop_generation_prompt_delivers_public_evidence(self):
        config, _ = load_config(ROOT / "config/repair_loop.yaml", {})
        self.assertEqual(config.nodes["generate"].use, "rtl_generate")
        text = render_repair(plan=None, parent=None)
        self.assert_public_interface(text)
        # A first-generation prompt carries no previous implementation block.
        self.assertNotIn("## Previous implementation", text)
        self.assertNotIn("## Tool feedback", text)

    def test_design_verify_loop_generation_prompt_delivers_public_evidence(self):
        config, _ = load_config(ROOT / "config/design_verify_loop.yaml", {})
        self.assertEqual(config.nodes["generate"].use, "rtl_generate")
        plan = {
            "requirements": [{"id": "R1", "quote": "The output y is the logical AND of a and b."}],
            "plan": ["Read both inputs", "AND them into y"],
            "uncertain": ["reset behavior is unspecified"],
        }
        text = render_repair(plan=plan, parent=None)
        self.assert_public_interface(text)
        self.assertNotIn("## Previous implementation", text)

    def test_classification_projection_renders_without_reasoning_fields(self):
        plan = {
            "classification": {
                "kind": "combinational",
                "clocks": [],
                "risks": ["width"],
            },
            "ambiguities": ["reset behavior is unspecified"],
        }
        text = render_repair(plan=plan, parent=None)
        self.assertIn("Task classification (host routing only; not a verified design)", text)
        self.assertIn("Classification is routing metadata, not a chosen implementation", text)
        self.assertIn('"kind": "combinational"', text)
        self.assertIn("Unresolved ambiguities (do not invent semantics)", text)
        self.assertIn("reset behavior is unspecified", text)
        # The unverified analysis reasoning and the routing policy stay host-side.
        self.assertNotIn("rationale", text)
        self.assertNotIn("model_cost", text)
        self.assert_public_interface(text)


if __name__ == "__main__":
    unittest.main()
