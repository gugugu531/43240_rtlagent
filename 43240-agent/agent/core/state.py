"""Immutable check evidence, run views and explicit workflow results."""
from __future__ import annotations
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal, Any
from agent.core.candidate import Candidate
from agent.core.model import _freeze, _thaw

CheckStatus = Literal['passed', 'failed', 'timeout', 'unavailable', 'error', 'skipped']


@dataclass(frozen=True)
class CheckResult:
    id: str
    candidate_id: str
    kind: str
    status: CheckStatus
    summary: str
    blocking: bool = False
    rc: int = 0
    elapsed_s: float = 0.0
    command: tuple[tuple[str, ...], ...] = ()
    details: Mapping[str, Any] = field(default_factory=dict)
    full_log_path: str | None = None
    work_dir: str | None = None

    def __post_init__(self):
        if self.status not in ('passed', 'failed', 'timeout', 'unavailable', 'error', 'skipped'):
            raise ValueError('unknown check status')
        object.__setattr__(self, 'details', _freeze(self.details))
        object.__setattr__(self, 'command', tuple(tuple(c) for c in self.command))

    def public_dict(self):
        return dict(check_id=self.id, candidate_id=self.candidate_id, kind=self.kind,
                    status=self.status, blocking=self.blocking, rc=self.rc,
                    elapsed_s=self.elapsed_s, command=[list(c) for c in self.command],
                    excerpt=self.summary[:2000], details=_thaw(self.details),
                    full_log_path=self.full_log_path, work_dir=self.work_dir)


@dataclass(frozen=True)
class NodeExecution:
    id: str
    parent_id: str | None
    component: Mapping[str, Any]
    status: str
    elapsed_s: float
    input: Any
    output: Any = None
    error_type: str | None = None
    error_message: str | None = None

    def __post_init__(self):
        for name in ('component', 'input', 'output'):
            object.__setattr__(self, name, _freeze(getattr(self, name)))


@dataclass(frozen=True)
class RunStateView:
    candidates: Mapping[str, Candidate]
    checks: tuple[CheckResult, ...]
    executions: tuple[NodeExecution, ...]
    selected_candidate_id: str | None
    stop_reason: str | None


@dataclass(frozen=True)
class WorkflowResult:
    run_id: str
    selected_candidate: Candidate | None
    stop_reason: str
    status: Literal['completed', 'stopped', 'error'] = 'completed'
