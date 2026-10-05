"""Own one solve lifecycle; workflow decisions stay in Python components."""
from __future__ import annotations
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
import inspect
import time
from .artifacts import ArtifactStore
from .context import RunContext
from .core.budget import Budget
from .core.components import Workflow, describe_component
from .core.config import ModelConfig
from .core.metadata import git_metadata
from .core.state import WorkflowResult
from .core.task import TaskSpec
from .recording.recorder import RunRecorder, RecordingConfig, RecordingError
from .services.model import ModelService, make_backend
from .tools import RtlToolchain

ROOT = Path(__file__).parent.parent


@dataclass(frozen=True)
class RunOptions:
    output_dir: Path
    deadline_s: float = 360.0
    reserve_s: float = 20.0
    recording: RecordingConfig = field(default_factory=RecordingConfig)
    save_candidates: bool = False


class Runner:
    def __init__(self, model_config: ModelConfig | None = None, *,
                 backend_factory=make_backend, toolchain_factory=RtlToolchain, process_executor=None):
        self._config = model_config
        self._process_executor = process_executor
        self._backend_factory, self._toolchain_factory = backend_factory, toolchain_factory

    def run(self, task: TaskSpec, workflow: Workflow | Callable[[], Workflow], *,
            options: RunOptions, started_at: float | None = None) -> WorkflowResult:
        started_at = time.monotonic() if started_at is None else started_at
        artifacts = ArtifactStore(options.output_dir, save_candidates=options.save_candidates)
        recorder = RunRecorder(options.output_dir, options.recording)
        if callable(getattr(self._process_executor, "set_recorder", None)):
            self._process_executor.set_recorder(recorder)
        ctx = None
        result = None
        try:
            budget = Budget(options.deadline_s, options.reserve_s, started_at=started_at)
            config = self._config or ModelConfig.from_env()
            llm = ModelService(self._backend_factory(config), recorder, timeout_limit_s=config.timeout_s)
            factory = self._toolchain_factory
            if factory is RtlToolchain:
                factory = lambda: RtlToolchain(executor=self._process_executor,
                    log_dir=recorder.run_dir / 'tool_logs' if options.recording.level == 'full' else None,
                    redactor=recorder.redactor)
            ctx = RunContext(task, llm, budget, artifacts, recorder, toolchain_factory=factory, process_executor=self._process_executor)
            # A factory creates fresh workflow/node instances for each task and is
            # invoked after artifacts exist, so constructor failures are recorded.
            instance = workflow if not inspect.isclass(workflow) and callable(getattr(workflow, 'run', None)) else workflow()
            spec = describe_component(instance)
            recorder.record_metadata(mode='agent', task_id=task.id, task=task.public_dict(),
                                     workflow=spec.public_dict(), model=config.public_dict(),
                                     runtime=dict(deadline_s=options.deadline_s, reserve_s=options.reserve_s,
                                                  save_candidates=options.save_candidates),
                                     git=git_metadata(str(ROOT)))
            recorder.record_task(task)
            recorder.write_event('agent', 'start', workflow=spec.public_dict())
            result = instance.run(ctx)
            if not isinstance(result, WorkflowResult):
                raise TypeError('workflow.run() must return ctx.finish() result')
            if (result.run_id != recorder.run_id or result.selected_candidate != artifacts.selected
                    or result.stop_reason != ctx.state.stop_reason):
                raise ValueError('workflow result disagrees with the selected artifact or run state')
        except RecordingError:
            raise
        except Exception as exc:
            recorder.write_event('agent', 'error', error_type=type(exc).__name__, excerpt=str(exc))
            result = (ctx.finish(reason='workflow_error', status='error') if ctx else
                      WorkflowResult(recorder.run_id, artifacts.selected, 'initialization_error', 'error'))
        finally:
            try:
                selected = artifacts.selected
                recorder.record_result(result)
                recorder.write_event('agent', 'done', candidate_id=selected.id if selected else None,
                                     code_hash=selected.code_hash if selected else None,
                                     bytes=len(selected.code.encode('utf-8')) if selected else 0,
                                     status=result.status if result else 'error',
                                     stop_reason=result.stop_reason if result else 'recording_error')
            finally:
                recorder.close()
        return result
