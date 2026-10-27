"""Task-local services; the runtime does not import RTL domain code."""

import dataclasses
import hashlib
import inspect
import json
from agent.runtime.registry import TOOLS, parameter_model, parameters
from agent.runtime.recorder import serializable
from agent.runtime.tool_result import ToolResult


def summarize(value):
    if hasattr(value, "public_dict"):
        return value.public_dict()
    if dataclasses.is_dataclass(value):
        return summarize(dataclasses.asdict(value))
    if isinstance(value, dict):
        return {str(k): summarize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [summarize(v) for v in value]
    if isinstance(value, str) and (len(value) > 200 or "\n" in value):
        return dict(
            bytes=len(value.encode()), sha256=hashlib.sha256(value.encode()).hexdigest()
        )
    return value


class Ctx:
    def __init__(
        self, *, task, budget, llm, record, processes, candidates, prompts, config
    ):
        self.task, self.budget, self.llm = task, budget, llm
        self.record, self.processes, self.candidates = record, processes, candidates
        self.prompts, self.config, self.store = prompts, config, {}
        self.tools = dict(config.tools)
        self.output_dir = record.output_dir

    def call(self, tool_name, *args, **kwargs):
        selected = self.tools.get(tool_name)
        implementation = selected.use if selected else tool_name
        if implementation not in TOOLS:
            raise ValueError(f"unknown tool: {implementation}")
        definition = TOOLS[implementation]
        bound = inspect.signature(definition.fn).bind_partial(self, *args, **kwargs)
        values = dict(selected.params) if selected else {}
        values.update({k: v for k, v in bound.arguments.items() if k != "ctx"})
        values = parameters(definition.fn, values)
        self.budget.timeout(self.budget.deadline_s)
        with self.record.span(
            "tool",
            name=tool_name,
            implementation=implementation,
            input=summarize(values),
        ):
            result = definition.fn(self, **values)
            self.record.emit(
                tool_name,
                "result",
                output=summarize(result),
                rc=getattr(result, "rc", None),
                status=getattr(result, "status", None),
                failure_kind=getattr(result, "failure_kind", None),
                excerpt=getattr(result, "summary", ""),
            )
            return result

    def dispatch(self, name, arguments):
        """Model-facing tool entry: bounded envelope, JSON-normalized for transport."""
        result = self.call(name, **arguments)
        if isinstance(result, ToolResult):
            envelope = result
        elif hasattr(result, "status") and hasattr(result, "summary"):
            envelope = ToolResult.from_check_result(result, tool=name)
        else:
            envelope = ToolResult.from_value(result, tool=name)
        # Host-only meta can contain Path/dataclass/tuple, so normalize here
        # before the model loop serializes the result into a tool message.
        return json.loads(json.dumps(envelope.to_model_dict(), default=serializable))

    def tool_schema(self, name):
        selected = self.tools.get(name)
        implementation = selected.use if selected else name
        definition = TOOLS[implementation]
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": definition.fn.__doc__ or implementation,
                "parameters": parameter_model(definition.fn).model_json_schema(),
            },
        }
