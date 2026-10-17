"""Serializable requests and results for managed processes."""
from __future__ import annotations
from dataclasses import dataclass, field
import math


@dataclass(frozen=True)
class ProcessRequest:
    command: tuple[str, ...]
    cwd: str
    timeout_s: float
    env: dict[str, str] | None = field(default=None, repr=False)
    terminate_grace_s: float = 0.15

    def __post_init__(self):
        if not self.command or any(not isinstance(part, str) for part in self.command):
            raise ValueError('command must contain strings')
        object.__setattr__(self, 'command', tuple(self.command))
        for value in (self.timeout_s, self.terminate_grace_s):
            if not math.isfinite(value) or value < 0:
                raise ValueError('process times must be finite and nonnegative')


@dataclass(frozen=True)
class ProcessResult:
    rc: int
    status: str
    elapsed_s: float
    output: str
    log_path: str | None = None


@dataclass(frozen=True)
class CleanupResult:
    terminated_groups: tuple[int, ...]
    unreaped_pids: tuple[int, ...]
