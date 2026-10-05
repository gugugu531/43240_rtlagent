"""Conservative attribution: a nonzero exit alone is not an RTL defect."""
from dataclasses import dataclass
from typing import Literal
from agent.core.model import ModelCallError
from agent.core.state import CheckResult


@dataclass(frozen=True)
class Diagnostic:
    kind: str
    message: str
    confidence: Literal['confirmed', 'unknown']
    source_id: str
    code: str | None = None


def classify_model_error(error: ModelCallError) -> Diagnostic:
    retryable = error.retryable and error.kind in ('transport', 'connection', 'timeout', 'http')
    return Diagnostic('model_retryable' if retryable else 'model_terminal', str(error),
                      'confirmed', error.call_id or '', error.kind)


def classify_check(result: CheckResult) -> tuple[Diagnostic, ...]:
    cause = result.details.get('failure_kind')
    if result.status == 'passed':
        kind, confidence = 'passed', 'confirmed'
    elif result.kind == 'interface' and result.status == 'failed' and result.blocking:
        kind, confidence = 'code', 'confirmed'
    elif result.status == 'timeout':
        kind, confidence = 'timeout', 'unknown'
    elif result.status in ('unavailable', 'error') or cause == 'environment':
        kind, confidence = 'environment', 'confirmed'
    elif result.status == 'failed' and cause == 'code':
        kind, confidence = 'code', 'confirmed'
    else:
        kind, confidence = 'unknown', 'unknown'
    return (Diagnostic(kind, result.summary, confidence, result.id),)
