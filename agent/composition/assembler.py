"""Resolve only requested local classes and construct one isolated object graph."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import importlib
import inspect
from pathlib import Path
from types import MappingProxyType
import types
import typing

from agent.core.assembly import AssemblySpec
from agent.core.components import ComponentSpec, Workflow, Node, Tool, describe_value
from agent.composition.validation import ConfigError, ROLE_PACKAGES, references, validate_assembly


@dataclass(frozen=True)
class ResolvedAssembly:
    root: object
    components: Mapping[str, object]
    spec: AssemblySpec


def _local_class(target, kind):
    module_name, name = target.split(':')
    package = Path(__file__).resolve().parents[1]
    relative = module_name.split('.')[1:]
    candidate = package.joinpath(*relative)
    path = candidate.with_suffix('.py')
    if not path.is_file():
        path = candidate / '__init__.py'
    if not path.is_file() or not path.resolve().is_relative_to(package / ROLE_PACKAGES[kind].split('.')[-1]):
        raise ConfigError('component module is absent from the local submission package')
    for parent in (package, *candidate.parents):
        if parent == package.parent:
            break
        if parent.is_relative_to(package) and parent.is_symlink():
            raise ConfigError('component module must not use symlink directories')
    if path.is_symlink():
        raise ConfigError('component module must not be a symlink')
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:
        raise ConfigError(f'cannot import component module ({type(exc).__name__})') from None
    module_file = getattr(module, '__file__', None)
    if module_file is None or Path(module_file).resolve() != path.resolve():
        raise ConfigError('component import resolved outside its expected local file')
    cls = getattr(module, name, None)
    if not inspect.isclass(cls) or cls.__module__ != module_name or getattr(cls, 'kind', None) != kind:
        raise ConfigError('component class has the wrong module or kind')
    role = {'workflow': Workflow, 'node': Node, 'tool': Tool}[kind]
    if not issubclass(cls, role):
        raise ConfigError('component class must inherit its declared component role')
    if not all(callable(getattr(cls, method, None)) for method in ('run', 'describe')):
        raise ConfigError('component class requires run and describe')
    if cls.run is role.run:
        raise ConfigError('component class must implement run')
    if inspect.isabstract(cls):
        raise ConfigError('component class must implement all abstract methods')
    for field in ('input_type', 'output_type'):
        if getattr(cls, field, None) is None:
            raise ConfigError('component class must declare input_type and output_type')
    return cls


def _matches_type(value, annotation):
    if annotation in (inspect.Parameter.empty, typing.Any, object):
        return True
    origin, args = typing.get_origin(annotation), typing.get_args(annotation)
    if origin in (typing.Union, types.UnionType):
        return any(_matches_type(value, item) for item in args)
    if annotation is None or annotation is type(None):
        return value is None
    if origin in (list, tuple, Sequence):
        if not isinstance(value, origin) or isinstance(value, (str, bytes)):
            return False
        if origin is tuple and args and args[-1] is not Ellipsis:
            return len(value) == len(args) and all(_matches_type(v, t) for v, t in zip(value, args))
        return not args or all(_matches_type(item, args[0]) for item in value)
    if origin in (dict, Mapping):
        return isinstance(value, Mapping) and (not args or all(_matches_type(k, args[0]) and _matches_type(v, args[1]) for k, v in value.items()))
    if annotation is float:
        return type(value) in (int, float)
    if annotation is int:
        return type(value) is int
    if annotation is bool:
        return type(value) is bool
    if origin is typing.Literal:
        return any(type(value) is type(item) and value == item for item in args)
    if inspect.isclass(annotation):
        if getattr(annotation, '_is_protocol', False):
            raise ConfigError('protocol parameter types must use an explicit dependency slot')
        return isinstance(value, annotation)
    raise ConfigError('unsupported explicit component parameter type')


def _dependency_annotation(annotation):
    origin, args = typing.get_origin(annotation), typing.get_args(annotation)
    if origin in (typing.Union, types.UnionType):
        alternatives = [item for item in args if item is not type(None)]
        if len(alternatives) == 1:
            return _dependency_annotation(alternatives[0])
    if origin in (list, tuple, Sequence):
        return True, _dependency_annotation(args[0])[1] if args else None
    if origin in (Node, Tool) and len(args) == 2:
        return False, args
    return False, None


def _compatible(actual, expected):
    if expected in (typing.Any, object) or actual == expected:
        return True
    try:
        return inspect.isclass(actual) and inspect.isclass(expected) and issubclass(actual, expected)
    except TypeError:
        return False


def assemble(spec: AssemblySpec) -> ResolvedAssembly:
    data = spec.public_dict()
    validate_assembly(data)
    configs = {row['id']: row for row in data['components']}
    classes = {}
    for key, row in configs.items():
        try:
            classes[key] = _local_class(row['target'], row['kind'])
        except ConfigError as exc:
            raise ConfigError(f'{key}: {exc}') from None
    effective = []
    # Validate the whole graph before constructing its first instance.
    for key, row in configs.items():
        cls = classes[key]
        dependencies = getattr(cls, 'dependencies', {})
        if not isinstance(dependencies, Mapping) or set(row.get('inject', {})) - set(dependencies):
            raise ConfigError(f'{key}: unknown component dependency slot')
        params, inject = row.get('params', {}), row.get('inject', {})
        try:
            signature = inspect.signature(cls)
            if any(name not in signature.parameters for name in (*params, *inject)):
                raise TypeError('unknown constructor parameter')
            bound = signature.bind(**params, **{slot: None for slot in inject})
            bound.apply_defaults()
            hints = typing.get_type_hints(cls.__init__)
        except Exception as exc:
            raise ConfigError(f'{key}: invalid component constructor ({type(exc).__name__})') from None
        if params.keys() & dependencies.keys():
            raise ConfigError(f'{key}: dependency slots must be supplied through inject')
        for slot in dependencies:
            if slot not in inject and bound.arguments.get(slot) is not None:
                raise ConfigError(f'{key}.{slot}: omitted dependency must default to None')
        for name, value in params.items():
            if not _matches_type(value, hints.get(name, inspect.Parameter.empty)):
                raise ConfigError(f'{key}.{name}: component parameter has the wrong type')
        for slot, reference in inject.items():
            expected_kind = dependencies[slot]
            refs = reference if isinstance(reference, list) else [reference]
            for ref in refs:
                if configs[ref]['kind'] != expected_kind:
                    raise ConfigError(f'{key}.{slot}: injected component has the wrong kind')
            hint = hints.get(slot)
            is_list, annotated_types = _dependency_annotation(hint)
            if hint is not None and isinstance(reference, list) != is_list:
                # Optional/protocol slots are scalar; list slots must be explicit.
                raise ConfigError(f'{key}.{slot}: dependency scalar/list shape differs from its constructor type')
            # Slots may declare stronger I/O contracts without generic reflection.
            slot_types = getattr(cls, 'dependency_types', {}).get(slot) or annotated_types
            if not slot_types:
                raise ConfigError(f'{key}.{slot}: dependency input/output contract must be declared')
            if slot_types:
                expected_input, expected_output = slot_types
                if any(not _compatible(expected_input, classes[ref].input_type) or
                       not _compatible(classes[ref].output_type, expected_output) for ref in refs):
                    raise ConfigError(f'{key}.{slot}: injected component input/output contract differs')
        ordinary = {name: value for name, value in bound.arguments.items() if name not in dependencies}
        effective.append(dict(row, params=describe_value(ordinary)))
    instances = {}

    def build(identity):
        if identity in instances:
            return instances[identity]
        row, cls = configs[identity], classes[identity]
        arguments = dict(row.get('params', {}))
        arguments.update({slot: [build(ref) for ref in value] if isinstance(value, list) else build(value)
                          for slot, value in row.get('inject', {}).items()})
        try:
            bound = inspect.signature(cls).bind(**arguments)
            bound.apply_defaults()
            instance = cls(**arguments)
        except Exception as exc:
            raise ConfigError(f'{identity}: cannot construct component ({type(exc).__name__})') from None
        ordinary = {name: value for name, value in bound.arguments.items() if name not in getattr(cls, 'dependencies', {})}
        metadata = ComponentSpec(getattr(cls, 'component_name', cls.__name__), cls.__module__, cls.__qualname__,
                                 describe_value(ordinary), row.get('inject', {}),
                                 instance_id=identity, kind=row['kind'])
        try:
            object.__setattr__(instance, '_construction_spec', metadata)
        except (AttributeError, TypeError):
            pass
        if not isinstance(instance.describe(), ComponentSpec):
            raise ConfigError('component describe must return ComponentSpec')
        instances[identity] = instance
        return instance

    root = build(data['root_id'])
    return ResolvedAssembly(root, MappingProxyType(instances),
                            AssemblySpec.from_dict(dict(root_id=data['root_id'], components=effective)))
