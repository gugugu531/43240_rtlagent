"""Registries contain classes, never mutable per-task instances."""
from __future__ import annotations
from collections.abc import Callable, Sequence
import importlib
import inspect
import re
from typing import Generic, TypeVar
from agent.core.components import Component, ComponentSpec, Node, Workflow, describe_value

T = TypeVar('T')


class Registry(Generic[T]):
    def __init__(self, kind: str):
        self.kind = kind
        self._classes: dict[str, type[T]] = {}

    def register(self, name: str) -> Callable[[type[T]], type[T]]:
        if not re.fullmatch(r'[a-z][a-z0-9_-]*', name):
            raise ValueError('component names must use lowercase letters, digits, underscores or hyphens')
        def register_class(cls: type[T]) -> type[T]:
            if name in self._classes:
                raise ValueError(f'duplicate {self.kind}: {name}')
            if not inspect.isclass(cls) or not all(callable(getattr(cls, method, None))
                                                 for method in ('run', 'describe')):
                raise TypeError(f'{self.kind} must be a class with run() and describe()')
            self._classes[name] = cls
            if issubclass(cls, Component):
                cls._registration_name = name
            return cls
        return register_class

    def get(self, name: str) -> type[T]:
        try:
            return self._classes[name]
        except KeyError:
            raise KeyError(f'unknown {self.kind}: {name}; available: {", ".join(self.names())}') from None

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._classes))

    def build(self, name: str, **params) -> T:
        cls = self.get(name)
        try:
            arguments = inspect.signature(cls).bind(**params)
            arguments.apply_defaults()
            instance = cls(**params)
        except Exception as exc:
            # Values and exception strings may contain secrets.
            raise ValueError(f'cannot construct {self.kind} {name} ({type(exc).__name__}); '
                             f'parameter names: {", ".join(sorted(params))}') from exc
        spec = ComponentSpec(name, cls.__module__, cls.__qualname__, describe_value(arguments.arguments))
        try:
            object.__setattr__(instance, '_construction_spec', spec)
        except AttributeError:
            pass  # Components with slots provide equivalent metadata in describe().
        if not isinstance(instance.describe(), ComponentSpec):
            raise TypeError(f'{self.kind} {name}.describe() must return ComponentSpec')
        return instance


NODE_REGISTRY: Registry[Node] = Registry('node')
WORKFLOW_REGISTRY: Registry[Workflow] = Registry('workflow')


def load_extensions(module_names: Sequence[str]) -> None:
    for name in module_names:
        importlib.import_module(name)


def load_builtin_components() -> None:
    load_extensions(('agent.nodes.generate', 'agent.nodes.extract', 'agent.nodes.check', 'agent.nodes.feedback',
                     'agent.nodes.baseline', 'agent.workflows.single_generate',
                     'agent.workflows.repair_loop', 'agent.workflows.evidence_repair',
                     'agent.nodes.guidance', 'agent.workflows.evidence_ablation',
                     'agent.workflows.search_ablation', 'agent.workflows.spec_repair'))


def build_node(name: str, **params) -> Node:
    load_builtin_components()
    return NODE_REGISTRY.build(name, **params)


def build_workflow(name: str, **params) -> Workflow:
    load_builtin_components()
    return WORKFLOW_REGISTRY.build(name, **params)
