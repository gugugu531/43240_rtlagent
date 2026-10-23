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
    model: str | None = None
    top_p: float | None = None
    stream: bool | None = False
    profile: str = 'default'
    chat_template_kwargs: Mapping[str, Any] | None = None
    seed: int | None = None
    reasoning_effort: str | None = None

    def __post_init__(self):
        if isinstance(self.max_tokens, bool) or not isinstance(self.max_tokens, int) or self.max_tokens <= 0:
            raise ModelCallError('max_tokens must be a positive integer', kind='config')
        if not math.isfinite(self.temperature) or self.temperature < 0:
            raise ModelCallError('temperature must be finite and nonnegative', kind='config')
        if not math.isfinite(self.timeout_s) or self.timeout_s <= 0:
            raise ModelCallError('timeout_s must be positive and finite', kind='config')
        if self.top_p is not None and (isinstance(self.top_p, bool) or
                not isinstance(self.top_p, (int, float)) or not math.isfinite(self.top_p) or
                not 0 < self.top_p <= 1):
            raise ModelCallError('top_p must be in (0, 1]', kind='config')
        if self.model is not None and (not isinstance(self.model, str) or not self.model):
            raise ModelCallError('model must be a nonempty string', kind='config')
        if self.stream is not None and type(self.stream) is not bool:
            raise ModelCallError('stream must be boolean or null', kind='config')
        if self.profile not in ('default', 'baseline_rtl'):
            raise ModelCallError('unknown request profile', kind='config')
        if self.seed is not None and (type(self.seed) is not int or not 0 <= self.seed < 2**32
                                      or self.profile == 'baseline_rtl'):
            raise ModelCallError('seed requires a default profile and unsigned 32-bit integer', kind='config')
        if self.reasoning_effort is not None and (not isinstance(self.reasoning_effort, str) or not self.reasoning_effort):
            raise ModelCallError('reasoning_effort must be a nonempty string', kind='config')
        if self.chat_template_kwargs is not None:
            if (not isinstance(self.chat_template_kwargs, Mapping)
                    or any(not isinstance(k, str) or not isinstance(v, (bool, int, float, str))
                           for k, v in self.chat_template_kwargs.items())):
                raise ModelCallError('unsupported chat template options', kind='config')
            object.__setattr__(self, 'chat_template_kwargs', _freeze(dict(self.chat_template_kwargs)))
        # Detach from caller-owned containers. No recorder may mutate this copy.
        object.__setattr__(self, 'messages', tuple(_freeze(dict(m)) for m in self.messages))

    def public_dict(self):
        result = dict(messages=_thaw(self.messages), max_tokens=self.max_tokens,
                    temperature=self.temperature, timeout_s=self.timeout_s, purpose=self.purpose,
                    model=self.model, top_p=self.top_p, stream=self.stream, profile=self.profile,
                    chat_template_kwargs=_thaw(self.chat_template_kwargs))
        if self.reasoning_effort is not None:
            result['reasoning_effort'] = self.reasoning_effort
        if self.seed is not None:
            result['seed'] = self.seed
        return result

    def payload(self, default_model: str):
        body = dict(model=self.model if self.model is not None else default_model,
                    messages=_thaw(self.messages), max_tokens=self.max_tokens,
                    temperature=self.temperature)
        if self.top_p is not None:
            body['top_p'] = self.top_p
        if self.stream is not None:
            body['stream'] = self.stream
        if self.chat_template_kwargs is not None:
            body['chat_template_kwargs'] = _thaw(self.chat_template_kwargs)
        if self.reasoning_effort is not None:
            body['reasoning_effort'] = self.reasoning_effort
        if self.seed is not None:
            body['seed'] = self.seed
        return body


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
class ModelReasoning:
    """Optional provider text, kept separate from final content and token usage.

    An absent key, explicit null and empty string retain distinct meanings.
    Malformed or conflicting aliases remain explicit evidence states.
    Raw malformed values remain in the recorded response, not this interface.
    """
    fields: Mapping[str, str | None] = field(default_factory=dict)
    invalid_fields: tuple[str, ...] = ()

    def __post_init__(self):
        names = {'reasoning', 'reasoning_content'}
        values = dict(self.fields)
        invalid = tuple(self.invalid_fields)
        if (set(values) - names or set(invalid) - names or set(values) & set(invalid)
                or len(set(invalid)) != len(invalid)
                or any(value is not None and not isinstance(value, str) for value in values.values())):
            raise ValueError('invalid reasoning evidence')
        object.__setattr__(self, 'fields', MappingProxyType(values))
        object.__setattr__(self, 'invalid_fields', invalid)

    @property
    def status(self):
        if self.invalid_fields:
            return 'invalid'
        values = set(self.fields.values())
        if len(values) > 1:
            return 'conflict'
        if not values:
            return 'absent'
        value = next(iter(values))
        return 'null' if value is None else 'available' if value else 'empty'

    @property
    def text(self):
        if self.status not in ('available', 'empty'):
            return None
        return next(value for value in self.fields.values() if isinstance(value, str))

    def public_dict(self):
        fields = {}
        for name in ('reasoning', 'reasoning_content'):
            if name in self.invalid_fields:
                fields[name] = dict(status='invalid')
            elif name not in self.fields:
                fields[name] = dict(status='absent')
            else:
                value = self.fields[name]
                fields[name] = (dict(status='null') if value is None else
                                dict(status='text' if value else 'empty', characters=len(value)))
        # Trace contains states and sizes only. Full text stays in response evidence.
        return dict(status=self.status, fields=fields)


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
    reasoning: ModelReasoning = field(default_factory=ModelReasoning)

    def public_dict(self):
        return dict(call_id=self.call_id, model=self.model, request_id=self.request_id,
                    finish_reason=self.finish_reason, tokens_in=self.usage.tokens_in,
                    tokens_out=self.usage.tokens_out, elapsed_s=self.elapsed_s,
                    empty_content=not self.content,
                    reasoning=self.reasoning.public_dict(),
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
