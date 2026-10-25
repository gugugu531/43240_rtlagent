"""Bind registered functions into Burr and record every action through hooks."""

import json
import time
from types import SimpleNamespace
import uuid
from burr.core import ApplicationBuilder, State, action
from burr.lifecycle.base import PreRunStepHook, PostRunStepHook
from agent.runtime.recorder import _span
from agent.runtime.registry import NODES, TOOLS, WORKFLOWS, parameters, parameter_model


def bind_node(definition, ctx, params):
    # Burr passes State positionally; the public API keeps ctx before state.
    def invoke(state: State, ctx, params) -> State:
        return definition.fn(ctx, state, **params)

    return action(reads=definition.reads, writes=definition.writes)(invoke).bind(
        ctx=ctx, params=params
    )


class NodeRecorder(PreRunStepHook, PostRunStepHook):
    def __init__(self, ctx, definitions):
        self.ctx, self.definitions = ctx, definitions
        self.started = {}

    def pre_run_step(self, *, action, state, sequence_id, **kwargs):
        parent = _span.get()
        token = _span.set((uuid.uuid4().hex, parent[0] if parent else None))
        self.started[sequence_id] = (time.monotonic(), token)
        self.ctx.record.emit(
            "node",
            "started",
            name=action.name,
            implementation=self.definitions[action.name]["use"],
            params=self.definitions[action.name]["params"],
            state=state.get_all(),
        )

    def post_run_step(self, *, action, state, sequence_id, exception, **kwargs):
        start, token = self.started.pop(sequence_id)
        try:
            json.dumps(state.get_all(), allow_nan=False)
            self.ctx.record.emit(
                "node",
                "failed" if exception else "finished",
                name=action.name,
                state=state.get_all(),
                elapsed_s=time.monotonic() - start,
                error=str(exception) if exception else None,
            )
        finally:
            _span.reset(token)


def build_graph(ctx):
    config = ctx.config
    if config.workflow not in WORKFLOWS:
        raise ValueError(f"unknown workflow: {config.workflow}")
    workflow = WORKFLOWS[config.workflow]
    from agent.config import Component

    ctx.tools = {
        name: Component.model_validate(
            value if isinstance(value, dict) else {"use": value}
        )
        for name, value in workflow.tools.items()
    }
    ctx.tools.update(config.tools)
    from pydantic import TypeAdapter

    for name, selected in ctx.tools.items():
        if selected.use not in TOOLS:
            raise ValueError(f"unknown tool: {selected.use}")
        fields = parameter_model(TOOLS[selected.use].fn).model_fields
        for key, value in selected.params.items():
            if key not in fields:
                raise ValueError(f"unknown parameter {key!r} for tool {name!r}")
            TypeAdapter(fields[key].rebuild_annotation()).validate_python(
                value, strict=True
            )
    definitions = {
        k: dict(v) if isinstance(v, dict) else {"use": v}
        for k, v in workflow.nodes.items()
    }
    for name, selected in config.nodes.items():
        if name not in definitions:
            raise ValueError(f"unknown workflow node alias: {name}")
        definitions[name] = selected.model_dump()
    actions = {}
    for name, selected in definitions.items():
        if selected["use"] not in NODES:
            raise ValueError(f"unknown node: {selected['use']}")
        definition = NODES[selected["use"]]
        params = parameters(definition.fn, selected.get("params", {}))
        if selected['use'] == 'rtl_generate':
            from agent.knowledge.policy import validate_selection
            validate_selection(params)
        selected["params"] = params
        actions[name] = bind_node(definition, ctx, params)
    values = dict(workflow.params)
    unknown = set(config.params) - set(values)
    if unknown and workflow.param_model is None:
        raise ValueError(f"unknown workflow parameters: {sorted(unknown)}")
    values.update(config.params)
    p = (
        workflow.param_model.model_validate(values)
        if workflow.param_model
        else SimpleNamespace(**values)
    )
    builder = ApplicationBuilder().with_actions(**actions).with_state(**workflow.state)
    builder = workflow.fn(builder, p)
    builder = builder.with_hooks(NodeRecorder(ctx, definitions)).with_identifiers(
        app_id=ctx.record.run_id
    )
    if config.runtime.recording.burr_tracker:
        if config.runtime.recording.level != "full":
            raise ValueError("Burr tracker requires full recording")
        builder = builder.with_tracker(
            "local",
            project="rtl",
            params={"storage_dir": str(ctx.record.record_dir / "burr")},
        )
    app = builder.build()
    for graph_action in app.graph.actions:
        definitions[graph_action.name].update(
            reads=list(graph_action.reads), writes=list(graph_action.writes)
        )
    ctx.record.emit(
        "run",
        "graph",
        graph_schema_version=1,
        workflow=config.workflow,
        entrypoint=app.graph.entrypoint.name,
        nodes=definitions,
        transitions=[
            {
                "from": transition.from_.name,
                "to": transition.to.name,
                "condition": transition.condition.name,
            }
            for transition in app.graph.transitions
        ],
        params=values,
        tools={name: item.model_dump() for name, item in ctx.tools.items()},
    )
    return app


def run_graph(ctx):
    app = build_graph(ctx)
    for _ in range(ctx.config.runtime.max_steps):
        ctx.budget.timeout(ctx.budget.deadline_s)
        outcome = app.step()
        if outcome is None:
            return app.state
        action_, _, state = outcome
        if action_.name == "finish":
            return state
    return app.state.update(stop_reason="max_steps", status="stopped")
