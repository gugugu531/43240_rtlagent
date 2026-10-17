"""Immutable data exchanged by skill lookup and prompt assembly."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    signatures: tuple[str, ...]
    trigger: str
    body: str
    path: str

    def __post_init__(self) -> None:
        object.__setattr__(self, 'signatures', tuple(self.signatures))


@dataclass(frozen=True)
class SkillQuery:
    prompt: str
    feedback: str
    limit: int = 2


@dataclass(frozen=True)
class SkillSelection:
    skills: tuple[Skill, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, 'skills', tuple(self.skills))
