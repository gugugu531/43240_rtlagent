"""Hard wall-clock boundary around a registered, reconstructible workflow."""
from __future__ import annotations
from dataclasses import dataclass, field
import ctypes
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import signal
import threading
import time
from .artifacts import atomic_write_json, atomic_write_text
from .candidate import Candidate
from .core.state import WorkflowResult
from .core.config import ModelConfig, ToolConfig
from .core.task import TaskSpec
from .runner import Runner, RunOptions
from .services.processes import ProcessExecutor, RemoteProcessExecutor, ProcessResult


@dataclass(frozen=True)
class RunSpec:
    task: TaskSpec
    workflow_name: str
    options: RunOptions
    workflow_parameters: dict = field(default_factory=dict)
    import_modules: tuple[str, ...] = ()
    started_at: float | None = None
    model_config: ModelConfig | None = None
    tool_config: ToolConfig | None = None
    configuration: dict = field(default_factory=dict)

    def __post_init__(self):
        # Production boundaries carry data, never a closure or live component.
        json.dumps(self.workflow_parameters, allow_nan=False)


def _worker(connection, spec):
    os.setsid()
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    from .core.registry import build_workflow, load_builtin_components, load_extensions
    from .tools import RtlToolchain
    executor = RemoteProcessExecutor(connection)

    def workflow():
        load_builtin_components()
        load_extensions(spec.import_modules)
        return build_workflow(spec.workflow_name, **spec.workflow_parameters)

    try:
        runner = Runner(spec.model_config, process_executor=executor, tool_config=spec.tool_config,
                        configuration=spec.configuration)
        result = runner.run(spec.task, workflow, options=spec.options, started_at=spec.started_at)
        connection.send(('result', result))
    except BaseException as exc:
        # Error text can include user supplied secrets; report only its type.
        connection.send(('worker_error', type(exc).__name__))
    finally:
        connection.close()


class Supervisor:
    def __init__(self):
        self._cancel_reason = None

    def cancel(self, reason='cancelled'):
        self._cancel_reason = reason

    def run(self, spec: RunSpec) -> WorkflowResult:
        started = spec.started_at if spec.started_at is not None else time.monotonic()
        from dataclasses import replace
        spec = replace(spec, started_at=started)
        options = spec.options
        out = Path(options.output_dir)
        out.mkdir(parents=True, exist_ok=True)
        # Contract files exist even if input/configuration/worker startup fails.
        atomic_write_text(out / 'solution.v', '')
        atomic_write_text(out / 'trace.jsonl', '')
        if spec.configuration:
            atomic_write_json(out / 'config.json', spec.configuration)
        atomic_write_json(out / 'selection.json', {'candidate_id': None})
        locator = out / 'run_locator.json'
        locator.unlink(missing_ok=True)
        import uuid
        fallback_id = uuid.uuid4().hex
        fallback = dict(run_id=fallback_id, level=options.recording.level,
                        record_dir=str((options.recording.root or out / 'records') / fallback_id))
        atomic_write_json(locator, fallback)
        hard_deadline = started + options.deadline_s
        solve_deadline = hard_deadline - options.reserve_s
        context = multiprocessing.get_context('fork')
        parent, child = context.Pipe()
        worker = context.Process(target=_worker, args=(child, spec), name='agent_worker')
        executor = ProcessExecutor()
        result, reason, active, error_type = None, None, None, None
        old_handlers = {}
        # This dedicated CLI process adopts descendants for reaping on Linux.
        previous_subreaper = ctypes.c_int(0)
        libc = None
        try:
            libc = ctypes.CDLL(None)
            libc.prctl(37, ctypes.byref(previous_subreaper), 0, 0, 0)
            libc.prctl(36, 1, 0, 0, 0)  # PR_SET_CHILD_SUBREAPER
        except (AttributeError, OSError):
            pass
        if threading.current_thread() is threading.main_thread():
            for sig in (signal.SIGTERM, signal.SIGINT):
                old_handlers[sig] = signal.getsignal(sig)
                signal.signal(sig, lambda signum, frame: self.cancel(signal.Signals(signum).name.lower()))
        try:
            if time.monotonic() >= solve_deadline:
                reason = 'deadline'
            else:
                worker.start()
                child.close()
                while True:
                    if self._cancel_reason or time.monotonic() >= solve_deadline:
                        reason = self._cancel_reason or 'deadline'
                        break
                    if active is not None:
                        reply = executor.poll(active)
                        if reply is not None:
                            parent.send(('process_result', reply))
                            active = None
                    if parent.poll(0.005):
                        try:
                            kind, payload = parent.recv()
                        except EOFError:
                            reason = 'worker_exit'
                            break
                        if kind == 'process':
                            payload, secrets = payload
                            executor.redactor.add_secrets(secrets)
                            if active is not None:
                                raise RuntimeError('overlapping worker process requests')
                            # Preserve raw process logs even if the worker is killed.
                            if executor.log_dir is None:
                                try:
                                    info = json.loads(locator.read_text())
                                    executor.log_dir = str(Path(info['record_dir']) / 'process_logs') if info['level'] == 'full' else None
                                except (OSError, ValueError, KeyError):
                                    pass
                            from dataclasses import replace
                            request = replace(payload, timeout_s=min(payload.timeout_s,
                                              max(0.0, solve_deadline - time.monotonic())))
                            try:
                                if request.timeout_s <= 0:
                                    parent.send(('process_result', ProcessResult(124, 'timeout', 0, 'no process budget remaining')))
                                else:
                                    active = executor.start(request)
                            except OSError as exc:
                                parent.send(('process_result', ProcessResult(-1, 'unavailable', 0,
                                            f'process launch failed ({type(exc).__name__})')))
                        elif kind == 'result':
                            result = payload
                            break
                        elif kind == 'worker_error':
                            error_type, reason = payload, 'worker_error'
                            break
                    elif not worker.is_alive():
                        reason = 'worker_exit'
                        break
        except Exception as exc:
            reason, error_type = 'supervisor_error', type(exc).__name__
        finally:
            # No trace handoff until the sole worker writer has stopped.
            cleanup_deadline = min(hard_deadline, time.monotonic() + 1.0)
            if worker.pid and worker.is_alive():
                ProcessExecutor._signal(worker.pid, signal.SIGTERM)
                worker.join(timeout=max(0, min(0.15, cleanup_deadline - time.monotonic())))
                if worker.is_alive():
                    ProcessExecutor._signal(worker.pid, signal.SIGKILL)
                    worker.kill()  # also covers setsid startup races
                    worker.join(timeout=max(0, cleanup_deadline - time.monotonic()))
            cleanup = executor.cancel_all(cleanup_deadline)
            if worker.pid:
                # Kill remaining children in the worker group on normal exit too.
                ProcessExecutor._signal(worker.pid, signal.SIGKILL)
                worker.join(timeout=max(0, cleanup_deadline - time.monotonic()))
            groups = set(executor.groups) | ({worker.pid} if worker.pid else set())
            adopted = self._reap_groups(groups, cleanup_deadline)
            if libc is not None:
                libc.prctl(36, previous_subreaper.value, 0, 0, 0)
            parent.close()
            child.close()
            for sig, handler in old_handlers.items():
                signal.signal(sig, handler)
        if worker.pid and worker.is_alive():
            # Never append concurrently with a worker that could still write.
            return WorkflowResult('', None, 'cleanup_incomplete', 'error')
        selected, selection_state = recover_selection(out)
        if result is not None:
            previous = result.selected_candidate
            same = (previous is None and selected is None) or (previous is not None and selected is not None
                    and previous.id == selected.id and previous.code_hash == selected.code_hash
                    and previous.code == selected.code)
            if not same:
                reason = 'selection_recovery_error'
            result = WorkflowResult(result.run_id, selected, reason or result.stop_reason,
                                    'error' if not same else result.status)
        interruption = reason or (result.stop_reason if result else 'worker_exit')
        if result is None:
            result = WorkflowResult(_read_locator(out).get('run_id', ''), selected, interruption,
                                    'stopped' if interruption in ('deadline', 'sigterm', 'sigint', 'cancelled') else 'error')
        fields = dict(status='interrupted' if reason else 'completed', stop_reason=interruption,
                      worker_exitcode=worker.exitcode if worker.pid else None,
                      process_logs_incomplete=executor.recording_incomplete,
                      error_type=error_type, selection_recovery=selection_state,
                      selected_candidate_id=selected.id if selected else None,
                      terminated_groups=list(cleanup.terminated_groups),
                      unreaped_pids=list(cleanup.unreaped_pids) + list(adopted),
                      backend_inference_cancelled='unknown')
        record_supervision(out, fields, result, interrupted=reason is not None)
        self._cancel_reason = None
        return result

    @staticmethod
    def _reap_groups(groups, deadline):
        remaining = set(groups)
        while remaining and time.monotonic() < deadline:
            for pgid in tuple(remaining):
                try:
                    pid, _ = os.waitpid(-pgid, os.WNOHANG)
                    if pid == 0:
                        continue
                except ChildProcessError:
                    remaining.discard(pgid)
            if remaining:
                time.sleep(0.005)
        return tuple(remaining)


def _read_locator(out):
    try:
        return json.loads((Path(out) / 'run_locator.json').read_text())
    except (OSError, ValueError):
        return {}


def recover_selection(out):
    out = Path(out)
    try:
        saved = json.loads((out / 'selection.json').read_text())
        if saved.get('candidate_id') is None:
            atomic_write_text(out / 'solution.v', '')
            return None, 'empty'
        code, metadata = saved['code'], saved['candidate']
        digest = hashlib.sha256(code.encode()).hexdigest()
        if digest != saved['code_hash'] or digest != metadata['code_hash'] or metadata['id'] != saved['candidate_id']:
            raise ValueError('checkpoint hash/identity mismatch')
        candidate = Candidate(code=code, **{k: v for k, v in metadata.items() if k != 'code_bytes'})
        previous = (out / 'solution.v').read_text()
        if previous != code:
            atomic_write_text(out / 'solution.v', code)
        return candidate, 'verified' if previous == code else 'restored'
    except (OSError, ValueError, KeyError, TypeError):
        # A file without verified provenance cannot be described as selected.
        atomic_write_text(out / 'solution.v', '')
        return None, 'invalid_checkpoint'


def record_supervision(out, fields, result, *, interrupted):
    """Append after worker exit; leave unfinished call/node evidence untouched."""
    from .recording.recorder import TRACE_SCHEMA_VERSION
    out = Path(out)
    trace = out / 'trace.jsonl'
    locator = _read_locator(out)
    events = []
    raw = trace.read_bytes() if trace.exists() else b''
    valid = bytearray()
    for line in raw.splitlines(keepends=True):
        try:
            events.append(json.loads(line))
            valid.extend(line if line.endswith(b'\n') else line + b'\n')
        except (ValueError, UnicodeDecodeError):
            # Retain interrupted bytes separately; return parseable JSONL.
            atomic_write_text(out / 'trace_partial.txt', line.decode(errors='replace'))
    event = dict(fields, tool='supervisor', event='result', schema_version=TRACE_SCHEMA_VERSION,
                 run_id=locator.get('run_id', result.run_id),
                 seq=max((e.get('seq', 0) for e in events), default=0) + 1, ts=round(time.time(), 3))
    atomic_write_text(trace, valid.decode() + json.dumps(event, ensure_ascii=False) + '\n')
    atomic_write_json(out / 'supervision.json', fields)
    if locator.get('level') == 'full':
        directory = Path(locator['record_dir'])
        try:
            atomic_write_json(directory / 'supervision.json', fields)
            path = directory / 'run.json'
            if path.is_file():
                manifest = json.loads(path.read_text())
            else:
                manifest = dict(schema_version=TRACE_SCHEMA_VERSION, run_id=locator.get('run_id'),
                                level=locator.get('level'), calls={}, nodes={}, recording_incomplete=True)
            manifest['supervision'] = fields
            if fields.get('process_logs_incomplete'):
                manifest['recording_incomplete'] = True
            if interrupted:
                manifest.update(status='interrupted', finished_at=time.time())
                manifest['result'] = dict(status=result.status, stop_reason=result.stop_reason,
                                         selected_candidate_id=result.selected_candidate.id if result.selected_candidate else None)
            atomic_write_json(path, manifest)
        except (OSError, ValueError):
            pass  # Optional full recording must not replace the solve result.
