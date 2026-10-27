"""Bounded model tool loop shared by stages.

The graph still owns transitions. This helper only lets one stage alternate
between model replies and whitelisted tools, and it always stops on a fixed
step budget. Each model call is the caller's responsibility, so completion
ledgers and permits stay in the stage that owns them.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
import json

from agent.llm.types import ModelError


@dataclass(frozen=True)
class ToolStep:
    step: int
    call_id: str
    name: str
    arguments: dict
    result: dict

    def public_dict(self):
        return {
            "step": self.step,
            "call_id": self.call_id,
            "name": self.name,
            "arguments": self.arguments,
            "result": self.result,
        }


@dataclass(frozen=True)
class LoopResult:
    reply: object
    steps: tuple[ToolStep, ...]
    stopped_reason: str  # replied / finish_tool / step_limit


def run_tool_loop(
    *,
    chat,
    dispatch,
    messages,
    tools,
    max_steps,
    finish_tool="finish_task",
):
    """Run at most `max_steps` model completions with a fixed tool whitelist."""
    if type(max_steps) is not int or max_steps < 1:
        raise ValueError("max_steps must be a positive integer")
    allowed = {tool["function"]["name"] for tool in tools}
    conversation = copy.deepcopy(messages)
    steps = []
    reply = None
    for index in range(max_steps):
        reply = chat(conversation, tools=tools)
        calls = list(getattr(reply, "tool_calls", ()) or ())
        if not calls:
            return LoopResult(reply, tuple(steps), "replied")
        conversation.append(
            {
                "role": "assistant",
                "content": getattr(reply, "content", "") or None,
                "tool_calls": calls,
            }
        )
        finished = False
        for call in calls:
            try:
                function = call["function"]
                call_id = call["id"]
                name = function["name"]
                arguments = json.loads(function["arguments"])
            except (KeyError, TypeError, ValueError) as error:
                raise ModelError(
                    "invalid tool call", kind="tool_call",
                    call_id=getattr(reply, "call_id", None),
                ) from error
            if (
                name not in allowed
                or not isinstance(call_id, str)
                or not isinstance(arguments, dict)
            ):
                raise ModelError(
                    "unknown tool or invalid arguments", kind="tool_call",
                    call_id=getattr(reply, "call_id", None),
                )
            result = dispatch(name, arguments)
            conversation.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )
            steps.append(ToolStep(index, call_id, name, arguments, result))
            if name == finish_tool:
                finished = True
        if finished:
            return LoopResult(reply, tuple(steps), "finish_tool")
    # The budget is a hard stop; the caller must not silently add another call.
    return LoopResult(reply, tuple(steps), "step_limit")
