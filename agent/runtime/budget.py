"""One task deadline shared by model calls and managed processes."""

import math
import time


class BudgetExhausted(RuntimeError):
    pass


class Deadline(RuntimeError):
    """Hard deadline or external cancellation; never retry as a model error."""


class Budget:
    def __init__(
        self, deadline_s=900.0, reserve_s=20.0, *, started_at=None, record=None
    ):
        if not math.isfinite(deadline_s) or deadline_s <= 0:
            raise ValueError("deadline must be positive and finite")
        if not math.isfinite(reserve_s) or not 0 <= reserve_s < deadline_s:
            raise ValueError("reserve must be finite and smaller than deadline")
        self.deadline_s, self.reserve_s, self.record = deadline_s, reserve_s, record
        self.started_at = time.monotonic() if started_at is None else started_at

    def remaining_s(self, include_reserve=False):
        return max(
            0.0,
            self.started_at
            + self.deadline_s
            - time.monotonic()
            - (0 if include_reserve else self.reserve_s),
        )

    def can_start(self, minimum_s=0):
        return self.remaining_s() > minimum_s

    def timeout(self, limit):
        if not math.isfinite(limit) or limit <= 0:
            raise ValueError("timeout must be positive and finite")
        remaining = self.remaining_s()
        if remaining <= 0:
            if self.record:
                self.record.emit("budget", "exhausted")
            raise BudgetExhausted("solve budget exhausted")
        if remaining < limit and self.record:
            self.record.emit(
                "budget", "clipped", requested_s=limit, timeout_s=remaining
            )
        return min(limit, remaining)

    timeout_s = timeout
    remaining = remaining_s
