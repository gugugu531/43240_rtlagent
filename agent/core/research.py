"""Immutable inputs and outputs shared by optional research workflows."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from agent.core.candidate import Candidate
from agent.core.model import _freeze
from agent.core.task import TaskSpec


INVALID_JSON_TEXT_LIMIT = 8192


@dataclass(frozen=True)
class JsonInput:
    task: TaskSpec
    instruction: str
    purpose: str
    context: Mapping[str, Any] = field(default_factory=dict)
    max_tokens: int | None = None
    seed: int | None = None

    def __post_init__(self):
        if not self.instruction.strip() or not self.purpose.strip():
            raise ValueError('structured request needs an instruction and purpose')
        if self.max_tokens is not None and (type(self.max_tokens) is not int or self.max_tokens <= 0):
            raise ValueError('max_tokens must be a positive integer')
        object.__setattr__(self, 'context', _freeze(dict(self.context)))


@dataclass(frozen=True)
class JsonOutput:
    status: Literal['ready', 'invalid']
    data: Mapping[str, Any] = field(default_factory=dict)
    call_id: str | None = None
    reason: str = ''
    # Unparsed content is evidence for correction, never an adopted JSON object.
    raw_text: str | None = None
    raw_text_metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.status not in ('ready', 'invalid'):
            raise ValueError('unknown structured reply status')
        if self.raw_text is not None and (self.status != 'invalid' or
                not isinstance(self.raw_text, str) or len(self.raw_text) > INVALID_JSON_TEXT_LIMIT):
            raise ValueError('raw structured reply must be bounded invalid content')
        object.__setattr__(self, 'data', _freeze(dict(self.data)))
        object.__setattr__(self, 'raw_text_metadata', _freeze(dict(self.raw_text_metadata)))


@dataclass(frozen=True)
class SuiteInput:
    """Checker construction receives the task, never an RTL candidate."""
    task: TaskSpec
    mode: Literal['behavior', 'stimulus'] = 'behavior'
    feedback: str = ''
    previous: Mapping[str, Any] | None = None

    def __post_init__(self):
        if self.mode not in ('behavior', 'stimulus'):
            raise ValueError('unknown simulation suite mode')
        if self.previous is not None:
            object.__setattr__(self, 'previous', _freeze(dict(self.previous)))


@dataclass(frozen=True)
class SuiteBuild:
    status: Literal['ready', 'invalid', 'unsupported']
    suite: Mapping[str, Any] | None = None
    call_id: str | None = None
    reason: str = ''

    def __post_init__(self):
        if self.status not in ('ready', 'invalid', 'unsupported'):
            raise ValueError('unknown suite construction status')
        if self.status == 'ready' and self.suite is None:
            raise ValueError('ready suite requires a specification')
        if self.suite is not None:
            object.__setattr__(self, 'suite', _freeze(dict(self.suite)))


@dataclass(frozen=True)
class FunctionalInput:
    candidate: Candidate
    suite: Mapping[str, Any]
    compare_expected: bool = True

    def __post_init__(self):
        if type(self.compare_expected) is not bool:
            raise ValueError('compare_expected must be boolean')
        object.__setattr__(self, 'suite', _freeze(dict(self.suite)))
