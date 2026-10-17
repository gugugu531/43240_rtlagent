"""Render already selected skills within the prompt budget."""
from __future__ import annotations

import re

from agent.core.skill import Skill


def render(skill: Skill, budget: int = 12000) -> str:
    return f'<skill name="{skill.name}">\n{_trim(skill.body, budget)}\n</skill>'


def _trim(body: str, budget: int) -> str:
    """Drop whole trailing sections and name those omitted."""
    if len(body) <= budget:
        return body
    sections = re.split(r"(?=^## )", body, flags=re.MULTILINE)
    kept: list[str] = []
    used = 0
    for section in sections:
        if used + len(section) > budget and kept:
            break
        kept.append(section)
        used += len(section)
    dropped = [section.splitlines()[0].lstrip("# ").strip()
               for section in sections[len(kept):] if section.strip()]
    note = f"\n\n... [skill truncated, sections omitted: {', '.join(dropped)}]"
    return "".join(kept).rstrip() + note
