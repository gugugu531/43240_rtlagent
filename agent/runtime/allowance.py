"""Opt-in, serial completion allowances; metadata requests never consume a call."""

from dataclasses import dataclass, field
import math
import time


class AllowanceError(RuntimeError):
    """A completion would exceed or reuse an explicitly granted allowance."""


@dataclass(eq=False)
class CompletionPermit:
    id: str
    stage: str
    max_tokens: int
    timeout_s: float
    followup_s: float
    optional: bool
    deadline: float
    _ledger: object = field(repr=False)
    state: str = "reserved"
    call_id: str | None = None
    sent_max_tokens: int | None = None
    response_received: bool = False
    terminal_confirmed: bool = False
    tokens_in: int | None = None
    tokens_out: int | None = None

    def remaining_s(self):
        return max(0.0, min(
            self.deadline - time.monotonic(),
            self._ledger.budget.remaining() - self.followup_s,
        ))

    def _begin(self):
        if self not in self._ledger._permits or self.state != "reserved":
            raise AllowanceError("completion permit has already been entered")
        self.state = "active"
        self._ledger._emit("entered", self)

    def _check_send(self, max_tokens):
        if self not in self._ledger._permits or self.state != "active" or self.call_id is not None:
            raise AllowanceError("one permit allows exactly one completion request")
        if type(max_tokens) is not int or not 0 < max_tokens <= self.max_tokens:
            raise AllowanceError("completion output exceeds its permit")
        if self.remaining_s() <= 0:
            raise AllowanceError("completion permit deadline has expired")

    def _sent(self, call_id, max_tokens):
        self._check_send(max_tokens)
        self.call_id, self.sent_max_tokens = call_id, max_tokens
        self._ledger._emit("sent", self)

    def _response(self, body=None):
        self.response_received = True
        usage = body.get("usage") if isinstance(body, dict) else None
        if isinstance(usage, dict):
            self.tokens_in = _count(usage.get("prompt_tokens"))
            self.tokens_out = _count(usage.get("completion_tokens"))

    def _finish(self):
        if self.state not in ("reserved", "active"):
            return
        self.state = "settled" if self.call_id is not None else "released"
        self._ledger._emit(self.state, self)

    def release(self):
        """Release a reservation that the caller decided not to enter."""
        if self.state != "reserved":
            raise AllowanceError("only an unentered reservation can be released")
        self._finish()

    def public_dict(self):
        return {name: getattr(self, name) for name in (
            "id", "stage", "max_tokens", "timeout_s", "followup_s", "optional",
            "deadline", "state", "call_id", "sent_max_tokens", "response_received",
            "terminal_confirmed", "tokens_in", "tokens_out",
        )}


def _count(value):
    return value if type(value) is int and value >= 0 else None


class CompletionLedger:
    """Reserve worst-case costs before preparation, settle only observed usage."""

    def __init__(self, budget, record, max_calls=5, max_output_tokens=110592):
        if any(type(value) is not int or value <= 0 for value in (max_calls, max_output_tokens)):
            raise ValueError("completion limits must be positive integers")
        self.budget, self.record = budget, record
        self.max_calls, self.max_output_tokens = max_calls, max_output_tokens
        self._permits = []
        self.last_denial = None

    def _emit(self, event, permit=None, **fields):
        self.record.emit(
            "completion_allowance", event,
            **({"permit": permit.public_dict()} if permit is not None else {}),
            **fields,
        )

    def snapshot(self):
        reserved = [p for p in self._permits if p.call_id is None and p.state in ("reserved", "active")]
        sent = [p for p in self._permits if p.call_id is not None]
        unknown_output = sum(p.tokens_out is None for p in sent)
        unknown_usage = sum(p.tokens_in is None or p.tokens_out is None for p in sent)
        unconfirmed = sum(not (p.response_received or p.terminal_confirmed) for p in sent)
        known_output = sum(p.tokens_out for p in sent if p.tokens_out is not None)
        charged = sum(p.max_tokens for p in reserved) + sum(
            p.max_tokens if p.tokens_out is None else p.tokens_out for p in sent
        )
        return {
            "max_calls": self.max_calls, "max_output_tokens": self.max_output_tokens,
            "calls_sent": len(sent), "calls_reserved": len(reserved),
            "calls_remaining": max(0, self.max_calls - len(sent) - len(reserved)),
            "known_output_tokens": known_output,
            "output_tokens_charged": charged,
            "output_tokens_remaining": max(0, self.max_output_tokens - charged),
            "unknown_output_calls": unknown_output, "unknown_usage_calls": unknown_usage,
            "unconfirmed_calls": unconfirmed,
            "optional_blocked": bool(unknown_usage or unconfirmed),
            "permits": [p.public_dict() for p in self._permits],
        }

    def reserve(self, stage, max_tokens, timeout_s, followup_s=0, optional=True,
                min_timeout_s=None):
        if not isinstance(stage, str) or not stage.strip():
            raise ValueError("completion stage must be a nonempty name")
        if type(max_tokens) is not int or max_tokens <= 0 or type(optional) is not bool:
            raise ValueError("invalid completion token limit or optional flag")
        if any(not math.isfinite(value) for value in (timeout_s, followup_s)) or timeout_s <= 0 or followup_s < 0:
            raise ValueError("completion time limits must be finite and nonnegative")
        if min_timeout_s is not None and (
            not math.isfinite(min_timeout_s) or not 0 < min_timeout_s <= timeout_s
        ):
            raise ValueError("minimum completion time must be positive and within the stage limit")
        requested_timeout_s = timeout_s
        remaining_s = self.budget.remaining()
        if min_timeout_s is not None:
            # Shrink only the model's allowance. Never borrow the tool/followup
            # reserve or admit an unusably short request to make progress appear.
            timeout_s = min(timeout_s, max(0.0, remaining_s - followup_s))
        snapshot = self.snapshot()
        reason = (
            "unfinished_permit" if any(p.state in ("reserved", "active") for p in self._permits)
            else "unconfirmed_completion" if snapshot["unconfirmed_calls"]
            else "unknown_usage" if optional and snapshot["unknown_usage_calls"]
            else "call_limit" if not snapshot["calls_remaining"]
            else "output_token_limit" if max_tokens > snapshot["output_tokens_remaining"]
            else "insufficient_followup_time" if (
                (min_timeout_s is None and timeout_s + followup_s > remaining_s)
                or (min_timeout_s is not None and timeout_s < min_timeout_s)
            )
            else None
        )
        self.last_denial = reason
        if reason:
            self._emit("denied", stage=stage, reason=reason, max_tokens=max_tokens,
                       timeout_s=timeout_s, requested_timeout_s=requested_timeout_s,
                       min_timeout_s=min_timeout_s, followup_s=followup_s, optional=optional)
            return None
        permit = CompletionPermit(
            f"a{len(self._permits) + 1:04d}", stage, max_tokens, timeout_s,
            followup_s, optional, time.monotonic() + timeout_s, self,
        )
        self._permits.append(permit)
        self._emit("reserved", permit, requested_timeout_s=requested_timeout_s,
                   min_timeout_s=min_timeout_s)
        return permit

    def confirm_terminated(self, permit, evidence):
        """Caller must supply independently obtained remote termination evidence."""
        if permit not in self._permits or permit.call_id is None or permit.state != "settled":
            raise AllowanceError("termination confirmation requires a settled sent permit")
        if not isinstance(evidence, dict) or not evidence:
            raise ValueError("explicit termination evidence is required")
        permit.terminal_confirmed = True
        self._emit("termination_confirmed", permit, evidence=evidence)
