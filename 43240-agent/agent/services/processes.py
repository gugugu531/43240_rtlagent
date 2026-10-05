"""Process execution owned by the supervisor; worker calls use a pipe."""
from __future__ import annotations
from dataclasses import dataclass, field
import math
import os
import signal
import subprocess
import tempfile
import time


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


@dataclass(frozen=True)
class CleanupResult:
    terminated_groups: tuple[int, ...]
    unreaped_pids: tuple[int, ...]


class ProcessExecutor:
    def __init__(self, *, log_dir=None):
        from ..recording.redaction import Redactor
        self.redactor = Redactor()
        self._jobs = {}
        self.log_dir = log_dir
        self.recording_incomplete = False
        self._sequence = 0
        self.groups = set()

    def start(self, request: ProcessRequest):
        self._sequence += 1
        identity = self._sequence
        started = time.monotonic()
        # File output avoids pipe buffer deadlocks and inherited-pipe hangs.
        if self.log_dir:
            try:
                os.makedirs(self.log_dir, exist_ok=True)
                stream = open(os.path.join(self.log_dir, f'process_{identity:03d}.log'), 'w+b')
            except OSError:
                self.recording_incomplete = True
                stream = tempfile.TemporaryFile()
        else:
            stream = tempfile.TemporaryFile()
        try:
            proc = subprocess.Popen(request.command, cwd=request.cwd, env=request.env,
                                    start_new_session=True, stdout=stream, stderr=subprocess.STDOUT)
        except BaseException:
            stream.close()
            raise
        self.groups.add(proc.pid)
        self._jobs[identity] = dict(proc=proc, stream=stream, started=started,
                                   deadline=started + max(0.0, request.timeout_s - request.terminate_grace_s),
                                   grace=request.terminate_grace_s, term_at=None, timeout=False)
        return identity

    def poll(self, identity):
        job = self._jobs[identity]
        proc = job['proc']
        now = time.monotonic()
        if now >= job['deadline'] and job['term_at'] is None:
            job['timeout'] = True
            job['term_at'] = now
            self._signal(proc.pid, signal.SIGTERM)
        if job['term_at'] is not None and now - job['term_at'] >= job['grace']:
            self._signal(proc.pid, signal.SIGKILL)
        rc = proc.poll()
        if rc is None:
            return None
        # Descendants may still hold this process group after its leader exits.
        self._signal(proc.pid, signal.SIGKILL)
        stream = job['stream']
        stream.flush()
        stream.seek(0)
        output = stream.read().decode('utf-8', errors='replace')
        self._sanitize_stream(stream, output)
        stream.close()
        del self._jobs[identity]
        return ProcessResult(124 if job['timeout'] else rc,
                             'timeout' if job['timeout'] else 'ok' if rc == 0 else 'failed',
                             now - job['started'], output)

    def run(self, request: ProcessRequest):
        if request.timeout_s <= 0:
            return ProcessResult(124, 'timeout', 0.0, 'no process budget remaining')
        try:
            identity = self.start(request)
        except OSError as exc:
            return ProcessResult(-1, 'unavailable', 0.0, f'process launch failed ({type(exc).__name__})')
        while True:
            result = self.poll(identity)
            if result is not None:
                return result
            time.sleep(0.005)

    def cancel_all(self, deadline: float) -> CleanupResult:
        groups = tuple(job['proc'].pid for job in self._jobs.values())
        for pgid in groups:
            self._signal(pgid, signal.SIGTERM)
        grace = min(deadline, time.monotonic() + 0.15)
        while time.monotonic() < grace and any(j['proc'].poll() is None for j in self._jobs.values()):
            time.sleep(0.005)
        for pgid in groups:
            self._signal(pgid, signal.SIGKILL)
        pending = []
        for job in self._jobs.values():
            try:
                job['proc'].wait(timeout=max(0.0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                pending.append(job['proc'].pid)
            stream = job['stream']
            stream.flush()
            stream.seek(0)
            self._sanitize_stream(stream, stream.read().decode('utf-8', errors='replace'))
            stream.close()
        self._jobs.clear()
        return CleanupResult(groups, tuple(pending))

    def _sanitize_stream(self, stream, output):
        # Run results keep their exact output; persisted copies remove secrets.
        try:
            stream.seek(0)
            stream.truncate()
            stream.write(self.redactor.copy(output).encode('utf-8'))
            stream.flush()
        except OSError:
            self.recording_incomplete = True
            if isinstance(stream.name, str):
                try:
                    os.unlink(stream.name)
                except OSError:
                    pass

    @staticmethod
    def _signal(pgid, sig):
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            pass


class RemoteProcessExecutor:
    def __init__(self, connection):
        self._connection = connection
        self._recorder = None

    def set_recorder(self, recorder):
        self._recorder = recorder

    def run(self, request: ProcessRequest) -> ProcessResult:
        secrets = tuple(self._recorder.redactor.secrets) if self._recorder else ()
        self._connection.send(('process', (request, secrets)))
        message, result = self._connection.recv()
        if message != 'process_result':
            raise RuntimeError('unexpected supervisor response')
        return result


class ProcessService:
    """Public custom-action process API with budget and mandatory call evidence."""
    def __init__(self, budget, executor, cancellation, emit):
        self._budget, self._executor = budget, executor
        self._cancellation, self._emit = cancellation, emit
        self._sequence = 0

    def run(self, request: ProcessRequest) -> ProcessResult:
        from dataclasses import replace
        self._cancellation.raise_if_cancelled()
        request = replace(request, timeout_s=self._budget.timeout_s(request.timeout_s))
        self._sequence += 1
        identity = f'p{self._sequence:03d}'
        self._emit('started', process_id=identity, command=list(request.command), timeout_s=request.timeout_s)
        try:
            result = self._executor.run(request)
        except BaseException as exc:
            self._emit('failed', process_id=identity, error_type=type(exc).__name__)
            raise
        self._emit('result', process_id=identity, status=result.status, rc=result.rc,
                   elapsed_s=result.elapsed_s, excerpt=result.output[:2000])
        return result
