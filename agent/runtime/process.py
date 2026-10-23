"""Subprocess groups, bounded waits and file-backed output."""

from dataclasses import dataclass
import os
import ctypes
from contextlib import contextmanager
import threading
import signal
import subprocess
import tempfile
import time


@contextmanager
def defer_cancellation():
    """Finish spawn registration before delivering a main-thread cancellation.

    Unlike a blocked POSIX signal mask, temporary Python handlers do not leave
    exec'ed children with SIGTERM blocked.
    """
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    pending = []
    signals = (signal.SIGALRM, signal.SIGTERM, signal.SIGINT)
    handlers = {sig: signal.getsignal(sig) for sig in signals}
    try:
        for sig in signals:
            signal.signal(sig, lambda signum, frame: pending.append(signum))
        yield
    finally:
        for sig, handler in handlers.items():
            signal.signal(sig, handler)
        if pending:
            signal.raise_signal(pending[0])


@dataclass(frozen=True)
class ProcessResult:
    rc: int
    stdout: str
    elapsed_s: float
    timed_out: bool = False
    log_path: str | None = None


class ProcessManager:
    def __init__(self, budget, record):
        self.budget, self.record = budget, record
        self.groups = {}
        self.sequence = 0
        # Adopt descendants so killed tool groups do not leave zombies at PID 1.
        try:
            self.subreaper = (
                ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) == 0
            )
        except (OSError, AttributeError):
            self.subreaper = False

    @staticmethod
    def _kill(pgid):
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    def _reap(self, pgid):
        if not self.subreaper:
            return
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            try:
                pid, _ = os.waitpid(-pgid, os.WNOHANG)
            except ChildProcessError:
                return
            if pid == 0:
                time.sleep(0.01)

    def run(self, command, *, cwd=None, timeout_s=None, env=None):
        timeout = self.budget.timeout(timeout_s or self.budget.deadline_s)
        self.sequence += 1
        identity = f"p{self.sequence:03d}"
        started = time.monotonic()
        with self.record.span(
            "process", process_id=identity, command=list(command), cwd=str(cwd)
        ):
            with tempfile.TemporaryFile() as stream:
                proc = None
                timed_out = False
                try:
                    try:
                        with defer_cancellation():
                            proc = subprocess.Popen(
                                command,
                                cwd=cwd,
                                env=env,
                                stdout=stream,
                                stderr=subprocess.STDOUT,
                                start_new_session=True,
                            )
                            self.groups[proc.pid] = proc
                    except OSError as exc:
                        self.record.emit(
                            "process",
                            "unavailable",
                            process_id=identity,
                            rc=-1,
                            error=str(exc),
                            error_type=type(exc).__name__,
                        )
                        return ProcessResult(-1, str(exc), time.monotonic() - started)
                    try:
                        proc.wait(timeout=timeout)
                    except subprocess.TimeoutExpired:
                        timed_out = True
                finally:
                    if proc is not None:
                        self._kill(proc.pid)
                        proc.wait()
                        self._reap(proc.pid)
                        self.groups.pop(proc.pid, None)
                    stream.seek(0)
                    output = stream.read().decode("utf-8", errors="replace")
                    path = self.record.write_text(
                        f"process_logs/{identity}.log", output
                    )
                result = ProcessResult(
                    proc.returncode, output, time.monotonic() - started, timed_out, path
                )
                self.record.emit(
                    "process",
                    "result",
                    process_id=identity,
                    rc=result.rc,
                    timed_out=timed_out,
                    elapsed_s=result.elapsed_s,
                    log_path=path,
                    excerpt=output[-2048:],
                )
                return result

    def close(self):
        for pgid, proc in list(self.groups.items()):
            self._kill(pgid)
            proc.wait()
            self._reap(pgid)
            self.groups.pop(pgid, None)
