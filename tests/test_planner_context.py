"""Planner sees public semantics and host limits without sharing stage history."""

import json
import unittest
from types import SimpleNamespace

from agent.domain.rtl.guided_plan import PlanError, parse_plan, plan_request
from agent.domain.rtl.task import TaskSpec


COMB_INTERFACE = "module TopModule(input [1:0] a, input [1:0] b, output [1:0] y);"
CLOCK_INTERFACE = "module TopModule(input clk, input reset_n, input d, output q);"


class PlannerContextTests(unittest.TestCase):
    def request(self, prompt, interface=COMB_INTERFACE, **kwargs):
        return plan_request(
            TaskSpec.from_text("self-authored", prompt, interface),
            [("rtl-method", "A public method")],
            [{"card_id": "method-card", "title": "Public explanation"}],
            **kwargs,
        )

    def test_same_interface_different_semantics_remain_distinguishable(self):
        arithmetic = "Compute y as the low two bits of a + b.\nDo not retain state."
        kmap = "Use a Karnaugh map with coordinates a,b to define y from the stated minterms."
        rules = {"supported": True, "reason": "combinational"}
        left = self.request(arithmetic, checker_rules=rules)
        right = self.request(kmap, checker_rules=rules)
        self.assertNotEqual(left, right)
        self.assertIn(arithmetic, left[1]["content"])
        self.assertIn(kmap, right[1]["content"])
        self.assertNotIn(kmap, left[1]["content"])

    def test_clock_edge_wording_is_preserved(self):
        rising = "On each positive edge of clk, q takes d unless reset_n is low."
        falling = "On each negative edge of clk, q takes d unless reset_n is low."
        up = self.request(rising, CLOCK_INTERFACE)
        down = self.request(falling, CLOCK_INTERFACE)
        self.assertNotEqual(up, down)
        self.assertIn(rising, up[1]["content"])
        self.assertIn(falling, down[1]["content"])
        self.assertIn('"supported":false', down[1]["content"])

    def test_complete_public_text_and_parsed_interface_are_visible(self):
        prompt = "公开题面：\n  Preserve spacing, polarity and signed meaning.\nEnd.\n"
        task = TaskSpec.from_text("self-authored", prompt, COMB_INTERFACE)
        messages = plan_request(task, [], [], checker_rules={"supported": True})
        self.assertEqual([message["role"] for message in messages], ["system", "user"])
        body = messages[1]["content"]
        self.assertIn(prompt, body)
        self.assertIn(COMB_INTERFACE, body)
        self.assertIn(json.dumps(task.expected_interface.public_dict(), ensure_ascii=False,
                                 separators=(",", ":")), body)

    def test_configured_selection_and_text_limits_are_explicit(self):
        messages = self.request(
            "Compute y = a + b.", checker_rules={"supported": False, "reason": "unsupported"},
            max_skills=1, max_cards=0, max_focus=2,
        )
        system, user = [message["content"] for message in messages]
        self.assertIn("at most 1 skills, 0 knowledge cards, and 2 focus phrases", system)
        self.assertIn("80 characters", system)
        self.assertIn("500 characters", system)
        self.assertIn("If supported is false, choose structural", system)
        self.assertIn("method=<structural or table>", user)
        self.assertNotIn("method=table\n", user)
        self.assertIn('"supported":false', user)

    def test_request_does_not_copy_unrelated_stage_state(self):
        task = TaskSpec.from_text("self-authored", "Compute y = a + b.", COMB_INTERFACE)
        task_with_history = SimpleNamespace(**vars(task), candidate="CANDIDATE_SECRET",
                                            observations="MEASURED_SECRET", history="HISTORY_SECRET")
        messages = plan_request(task_with_history, [], [], checker_rules={"supported": True})
        serialized = json.dumps(messages)
        for marker in ("CANDIDATE_SECRET", "MEASURED_SECRET", "HISTORY_SECRET"):
            self.assertNotIn(marker, serialized)

    def test_strict_plan_text_bounds_still_reject_invalid_output(self):
        for tail in ("focus=" + "x" * 81, "reason=" + "x" * 501,
                     "focus=a|b|c"):
            with self.subTest(tail=tail), self.assertRaises(PlanError):
                parse_plan("method=table\n" + tail, skill_ids=[], card_ids=[], max_focus=2)


if __name__ == "__main__":
    unittest.main()
