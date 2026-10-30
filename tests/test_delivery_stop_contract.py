"""Behavioral coverage for Markdown prompt rendering and stage dispatch."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from jinja2 import UndefinedError

from agent.context.prompts import TemplateRenderer
from agent.domain.rtl.candidate import CandidateFactory
from agent.domain.rtl.task import TaskSpec


class MarkdownPromptRendering(unittest.TestCase):
    def setUp(self):
        self.renderer = TemplateRenderer()
        self.task = TaskSpec.from_text(
            "delivery-stop-contract",
            "Repair the output declaration in the buggy candidate and keep its behavior.",
            "module TopModule(input a, output [1:0] y); endmodule",
        )
        self.parent = CandidateFactory().create(
            "module TopModule(input a, output y); assign y = {2{a}}; endmodule",
            source_stage="public_synthetic",
            round=1,
        )

    def test_repair_feedback_controls_candidate_inclusion(self):
        feedback = "Public width mismatch: expected <2> bits."
        for evidence in ("", feedback):
            with self.subTest(feedback=bool(evidence)):
                messages = self.renderer.render(
                    "repair.md",
                    task=self.task,
                    parent=self.parent,
                    feedback=evidence,
                )
                self.assertEqual(
                    [message["role"] for message in messages], ["system", "user"]
                )
                user = messages[1]["content"]
                self.assertIn(self.task.prompt, user)
                self.assertIn(self.task.interface, user)
                if evidence:
                    self.assertIn(self.parent.code, user)
                    self.assertIn(feedback, user)
                else:
                    self.assertNotIn(self.parent.code, user)
                    self.assertNotIn(feedback, user)


    def test_missing_required_values_fail_instead_of_rendering_empty(self):
        with self.assertRaises(UndefinedError):
            self.renderer.render("repair.md", task=self.task, parent=self.parent)

    def test_custom_directory_controls_templates_and_stage_dispatch(self):
        with TemporaryDirectory() as directory:
            path = Path(directory)
            templates = {
                "system.md": "  delivery {{ marker }}  ",
                "repair_analysis_system.md": "  analysis {{ marker }}  ",
                "repair.md": "  {% if plan %}{{ plan }}{% else %}{{ marker }}{% endif %}  ",
                "repair_analysis.md": "  {{ marker }}  ",
                "custom.md": "  {{ marker }}  ",
            }
            for name, text in templates.items():
                (path / name).write_text(text, encoding="utf-8")
            renderer = TemplateRenderer(paths=[directory])
            for name, stage in (
                ("repair.md", "delivery"),
                ("repair_analysis.md", "analysis"),
                ("custom.md", "delivery"),
            ):
                with self.subTest(name=name):
                    self.assertEqual(
                        renderer.render(name, marker="<public & unescaped>"),
                        [
                            {
                                "role": "system",
                                "content": f"{stage} <public & unescaped>",
                            },
                            {"role": "user", "content": "<public & unescaped>"},
                        ],
                    )
            self.assertEqual(
                renderer.render("repair.md", marker="task", plan="explicit plan")[1],
                {"role": "user", "content": "explicit plan"},
            )


if __name__ == "__main__":
    unittest.main()
