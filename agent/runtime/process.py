"""Task-group subprocesses, bounded tree cleanup and file-backed output."""

from dataclasses import dataclass
import os
import ctypes
import json
from contextlib import contextmanager
import threading
import signal
import subprocess
import tempfile
import time
from pathlib import Path
import sys


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
        # Adopt tool descendants for per-call cleanup. All tools also stay in
        # the task's process group, so the outer timeout can kill them even if
        # this Python process has already been killed or stopped.
        try:
            self.subreaper = (
                ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) == 0
            )
        except (OSError, AttributeError):
            self.subreaper = False

    @staticmethod
    def _kill(pid):
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    def _cleanup(self, proc):
        if proc.poll() is None:
            try:
                os.kill(proc.pid, signal.SIGTERM)
                os.kill(proc.pid, signal.SIGCONT)
            except ProcessLookupError:
                pass
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                self._kill(proc.pid)
                proc.wait(timeout=1.0)

    def run(self, command, *, cwd=None, timeout_s=None, env=None):
        timeout = self.budget.timeout(timeout_s or self.budget.deadline_s)
        self.sequence += 1
        identity = f"p{self.sequence:03d}"
        started = time.monotonic()
        with self.record.span(
            "process", process_id=identity, command=list(command), cwd=str(cwd)
        ):
            with tempfile.TemporaryDirectory(prefix="rtla_process_") as control, tempfile.TemporaryFile() as stream:
                result_path = Path(control) / "result.json"
                proc = None
                timed_out = False
                try:
                    try:
                        with defer_cancellation():
                            proc = subprocess.Popen(
                                [sys.executable, str(Path(__file__).with_name("process_worker.py")), str(result_path), *command],
                                cwd=cwd,
                                env=env,
                                stdout=stream,
                                stderr=subprocess.STDOUT,
                            )
                            self.groups[proc.pid] = proc
                            self.record.emit(
                                "process", "spawned", process_id=identity,
                                pid=proc.pid, pgid=os.getpgrp(),
                            )
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
                        self._cleanup(proc)
                        self.groups.pop(proc.pid, None)
                    stream.seek(0)
                    output = stream.read().decode("utf-8", errors="replace")
                    path = self.record.write_text(
                        f"process_logs/{identity}.log", output
                    )
                try:
                    tool_result = json.loads(result_path.read_text())
                    if type(tool_result.get("rc")) is not int:
                        raise ValueError("missing tool return code")
                except (OSError, ValueError, AttributeError):
                    tool_result = {"rc": -1, "status": "worker_failed"}
                if tool_result.get("status") in ("unavailable", "worker_failed", "cleanup_failed"):
                    self.record.emit("process", tool_result["status"], process_id=identity,
                                     rc=-1, error=tool_result.get("error"), worker_rc=proc.returncode)
                result = ProcessResult(
                    tool_result["rc"], output, time.monotonic() - started, timed_out, path
                )
                self.record.emit(
                    "process",
                    "result",
                    process_id=identity,
                    rc=result.rc,
                    worker_rc=proc.returncode,
                    timed_out=timed_out,
                    elapsed_s=result.elapsed_s,
                    log_path=path,
                    excerpt=output[-2048:],
                )
                return result

    def close(self):
        for pid, proc in list(self.groups.items()):
            self._cleanup(proc)
            self.groups.pop(pid, None)
