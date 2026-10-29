"""File-backed prompts, overridable without modifying nodes."""

from pathlib import Path
from jinja2 import Environment, FileSystemLoader, StrictUndefined


class TemplateRenderer:
    def __init__(self, paths=None):
        self.env = Environment(
            loader=FileSystemLoader(paths or [str(Path(__file__).parent)]),
            undefined=StrictUndefined,
            autoescape=False,
        )

    def render(self, name, **values):
        values.setdefault("plan", None)
        return [
            {
                "role": "system",
                "content": self.env.get_template(
                    "repair_analysis_system.j2" if name == "repair_analysis.j2" else "system.j2"
                ).render(**values).strip(),
            },
            {
                "role": "user",
                "content": self.env.get_template(name).render(**values).strip(),
            },
        ]
