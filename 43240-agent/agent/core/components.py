"""Public component contracts and serializable construction metadata."""
from __future__ import annotations
from collections.abc import Mapping
from dataclasses import dataclass
import inspect
from pathlib import Path
from typing import Any, Protocol, TYPE_CHECKING, TypeVar
from .model import _freeze, _thaw

if TYPE_CHECKING:
    from ..context import RunContext
    from .state import WorkflowResult

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

    def __post_init__(self):
        object.__setattr__(self, 'parameters', _freeze(describe_value(self.parameters)))

    def public_dict(self) -> dict[str, Any]:
        return dict(name=self.name, module=self.module, implementation=self.implementation,
                    parameters=_thaw(self.parameters))


class Component:
    """Optional base for components using ordinary constructor parameters."""
    def describe(self) -> ComponentSpec:
        captured = getattr(self, '_construction_spec', None)
        if captured is not None:
            return captured
        cls = type(self)
        parameters = {}
        for name, parameter in inspect.signature(cls).parameters.items():
            if parameter.kind in (parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD):
                parameters[name] = {'status': 'unknown'}
            else:
                parameters[name] = describe_value(getattr(self, name, {'status': 'unknown'}))
        return ComponentSpec(cls.__dict__.get('_registration_name', cls.__name__),
                             cls.__module__, cls.__qualname__, parameters)


class Node(Protocol[InputT, OutputT]):
    def run(self, ctx: RunContext, input: InputT) -> OutputT: ...
    def describe(self) -> ComponentSpec: ...


class Workflow(Protocol):
    def run(self, ctx: RunContext) -> WorkflowResult: ...
    def describe(self) -> ComponentSpec: ...


def describe_component(component) -> ComponentSpec:
    spec = getattr(component, '_construction_spec', None) or component.describe()
    if not isinstance(spec, ComponentSpec):
        raise TypeError('component.describe() must return ComponentSpec')
    return spec
