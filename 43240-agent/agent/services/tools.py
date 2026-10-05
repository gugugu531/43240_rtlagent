"""Record solver checks without assigning retry or repair policy."""
from __future__ import annotations
from collections.abc import Callable
import time
from ..candidate import Candidate
from ..core.budget import Budget
from ..core.state import CheckResult
from ..core.task import TaskSpec
from ..interface import check_interface_result
from ..tools import RtlToolchain


class ToolService:
    def __init__(self, budget: Budget, allocate_id: Callable[[], str],
                 publish: Callable[[CheckResult], None], *,
                 toolchain_factory: Callable[[], RtlToolchain] = RtlToolchain):
        self._budget, self._allocate_id, self._publish = budget, allocate_id, publish
        self._factory = toolchain_factory
        self._toolchain = None

    def check_interface(self, task: TaskSpec, candidate: Candidate) -> CheckResult:
        start = time.monotonic()
        result = check_interface_result(candidate.code, task.interface, task.prompt)
        status = {'ok': 'passed', 'mismatch': 'failed', 'advisory': 'failed',
                  'skipped': 'skipped', 'parse_error': 'error'}[result.status]
        check = CheckResult(self._allocate_id(), candidate.id, 'interface', status,
                            result.summary, blocking=result.blocking, rc=result.rc,
                            elapsed_s=time.monotonic() - start, details=result.trace_dict())
        self._publish(check)
        return check

    def lint(self, candidate: Candidate, top: str, *, timeout_s: float = 300.0) -> CheckResult:
        return self._run('lint', candidate, top, timeout_s)

    def synth(self, candidate: Candidate, top: str, *, timeout_s: float = 900.0) -> CheckResult:
        return self._run('synth', candidate, top, timeout_s)

    def _run(self, kind, candidate, top, timeout_s):
        timeout = self._budget.timeout_s(timeout_s)
        check_id = self._allocate_id()
        start = time.monotonic()
        try:
            if self._toolchain is None:
                self._toolchain = self._factory()
            result = getattr(self._toolchain, kind)(candidate.code, top, timeout_s=timeout)
        except Exception as exc:
            check = CheckResult(check_id, candidate.id, kind, 'error',
                                f'check service failed ({type(exc).__name__})', blocking=True,
                                rc=1, elapsed_s=time.monotonic() - start,
                                details={'error_type': type(exc).__name__})
            self._publish(check)
            raise
        check = CheckResult(check_id, candidate.id, kind,
                            'passed' if result.status == 'ok' else result.status,
                            result.summary, blocking=result.status in ('failed', 'timeout'),
                            rc=result.rc, elapsed_s=result.elapsed_s, command=result.command,
                            full_log_path=result.full_log_path, work_dir=result.work_dir)
        self._publish(check)
        return check
