"""Own one solve lifecycle; workflow decisions stay in Python components."""
from __future__ import annotations
from collections.abc import Callable
from pathlib import Path
import inspect
import hashlib
import json
import time
from agent.recording.artifacts import ArtifactStore
from agent.runtime.context import RunContext
from agent.core.budget import Budget
from agent.core.components import Workflow, describe_component
from agent.core.config import ModelConfig, ToolConfig
from agent.core.metadata import git_metadata
from agent.core.state import WorkflowResult
from agent.core.replay_contract import InitialReplayContract
from agent.core.task import TaskSpec
from agent.recording.recorder import RunRecorder, RecordingError
from agent.runtime.specification import RunOptions
from agent.services.model import ModelService, make_backend
from agent.services.vivado import RtlToolchain

ROOT = Path(__file__).resolve().parents[2]


class Runner:
    def __init__(self, model_config: ModelConfig | None = None, *,
                 backend_factory=make_backend, toolchain_factory=RtlToolchain, process_executor=None, tool_config=None, configuration=None):
        self._config = model_config
        self._tool_config = tool_config
        self._configuration = configuration or {}
        self._process_executor = process_executor
        self._backend_factory, self._toolchain_factory = backend_factory, toolchain_factory

    def run(self, task: TaskSpec, workflow: Workflow | Callable[[], Workflow], *,
            options: RunOptions, started_at: float | None = None) -> WorkflowResult:
        started_at = time.monotonic() if started_at is None else started_at
        artifacts = ArtifactStore(options.output_dir)
        recorder = RunRecorder(options.output_dir, options.recording, run_id=options.run_id)
        if callable(getattr(self._process_executor, "set_recorder", None)):
            self._process_executor.set_recorder(recorder)
        ctx = None
        result = None
        configuration = dict(self._configuration)
        try:
            budget = Budget(options.deadline_s, options.reserve_s, started_at=started_at)
            config = self._config or ModelConfig.from_env()
            from agent.core.tokens import TokenPolicy
            counter = None
            if config.tokenizer_dir:
                from agent.services.tokenizer import LocalTokenCounter
                try:
                    counter = LocalTokenCounter(config.tokenizer_dir,
                        expected_tokenizer_sha256=config.tokenizer_sha256,
                        expected_template_sha256=config.template_sha256)
                except Exception as exc:
                    recorder.write_event('tokens', 'counter_unavailable', error_type=type(exc).__name__)
            llm = ModelService(self._backend_factory(config), recorder, timeout_limit_s=config.timeout_s,
                token_counter=counter, token_policy=TokenPolicy(config.token_total_limit, config.token_output_limit),
                context_limit=config.context_limit, strict_context=config.strict_context,
                template_options={} if config.enable_thinking is None else {'enable_thinking': config.enable_thinking})
            factory = self._toolchain_factory
            if factory is RtlToolchain:
                factory = lambda: RtlToolchain(config=self._tool_config, executor=self._process_executor,
                    log_dir=recorder.run_dir / 'tool_logs' if options.recording.level == 'full' else None,
                    redactor=recorder.redactor)
            ctx = RunContext(task, llm, budget, artifacts, recorder, toolchain_factory=factory,
                             process_executor=self._process_executor, started_at=started_at,
                             configuration=configuration)
            # A factory creates fresh workflow/node instances for each task and is
            # invoked after artifacts exist, so constructor failures are recorded.
            instance = workflow if not inspect.isclass(workflow) and (
                hasattr(workflow, 'root') or callable(getattr(workflow, 'run', None))) else workflow()
            if hasattr(instance, 'root'):
                resolved = instance
                instance = resolved.root
                if hasattr(resolved, 'spec'):
                    configuration['effective_assembly'] = resolved.spec.public_dict()
                    configuration['assembly_sha256'] = hashlib.sha256(json.dumps(
                        configuration['effective_assembly'], sort_keys=True, ensure_ascii=False,
                        separators=(',', ':'), allow_nan=False).encode()).hexdigest()
            initial_state = configuration.get("effective", {}).get("runtime", {}).get("initial_state")
            declare_replay = getattr(instance, 'initial_replay_contract', None)
            if callable(declare_replay):
                contract = declare_replay()
                if not isinstance(contract, InitialReplayContract) or contract.request_policy != 'scheme_a':
                    raise ValueError('workflow declares an unsupported initial replay contract')
                if any(not callable(getattr(node, 'run', None)) or not callable(getattr(node, 'describe', None))
                       for node in (contract.extract_node, *contract.check_nodes)):
                    raise ValueError('initial replay contract requires component bindings')
                ctx.initial_replay_contract = contract
            elif initial_state:
                raise ValueError("workflow does not support initial replay")
            spec = describe_component(instance)
            recorder.record_metadata(mode='agent', task_id=task.id, task=task.public_dict(),
                                     workflow=spec.public_dict(), model=config.public_dict(),
                                     runtime=dict(deadline_s=options.deadline_s, reserve_s=options.reserve_s),
                                     git=git_metadata(str(ROOT)), configuration=configuration,
                                     tools=(self._tool_config or ToolConfig.from_env()).public_dict())
            recorder.record_task(task)
            recorder.write_event('agent', 'start')
            result = instance.run(ctx)
            # Declaring replay support is not enough: a workflow that receives
            # initial_state must actually validate and import that checkpoint.
            if initial_state and not ctx.initial_replay_validated:
                raise ValueError("workflow did not validate the initial checkpoint")
            if not isinstance(result, WorkflowResult):
                raise TypeError('workflow.run() must return ctx.finish() result')
            # The return value must describe the already persisted selection;
            # a workflow cannot select a different answer only in memory.
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
                if ctx is not None:
                    recorder.write_event('tokens', 'final', snapshot=ctx.llm.tokens.snapshot())
                selected = artifacts.selected
                recorder.write_event('agent', 'done', candidate_id=selected.id if selected else None,
                                     code_hash=selected.code_hash if selected else None,
                                     bytes=len(selected.code.encode('utf-8')) if selected else 0,
                                     status=result.status if result else 'error',
                                     stop_reason=result.stop_reason if result else 'recording_error')
            finally:
                recorder.close()
        return result
