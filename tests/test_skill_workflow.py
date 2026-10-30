"""Automatic skill discovery must respect workflow phases and task snapshots."""

import tempfile
import unittest
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agent.domain.knowledge.assets import load_assets
from agent.domain.rtl.task import TaskSpec
from agent.orchestration.nodes import guided
from agent.orchestration.nodes.generate import _skill_material


class SkillWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.ctx = self.context()
        self.loader = patch.object(guided, "load_assets", partial(load_assets, root=self.root))
        self.loader.start()
        self.addCleanup(self.loader.stop)

    def context(self):
        return SimpleNamespace(
            record=SimpleNamespace(
                emit=lambda *args, **kwargs: None,
                write_json=lambda *args, **kwargs: None,
                write_text=lambda *args, **kwargs: None,
            ),
            task=TaskSpec.from_text(
                "skills", "Implement module top_module(input a, output y); assign y = a; endmodule"
            ),
            store={"guided": {
                "settings": {"retrieval_mode": "off"},
                "plan": {"skills": [], "knowledge": []},
            }},
        )

    def skill(self, identity, body, metadata=""):
        path = self.root / "skill" / identity / "skill.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"---\nname: {identity}\ndescription: Public RTL method\n{metadata}---\n{body}\n",
            encoding="utf-8",
        )
        return path

    def test_snapshot_stays_bound_to_plan_until_next_task(self):
        self.skill("new-method", "Preserve the public priority order.")
        skills, _ = guided._shortlist(self.ctx, 5)
        self.assertEqual([identity for identity, _ in skills], ["new-method"])
        self.ctx.store["guided"]["plan"]["skills"] = ["new-method"]
        self.skill("new-method", "Check declared output widths.")
        material, report = guided._skill_and_card_material(self.ctx)
        self.assertIn("Preserve the public priority order.", material)
        self.assertNotIn("Check declared output widths.", material)
        self.assertEqual(report["sent"], ["new-method"])
        next_ctx = self.context()
        next_ctx.store["guided"]["plan"]["skills"] = ["new-method"]
        self.assertIn("Check declared output widths.", guided._skill_and_card_material(next_ctx)[0])

    def test_repair_only_skill_is_available_but_never_in_first_draft(self):
        self.skill("repair-only", "Recheck the failed expression width.", "phases: [repair]\n")
        self.skill("blocked", "Do not automatically inject this method.",
                   "review_status: frozen_rejected_fixed_ab\n")
        skills, _ = guided._shortlist(self.ctx, 5)
        self.assertEqual([identity for identity, _ in skills], ["repair-only"])
        self.ctx.store["guided"]["plan"]["skills"] = ["repair-only"]
        material, report = guided._skill_and_card_material(self.ctx, "generate")
        self.assertEqual(material, "")
        self.assertEqual(report["rejected"], [{"id": "repair-only", "reason": "unsupported_phase"}])
        material, report = guided._skill_and_card_material(self.ctx, "repair")
        self.assertIn("Recheck the failed expression width.", material)
        self.assertEqual(report["sent"], ["repair-only"])

    def test_automatic_generation_skips_conflicts_and_shadow_does_not_inject(self):
        for identity in ("method-a", "method-b"):
            self.skill(identity, f"Body of {identity}.", "conflict_group: alternatives\n")
        self.skill("method-c", "Independent method.")
        ctx = self.context()
        ctx.task = TaskSpec.from_text(
            "methods", "Public RTL method: implement module top_module(output y); endmodule"
        )
        ctx.store["skill_assets"] = load_assets(skills=True, root=self.root)
        events = []
        ctx.record = SimpleNamespace(emit=lambda *args, **kwargs: events.append(kwargs))
        material = _skill_material(ctx, mode="on", ids=[], phase="generate")
        self.assertIn("Body of method-a.", material)
        self.assertNotIn("Body of method-b.", material)
        self.assertIn("Independent method.", material)
        self.assertEqual(events[-1]["selected"], ["method-a", "method-c"])
        self.assertEqual(
            _skill_material(ctx, mode="shadow", ids=[], phase="generate"), ""
        )
        self.assertEqual(events[-1]["selected"], ["method-a", "method-c"])
        self.assertEqual(events[-1]["sent"], [])


if __name__ == "__main__":
    unittest.main()
