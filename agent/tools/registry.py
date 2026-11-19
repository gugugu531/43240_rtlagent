"""Explicit function registration, signature validation and plugin imports."""

from dataclasses import dataclass, field
import hashlib
import importlib.util
import inspect
from pathlib import Path
from typing import Any, get_type_hints

from pydantic import ConfigDict, create_model


@dataclass
class Definition:
    name: str
    fn: object
    reads: list = field(default_factory=list)
    writes: list = field(default_factory=list)
    nodes: dict = field(default_factory=dict)
    tools: dict = field(default_factory=dict)
    params: dict = field(default_factory=dict)
    state: dict = field(default_factory=dict)
    param_model: object = None
    label: str | None = None
    role: str | None = None


NODES, TOOLS, WORKFLOWS = {}, {}, {}


def _register(registry, name, **metadata):
    def decorate(fn):
        if name in registry:
            raise ValueError(f"duplicate registration: {name}")
        registry[name] = Definition(name, fn, **metadata)
        return fn

    return decorate


def node(name, *, reads=(), writes=(), label=None, role=None):
    return _register(NODES, name, reads=list(reads), writes=list(writes), label=label, role=role)


def tool(name):
    return _register(TOOLS, name)


def workflow(
    name, *, nodes=None, tools=None, params=None, state=None, param_model=None
):
    return _register(
        WORKFLOWS,
        name,
        nodes=nodes or {},
        params=params or {},
        tools=tools or {},
        state=state or {},
        param_model=param_model,
    )


def parameter_model(fn, excluded=("ctx", "state")):
    fields = {}
    hints = get_type_hints(fn)
    for name, param in inspect.signature(fn).parameters.items():
        if name in excluded:
            continue
        if param.kind in (
            param.VAR_POSITIONAL,
            param.VAR_KEYWORD,
            param.POSITIONAL_ONLY,
        ):
            raise TypeError(f"{fn.__name__}: named parameters required")
        default = ... if param.default is inspect.Parameter.empty else param.default
        annotation = hints.get(
            name, type(default) if default not in (..., None) else Any
        )
        fields[name] = (annotation, default)
    return create_model(
        fn.__name__ + "Parameters",
        __config__=ConfigDict(
            extra="forbid", arbitrary_types_allowed=True, allow_inf_nan=False
        ),
        **fields,
    )


def parameters(fn, values):
    model = parameter_model(fn).model_validate(values, strict=True)
    return {name: getattr(model, name) for name in type(model).model_fields}


def load_plugins(paths):
    for path in paths:
        source = Path(path).resolve()
        if source.suffix != ".py" or not source.is_file():
            raise ValueError(f"plugin must name an existing Python file: {source}")
        name = "rtl_plugin_" + hashlib.sha256(str(source).encode()).hexdigest()[:16]
        import sys

        if name in sys.modules:
            continue
        spec = importlib.util.spec_from_file_location(name, source)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            sys.modules.pop(name, None)
            raise
