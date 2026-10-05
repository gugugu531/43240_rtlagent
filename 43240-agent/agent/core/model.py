"""Contracts shared by model transports, recording and workflows."""
from __future__ import annotations
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol
from types import MappingProxyType
import math


def _freeze(value):
    if isinstance(value, Mapping):
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(v) for v in value)
    return value


def _thaw(value):
    if isinstance(value, Mapping):
        return {k: _thaw(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw(v) for v in value]
    return value


@dataclass(frozen=True)
class ModelRequest:
    messages: Sequence[Mapping[str, Any]]
    max_tokens: int = 4096
    temperature: float = 0.2
    timeout_s: float = 180.0
    purpose: str = 'generate'

    def __post_init__(self):
        if isinstance(self.max_tokens, bool) or not isinstance(self.max_tokens, int) or self.max_tokens <= 0:
            raise ModelCallError('max_tokens must be a positive integer', kind='config')
        if not math.isfinite(self.temperature) or self.temperature < 0:
            raise ModelCallError('temperature must be finite and nonnegative', kind='config')
        if not math.isfinite(self.timeout_s) or self.timeout_s <= 0:
            raise ModelCallError('timeout_s must be positive and finite', kind='config')
        # Detach from caller-owned containers. No recorder may mutate this copy.
        object.__setattr__(self, 'messages', tuple(_freeze(dict(m)) for m in self.messages))

    def public_dict(self):
        return dict(messages=_thaw(self.messages), max_tokens=self.max_tokens,
                    temperature=self.temperature, timeout_s=self.timeout_s, purpose=self.purpose)


@dataclass(frozen=True)
class ArtifactRef:
    run_id: str
    path: str

    def public_dict(self):
        return dict(run_id=self.run_id, path=self.path)


@dataclass(frozen=True)
class ModelUsage:
    tokens_in: int | None = None
    tokens_out: int | None = None


@dataclass(frozen=True)
class ModelReply:
    call_id: str
    content: str
    model: str | None = None
    request_id: str | None = None
    finish_reason: str | None = None
    usage: ModelUsage = field(default_factory=ModelUsage)
    elapsed_s: float = 0.0
    response_artifact: ArtifactRef | None = None

    def public_dict(self):
        return dict(call_id=self.call_id, model=self.model, request_id=self.request_id,
                    finish_reason=self.finish_reason, tokens_in=self.usage.tokens_in,
                    tokens_out=self.usage.tokens_out, elapsed_s=self.elapsed_s,
                    empty_content=not self.content,
                    response_artifact=self.response_artifact.public_dict() if self.response_artifact else None)


class ModelCallError(RuntimeError):
    def __init__(self, message: str, *, call_id: str = '', kind: str,
                 retryable: bool = False, status_code: int | None = None,
                 elapsed_s: float = 0.0, evidence: ArtifactRef | None = None):
        super().__init__(message)
        self.call_id, self.kind, self.retryable = call_id, kind, retryable
        self.status_code, self.elapsed_s, self.evidence = status_code, elapsed_s, evidence

    def public_dict(self):
        return dict(call_id=self.call_id, kind=self.kind, retryable=self.retryable,
                    status_code=self.status_code, elapsed_s=self.elapsed_s,
                    message=str(self), evidence=self.evidence.public_dict() if self.evidence else None)


@dataclass(frozen=True)
class BackendResponse:
    elapsed_s: float
    status_code: int | None = None
    raw_text: str | None = None
    # Mock has a content value, not a fabricated HTTP response.
    mock_content: str | None = None


class ModelBackend(Protocol):
    def describe(self) -> Mapping[str, Any]: ...
    def complete(self, request: ModelRequest) -> BackendResponse: ...
