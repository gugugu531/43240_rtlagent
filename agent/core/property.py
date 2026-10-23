"""Versioned, source-grounded inputs for finite property simulation."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from agent.core.candidate import Candidate
from agent.core.model import _freeze
from agent.core.task import TaskSpec


@dataclass(frozen=True)
class PropertyBuildInput:
    task: TaskSpec
    feedback: str = ''
    previous: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class PropertyBuild:
    status: Literal['ready', 'invalid', 'unsupported']
    suite: Mapping[str, Any] | None = None
    call_id: str | None = None
    reason: str = ''

    def __post_init__(self):
        if self.status not in ('ready', 'invalid', 'unsupported'):
            raise ValueError('unknown property construction status')
        if self.status == 'ready' and self.suite is None:
            raise ValueError('ready property construction needs a suite')
        if self.suite is not None:
            object.__setattr__(self, 'suite', _freeze(dict(self.suite)))


@dataclass(frozen=True)
class PropertyCheckInput:
    candidate: Candidate
    suite: Mapping[str, Any]

    def __post_init__(self):
        object.__setattr__(self, 'suite', _freeze(dict(self.suite)))


@dataclass(frozen=True)
class PropertyReviewInput:
    task: TaskSpec
    suite: Mapping[str, Any]


@dataclass(frozen=True)
class PropertyReview:
    approved_ids: tuple[str, ...] = ()
    issues: tuple[str, ...] = ()
    call_id: str | None = None
