"""Managed, injectable lookup of locally installed skills."""
from __future__ import annotations

from pathlib import Path

from agent.core.components import Tool
from agent.core.skill import SkillQuery, SkillSelection
from agent.services.skills import load_skills, select


class SkillLookupTool(Tool[SkillQuery, SkillSelection]):
    component_name = 'skill_lookup'
    input_type = SkillQuery
    output_type = SkillSelection
    assembly_roles = ['skill_tool']
    assembly_defaults = {'params': {'skill_dir': None}, 'dependencies': {}}

    def __init__(self, skill_dir: str | Path | None = None) -> None:
        if skill_dir is not None and (not isinstance(skill_dir, (str, Path)) or not str(skill_dir)):
            raise ValueError('skill_dir must be a nonempty path or None')
        self.skill_dir = str(skill_dir) if skill_dir is not None else None

    def run(self, ctx, input: SkillQuery) -> SkillSelection:
        skill_dir = self.skill_dir
        if skill_dir is None:
            skill_dir = str(Path(__file__).resolve().parents[2] / 'skill')
        return SkillSelection(tuple(select(load_skills(skill_dir), input.prompt,
                                           input.feedback, limit=input.limit)))
