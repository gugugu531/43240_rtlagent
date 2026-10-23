"""Public component contracts and serializable construction metadata."""
from __future__ import annotations
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
import inspect
from pathlib import Path
from typing import Any, Generic, Protocol, TypeVar, ClassVar
from agent.core.model import _freeze, _thaw

from agent.core.task import TaskSpec
from agent.core.budget import Budget
from agent.core.candidate import Candidate
from agent.core.state import CheckResult, RunStateView, WorkflowResult
from agent.core.process import ProcessRequest, ProcessResult

InputT = TypeVar('InputT', contravariant=True)
OutputT = TypeVar('OutputT', covariant=True)


def describe_value(value: Any) -> Any:
    """Do not stringify arbitrary objects: repr() can contain credentials."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(k): describe_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [describe_value(v) for v in value]
    if isinstance(value, ComponentSpec):
        return value.public_dict()
    if callable(getattr(value, 'describe', None)):
        return describe_value(value.describe())
    return {'status': 'unknown', 'type': type(value).__qualname__}


@dataclass(frozen=True)
class ComponentSpec:
    name: str
    module: str
    implementation: str
    parameters: Mapping[str, Any]
    dependencies: Mapping[str, str | tuple[str, ...]] = field(default_factory=dict)
    instance_id: str | None = None
    kind: str = "component"

    def __post_init__(self):
        object.__setattr__(self, 'parameters', _freeze(describe_value(self.parameters)))
        object.__setattr__(self, 'dependencies', _freeze(dict(self.dependencies)))

    def public_dict(self) -> dict[str, Any]:
        return dict(name=self.name, module=self.module, implementation=self.implementation,
                    parameters=_thaw(self.parameters), dependencies=_thaw(self.dependencies),
                    instance_id=self.instance_id, kind=self.kind)


class Component:
    """Construction metadata and explicit dependency declarations."""
    kind: ClassVar[str] = "component"
    input_type: ClassVar[type] = object
    output_type: ClassVar[type] = object
    dependencies: ClassVar[Mapping[str, str]] = {}
    # Literal metadata is read through AST before importing a named component.
    assembly_roles: ClassVar[list[str]] = []
    assembly_defaults: ClassVar[Mapping[str, Any]] = {}
    def describe(self) -> ComponentSpec:
        captured = getattr(self, '_construction_spec', None)
        if captured is not None:
            return captured
        cls = type(self)
        parameters = {}
        dependencies = {}
        for name, parameter in inspect.signature(cls).parameters.items():
            if name in self.dependencies:
                dependency = getattr(self, name, None)
                def identity(value):
                    return f'{type(value).__module__}:{type(value).__qualname__}'
                dependencies[name] = ([identity(item) for item in dependency]
                                      if isinstance(dependency, (list, tuple)) else identity(dependency))
                continue
            if parameter.kind in (parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD):
                parameters[name] = {'status': 'unknown'}
            else:
                parameters[name] = describe_value(getattr(self, name, {'status': 'unknown'}))
        return ComponentSpec(getattr(cls, "component_name", cls.__name__),
                             cls.__module__, cls.__qualname__, parameters, dependencies, kind=self.kind)


class ProcessContext(Protocol):
    def run(self, request: ProcessRequest) -> ProcessResult: ...


class ArtifactContext(Protocol):
    def write_text(self, name: str, content: str) -> Path: ...
    def write_json(self, name: str, content: Any) -> Path: ...


class ToolContext(Protocol):
    task: TaskSpec
    budget: Budget
    processes: ProcessContext
    artifacts: ArtifactContext
    timeout_s: float | None

    def emit(self, event: str, **fields) -> None: ...
    def toolchain(self) -> Any: ...
    def with_timeout(self, timeout_s: float | None) -> ToolContext: ...


class RunContext(Protocol):
    task: TaskSpec
    budget: Budget
    llm: Any
    state: RunStateView
    checks: Any
    processes: ProcessContext
    started_at: float
    configuration: dict
    output_dir: Path

    def execute(self, node: Node[InputT, OutputT], input: InputT) -> OutputT: ...
    def call(self, tool: Tool[InputT, OutputT], input: InputT, *, timeout_s: float | None = None) -> OutputT: ...
    def check(self, tool: Tool, input: Any, *, candidate: Candidate,
              timeout_s: float | None, minimum_s: float = 0.0) -> CheckResult: ...
    def create_candidate(self, code: str, *, reply: Any, round: int,
                         parent_id: str | None = None, source_stage: str = 'generate',
                         extraction_status: str = 'complete') -> Candidate: ...
    def register_candidate(self, candidate: Candidate) -> None: ...
    def record_extraction(self, call_id, extraction, candidate_id=None) -> None: ...
    def new_check_id(self) -> str: ...
    def record_check(self, result: CheckResult) -> None: ...
    def select_candidate(self, candidate_id: str, *, reason: str) -> None: ...
    def apply_selection(self, decision: Any) -> None: ...
    def emit(self, event: str, **fields) -> None: ...
    def finish(self, *, reason: str, status: str = 'completed') -> WorkflowResult: ...


class Node(Component, ABC, Generic[InputT, OutputT]):
    kind = 'node'

    @abstractmethod
    def run(self, ctx: RunContext, input: InputT) -> OutputT:
        raise NotImplementedError


class Workflow(Component, ABC):
    kind = 'workflow'

    @abstractmethod
    def run(self, ctx: RunContext) -> WorkflowResult:
        raise NotImplementedError


class Tool(Component, ABC, Generic[InputT, OutputT]):
    kind = 'tool'

    @abstractmethod
    def run(self, ctx: ToolContext, input: InputT) -> OutputT:
        raise NotImplementedError


def describe_component(component) -> ComponentSpec:
    spec = getattr(component, '_construction_spec', None) or component.describe()
    if not isinstance(spec, ComponentSpec):
        raise TypeError('component.describe() must return ComponentSpec')
    return spec
