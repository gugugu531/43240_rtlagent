"""Replaceable bounded retry/repair decisions, owned by the workflow."""
from dataclasses import dataclass
import math
from .diagnostics import Diagnostic
from ..core.components import Component


@dataclass(frozen=True)
class AttemptState:
    model_calls: int = 0
    request_retries: int = 0
    repairs: int = 0


@dataclass(frozen=True)
class FailureDecision:
    action: str
    reason: str
    diagnostic_ids: tuple[str, ...]


class FailurePolicy(Component):
    def __init__(self, max_request_retries=1, max_model_calls=4, max_repairs=2,
                 minimum_action_s=0.05):
        for value in (max_request_retries, max_model_calls, max_repairs):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError('attempt limits must be nonnegative integers')
        if max_model_calls < 1:
            raise ValueError('max_model_calls must be positive')
        if not math.isfinite(minimum_action_s) or minimum_action_s < 0:
            raise ValueError('minimum_action_s must be nonnegative')
        self.max_request_retries = max_request_retries
        self.max_model_calls = max_model_calls
        self.max_repairs = max_repairs
        self.minimum_action_s = minimum_action_s

    def decide(self, diagnostics: tuple[Diagnostic, ...], attempts: AttemptState, budget) -> FailureDecision:
        ids = tuple(d.source_id for d in diagnostics)
        if not budget.can_start(self.minimum_action_s):
            return FailureDecision('stop', 'deadline', ids)
        if attempts.model_calls >= self.max_model_calls:
            return FailureDecision('stop', 'model_call_limit', ids)
        kinds = {d.kind for d in diagnostics}
        if kinds == {'model_retryable'} and attempts.request_retries < self.max_request_retries:
            return FailureDecision('retry_request', 'retryable_model_error', ids)
        if kinds <= {'code', 'extraction'} and attempts.repairs < self.max_repairs:
            return FailureDecision('repair', 'code_feedback', ids)
        return FailureDecision('stop', next(iter(sorted(kinds)), 'unknown'), ids)
