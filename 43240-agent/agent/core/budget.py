"""Cooperative time accounting; hard supervision is a separate concern."""
from __future__ import annotations
import math
import time
from collections.abc import Callable


class BudgetExhausted(RuntimeError):
    pass


class Budget:
    def __init__(self, deadline_s: float, reserve_s: float = 20.0, *,
                 clock: Callable[[], float] = time.monotonic, started_at: float | None = None):
        if not math.isfinite(deadline_s) or deadline_s <= 0:
            raise ValueError('deadline_s must be positive and finite')
        if not math.isfinite(reserve_s) or reserve_s < 0:
            raise ValueError('reserve_s must be finite and nonnegative')
        self.deadline_s, self.reserve_s = deadline_s, reserve_s
        self._clock = clock
        self._deadline = (clock() if started_at is None else started_at) + deadline_s

    def remaining_s(self, include_reserve: bool = False) -> float:
        return max(0.0, self._deadline - self._clock() - (0.0 if include_reserve else self.reserve_s))

    def consume_previous(self, elapsed_s: float):
        """Debit a shared initial phase during controlled repair replay."""
        if type(elapsed_s) not in (int, float) or not math.isfinite(elapsed_s) or elapsed_s < 0:
            raise ValueError('previous elapsed time must be finite and nonnegative')
        self._deadline -= elapsed_s

    def can_start(self, minimum_s: float = 0.0) -> bool:
        if not math.isfinite(minimum_s) or minimum_s < 0:
            raise ValueError('minimum_s must be finite and nonnegative')
        return self.remaining_s() > max(0.0, minimum_s)

    def timeout_s(self, limit_s: float, minimum_s: float = 0.0) -> float:
        if not math.isfinite(limit_s) or limit_s <= 0:
            raise ValueError('action timeout must be positive and finite')
        if not math.isfinite(minimum_s) or minimum_s < 0:
            raise ValueError('minimum_s must be finite and nonnegative')
        timeout = min(limit_s, self.remaining_s())
        if timeout <= max(0.0, minimum_s):
            raise BudgetExhausted('solve budget exhausted')
        return timeout
