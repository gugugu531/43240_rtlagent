"""Per-call token evidence and optional conservative cumulative limits."""
from __future__ import annotations

from dataclasses import asdict, dataclass

from agent.core.model import ModelCallError, ModelUsage


def positive_integer(value, name, *, optional=False):
    if value is None and optional:
        return
    if type(value) is not int or value <= 0:
        raise ValueError(f'{name} must be a positive integer')


@dataclass(frozen=True)
class TokenCount:
    value: int | None = None
    status: str = 'unavailable'
    tokenizer_sha256: str | None = None
    template_sha256: str | None = None
    reason: str | None = None

    def __post_init__(self):
        if self.status not in ('exact', 'unavailable', 'mismatch'):
            raise ValueError('invalid token count status')
        if self.value is not None and (type(self.value) is not int or self.value < 0):
            raise ValueError('invalid token count')
        if self.status == 'exact' and self.value is None:
            raise ValueError('exact count requires a value')

    def public_dict(self):
        return asdict(self)


class UnavailableCounter:
    def count(self, messages, *, template_options=None):
        return TokenCount(reason='tokenizer_not_configured')


@dataclass(frozen=True)
class TokenPolicy:
    total_limit: int | None = None
    output_limit: int | None = None

    def __post_init__(self):
        positive_integer(self.total_limit, 'total_limit', optional=True)
        positive_integer(self.output_limit, 'output_limit', optional=True)

    @property
    def strict(self):
        return self.total_limit is not None or self.output_limit is not None


class TokenBudgetError(ModelCallError):
    def __init__(self, reason):
        super().__init__(reason, kind='token_budget')


class TokenLedger:
    """A missing response retains its reservation; it never becomes zero usage.

    Limits apply to client model requests. Actual service computation after a
    failed request cannot be inferred or bounded by this ledger.
    """

    def __init__(self, policy=None):
        self.policy = policy or TokenPolicy()
        self._calls = {}
        self._blocked = False

    def allowance(self, predicted_input: TokenCount, output_cap: int) -> int:
        positive_integer(output_cap, 'output_cap')
        if self._blocked and self.policy.strict:
            raise TokenBudgetError('token_accounting_mismatch')
        cap = output_cap
        if self.policy.output_limit is not None:
            cap = min(cap, self.policy.output_limit - sum(c['charged_output'] for c in self._calls.values()))
        if self.policy.total_limit is not None:
            if predicted_input.status != 'exact':
                raise TokenBudgetError('input_tokens_unknown')
            cap = min(cap, self.policy.total_limit - sum(c['charged_total'] for c in self._calls.values())
                      - predicted_input.value)
        if cap <= 0:
            raise TokenBudgetError('token_budget_exhausted')
        return cap

    def start(self, call_id, *, predicted_input: TokenCount, output_cap: int):
        if call_id in self._calls:
            raise ValueError('duplicate token call')
        positive_integer(output_cap, 'output_cap')
        known_input = predicted_input.value if predicted_input.status == 'exact' else None
        self._calls[call_id] = dict(status='started', prediction=predicted_input.public_dict(),
            output_cap=output_cap, tokens_in=None, tokens_out=None,
            charged_output=output_cap, charged_total=(known_input or 0) + output_cap,
            input_reservation_known=known_input is not None)

    def finish(self, call_id, *, usage=None, outcome):
        entry = self._calls[call_id]
        if entry['status'] != 'started':
            raise ValueError('token call already finished')
        if outcome not in ('succeeded', 'failed'):
            raise ValueError('invalid token outcome')
        usage = usage or ModelUsage()
        for key, value in (('tokens_in', usage.tokens_in), ('tokens_out', usage.tokens_out)):
            entry[key] = value if type(value) is int and value >= 0 else None
        entry['status'] = outcome
        predicted = entry['prediction']['value'] if entry['input_reservation_known'] else None
        actual_in, actual_out = entry['tokens_in'], entry['tokens_out']
        entry['charged_output'] = actual_out if actual_out is not None else entry['output_cap']
        entry['charged_total'] = (actual_in if actual_in is not None else predicted or 0) + entry['charged_output']
        mismatch = (predicted is not None and actual_in is not None and predicted != actual_in)
        entry['prediction_matches_usage'] = None if predicted is None or actual_in is None else not mismatch
        self._blocked |= mismatch or (actual_out is not None and actual_out > entry['output_cap'])

    def snapshot(self):
        calls = list(self._calls.values())
        result = dict(total_limit=self.policy.total_limit, output_limit=self.policy.output_limit,
                      mode='strict' if self.policy.strict else 'observe', blocked=self._blocked,
                      calls=len(calls), unfinished=sum(c['status'] == 'started' for c in calls),
                      charged_output=sum(c['charged_output'] for c in calls),
                      charged_total=sum(c['charged_total'] for c in calls)
                        if all(c['input_reservation_known'] or c['tokens_in'] is not None for c in calls) else None)
        for field in ('tokens_in', 'tokens_out'):
            values = [c[field] for c in calls if c[field] is not None]
            result[field] = dict(known_total=sum(values) if values else None,
                                 known_calls=len(values), unknown_calls=len(calls) - len(values))
        result['entries'] = {key: dict(value) for key, value in self._calls.items()}
        return result
