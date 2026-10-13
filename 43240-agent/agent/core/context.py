"""Per-task state and public operations shared by arbitrary Python workflows."""
from __future__ import annotations
from dataclasses import fields, is_dataclass
import hashlib
import time
from types import MappingProxyType
from typing import TypeVar
from agent.recording.artifacts import ArtifactStore
from agent.core.candidate import Candidate, CandidateFactory
from agent.core.budget import Budget
from agent.core.cancellation import CancellationToken
from agent.core.components import Node, ComponentSpec, describe_component
from agent.core.model import ModelReply
from agent.core.state import CheckResult, NodeExecution, RunStateView, SelectionDecision, WorkflowResult
from agent.core.task import TaskSpec
from agent.recording.recorder import RunRecorder
from agent.services.model import ModelService
from agent.services.tools import ToolService
from agent.services.vivado import RtlToolchain

I = TypeVar('I')
O = TypeVar('O')


def summarize(value):
    """Keep bodies out of node events; objects with their own events appear by ID only."""
    if isinstance(value, Candidate):
        return dict(candidate_id=value.id)
    if isinstance(value, ModelReply):
        return dict(call_id=value.call_id)
    if isinstance(value, CheckResult):
        return dict(check_id=value.id, status=value.status)
    if isinstance(value, TaskSpec):
        return dict(task_id=value.id)
    if callable(getattr(value, 'summary_dict', None)):
        return value.summary_dict()
    if isinstance(value, ComponentSpec):
        return value.public_dict()
    if callable(getattr(value, 'trace_dict', None)):
        return value.trace_dict()
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if len(value) <= 80 and '\n' not in value:
            return value
        return dict(bytes=len(value.encode('utf-8')), sha256=hashlib.sha256(value.encode('utf-8')).hexdigest())
    if is_dataclass(value):
        return {f.name: summarize(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, (list, tuple)):
        return [summarize(item) for item in value]
    if isinstance(value, dict):
        return {str(k): summarize(v) for k, v in value.items()}
    return dict(type=type(value).__qualname__, status='unknown')


class RunContext:
    def __init__(self, task: TaskSpec, llm: ModelService, budget: Budget,
                 artifacts: ArtifactStore, recorder: RunRecorder, *,
                 toolchain_factory=RtlToolchain, process_executor=None):
        self.task, self.llm, self.budget = task, llm, budget
        self.started_at = time.monotonic()
        self.cancellation = CancellationToken()
        self._artifacts, self._recorder = artifacts, recorder
        self._candidates: dict[str, Candidate] = {}
        self._checks: list[CheckResult] = []
        self._executions: list[NodeExecution] = []
        self._stack: list[str] = []
        self._check_sequence = 0
        self._stop_reason = None
        self._selection_reason = None
        self._candidate_factory = CandidateFactory()
        from agent.services.processes import ProcessService, ProcessExecutor
        self.processes = ProcessService(budget, process_executor or ProcessExecutor(), self.cancellation,
            lambda event, **fields: recorder.write_event('process', event, **fields))
        self.tools = ToolService(budget, self.new_check_id, self.record_check,
                                 toolchain_factory=toolchain_factory, task=task, emit=self.emit)

    @property
    def state(self) -> RunStateView:
        return RunStateView(MappingProxyType(dict(self._candidates)), tuple(self._checks),
                            tuple(self._executions),
                            self._artifacts.selected.id if self._artifacts.selected else None,
                            self._stop_reason)

    def execute(self, node: Node[I, O], input: I) -> O:
        self.cancellation.raise_if_cancelled()
        spec = describe_component(node)
        if not isinstance(spec, ComponentSpec):
            raise TypeError('node.describe() must return ComponentSpec')
        execution_id = f'e{len(self._executions) + 1:03d}'
        parent = self._stack[-1] if self._stack else None
        index = len(self._executions)
        start = time.monotonic()
        inputs = summarize(input)
        self._executions.append(NodeExecution(execution_id, parent, spec.public_dict(), 'started', 0.0, inputs))
        self._stack.append(execution_id)
        try:
            with self._recorder.execution_scope(execution_id):
                self._recorder.record_node(self._executions[index])
                try:
                    output = node.run(self, input)
                except BaseException as exc:
                    execution = NodeExecution(execution_id, parent, spec.public_dict(), 'failed',
                                              time.monotonic() - start, inputs, error_type=type(exc).__name__,
                                              error_message=str(exc)[:2000])
                    self._executions[index] = execution
                    self._recorder.record_node(execution)
                    raise
                execution = NodeExecution(execution_id, parent, spec.public_dict(), 'succeeded',
                                          time.monotonic() - start, inputs, summarize(output))
                self._executions[index] = execution
                self._recorder.record_node(execution)
                return output
        finally:
            self._stack.pop()

    def create_candidate(self, code: str, *, reply: ModelReply, round: int,
                         parent_id: str | None = None, source_stage: str = 'generate',
                         extraction_status: str = 'complete') -> Candidate:
        candidate = self._candidate_factory.create(
            code, source_stage=source_stage, round=round, parent_id=parent_id,
            finish_reason=reply.finish_reason, extraction_status=extraction_status,
            source_call_id=reply.call_id)
        self.register_candidate(candidate)
        return candidate

    def register_candidate(self, candidate: Candidate) -> None:
        if candidate.id in self._candidates:
            raise ValueError(f'duplicate candidate: {candidate.id}')
        if candidate.parent_id and candidate.parent_id not in self._candidates:
            raise ValueError('candidate parent is not registered')
        self._candidates[candidate.id] = candidate
        self._recorder.record_candidate(candidate)

    def record_extraction(self, call_id, extraction, candidate_id=None) -> None:
        self._recorder.record_extraction(call_id, extraction, candidate_id)

    def new_check_id(self) -> str:
        self._check_sequence += 1
        return f'k{self._check_sequence:03d}'

    def record_check(self, result: CheckResult) -> None:
        if result.candidate_id not in self._candidates:
            raise ValueError('check candidate is not registered')
        if any(check.id == result.id for check in self._checks):
            raise ValueError(f'duplicate check: {result.id}')
        self._checks.append(result)
        self._recorder.record_check(result)
        from agent.core.diagnostic import diagnostics_from_check
        for diagnostic in diagnostics_from_check(result, candidate_code=self._candidates[result.candidate_id].code):
            self._recorder.write_event('diagnostic', 'parsed', diagnostic=diagnostic.public_dict())

    def select_candidate(self, candidate_id: str, *, reason: str) -> None:
        candidate = self._candidates[candidate_id]
        self._artifacts.select(candidate, reason=reason)
        self._selection_reason = reason
        self._recorder.record_selection(candidate, reason=reason)

    def apply_selection(self, decision: SelectionDecision) -> None:
        self.emit('selection_decision', candidate_id=decision.candidate_id,
                  changed=decision.changed, reason=decision.reason,
                  evidence_ids=decision.evidence_ids)
        if decision.changed or (decision.candidate_id and decision.reason != self._selection_reason):
            if decision.candidate_id is None:
                self._artifacts.clear_selection(reason=decision.reason)
                self._selection_reason = None
                self.emit('selection_cleared', reason=decision.reason)
            else:
                self.select_candidate(decision.candidate_id, reason=decision.reason)

    def emit(self, event: str, **fields) -> None:
        self._recorder.write_event('workflow', event, **fields)

    @property
    def output_dir(self):
        return self._artifacts.output_dir

    def finish(self, *, reason: str, status='completed') -> WorkflowResult:
        if not reason or status not in ('completed', 'stopped', 'error'):
            raise ValueError('invalid workflow finish reason or status')
        self._stop_reason = reason
        return WorkflowResult(self._recorder.run_id, self._artifacts.selected, reason, status)
