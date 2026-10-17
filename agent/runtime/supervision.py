"""Hard wall-clock boundary around a reconstructible component assembly."""
from __future__ import annotations
from dataclasses import dataclass
import ctypes
import multiprocessing
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
import os
from pathlib import Path
import signal
import threading
import time
from agent.recording.artifacts import atomic_write_json, atomic_write_text
from agent.core.state import WorkflowResult
from agent.runtime.runner import Runner
from agent.runtime.specification import RunSpec
from agent.recording.recorder import record_dir
from agent.recording.recovery import recover_selection, record_supervision
from agent.services.processes import ProcessExecutor, RemoteProcessExecutor
from agent.core.process import CleanupResult, ProcessResult


@dataclass
class _SupervisionRun:
    spec: RunSpec
    out: Path
    hard_deadline: float
    solve_deadline: float
    parent: Connection
    child: Connection
    worker: BaseProcess
    executor: ProcessExecutor
    result: WorkflowResult | None = None
    reason: str | None = None
    active: int | None = None
    error_type: str | None = None


def _worker(connection, spec):
    os.setsid()
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    from agent.composition.assembler import assemble
    executor = RemoteProcessExecutor(connection)

    def workflow():
        return assemble(spec.assembly)

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
        run = self._prepare(spec)
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
            self._run_worker(run)
        except Exception as exc:
            run.reason, run.error_type = 'supervisor_error', type(exc).__name__
        finally:
            cleanup, adopted = self._cleanup(run)
            if libc is not None:
                libc.prctl(36, previous_subreaper.value, 0, 0, 0)
            run.parent.close()
            run.child.close()
            for sig, handler in old_handlers.items():
                signal.signal(sig, handler)
        return self._reconcile_result(run, cleanup, adopted)

    @staticmethod
    def _prepare(spec: RunSpec) -> _SupervisionRun:
        started = spec.started_at if spec.started_at is not None else time.monotonic()
        from dataclasses import replace
        import uuid
        # The supervisor owns the run identity, so it can find the records after any worker exit.
        run_id = spec.options.run_id or uuid.uuid4().hex
        spec = replace(spec, started_at=started, options=replace(spec.options, run_id=run_id))
        options = spec.options
        out = Path(options.output_dir)
        out.mkdir(parents=True, exist_ok=True)
        # Contract files exist even if input/configuration/worker startup fails.
        atomic_write_text(out / 'solution.v', '')
        atomic_write_text(out / 'trace.jsonl', '')
        atomic_write_json(out / 'selection.json', {'candidate_id': None})
        hard_deadline = started + options.deadline_s
        solve_deadline = hard_deadline - options.reserve_s
        context = multiprocessing.get_context('fork')
        parent, child = context.Pipe()
        worker = context.Process(target=_worker, args=(child, spec), name='agent_worker')
        # Process output is streamed here, so it survives a killed worker.
        executor = ProcessExecutor(log_dir=str(record_dir(out, options.recording, run_id) / 'process_logs')
                                   if options.recording.level == 'full' else None)
        return _SupervisionRun(spec, out, hard_deadline, solve_deadline, parent, child, worker, executor)

    def _run_worker(self, run: _SupervisionRun):
        if time.monotonic() >= run.solve_deadline:
            run.reason = 'deadline'
            return
        run.worker.start()
        run.child.close()
        while True:
            if self._cancel_reason or time.monotonic() >= run.solve_deadline:
                run.reason = self._cancel_reason or 'deadline'
                break
            if run.active is not None:
                reply = run.executor.poll(run.active)
                if reply is not None:
                    run.parent.send(('process_result', reply))
                    run.active = None
            if run.parent.poll(0.005):
                try:
                    kind, payload = run.parent.recv()
                except EOFError:
                    run.reason = 'worker_exit'
                    break
                if kind == 'process':
                    self._process_request(run, payload)
                elif kind == 'result':
                    run.result = payload
                    break
                elif kind == 'worker_error':
                    run.error_type, run.reason = payload, 'worker_error'
                    break
            elif not run.worker.is_alive():
                run.reason = 'worker_exit'
                break

    @staticmethod
    def _process_request(run: _SupervisionRun, payload):
        payload, secrets = payload
        run.executor.redactor.add_secrets(secrets)
        if run.active is not None:
            raise RuntimeError('overlapping worker process requests')
        from dataclasses import replace
        request = replace(payload, timeout_s=min(payload.timeout_s,
                          max(0.0, run.solve_deadline - time.monotonic())))
        try:
            if request.timeout_s <= 0:
                run.parent.send(('process_result', ProcessResult(124, 'timeout', 0, 'no process budget remaining')))
            else:
                run.active = run.executor.start(request)
        except OSError as exc:
            run.parent.send(('process_result', ProcessResult(-1, 'unavailable', 0,
                            f'process launch failed ({type(exc).__name__})')))

    def _cleanup(self, run: _SupervisionRun) -> tuple[CleanupResult, tuple[int, ...]]:
        # No trace handoff until the sole worker writer has stopped.
        worker, executor = run.worker, run.executor
        cleanup_deadline = min(run.hard_deadline, time.monotonic() + 1.0)
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
        return cleanup, adopted

    def _reconcile_result(self, run: _SupervisionRun, cleanup: CleanupResult,
                          adopted: tuple[int, ...]) -> WorkflowResult:
        worker, executor = run.worker, run.executor
        if worker.pid and worker.is_alive():
            # Never append concurrently with a worker that could still write.
            return WorkflowResult('', None, 'cleanup_incomplete', 'error')
        selected, selection_state = recover_selection(run.out)
        result, reason = run.result, run.reason
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
            result = WorkflowResult(run.spec.options.run_id, selected, interruption,
                                    'stopped' if interruption in ('deadline', 'sigterm', 'sigint', 'cancelled') else 'error')
        fields = dict(status='interrupted' if reason else 'completed', stop_reason=interruption,
                      worker_exitcode=worker.exitcode if worker.pid else None,
                      process_logs_incomplete=executor.recording_incomplete,
                      error_type=run.error_type, selection_recovery=selection_state,
                      selected_candidate_id=selected.id if selected else None,
                      terminated_groups=list(cleanup.terminated_groups),
                      unreaped_pids=list(cleanup.unreaped_pids) + list(adopted),
                      backend_inference_cancelled='unknown')
        record_supervision(run.out, fields, run.spec.options.run_id)
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
