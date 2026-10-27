"""Bounded model tool loop: dispatch, stop reasons, and invalid calls."""

import json
import unittest

from agent.llm.types import ModelError, Reply
from agent.orchestration.agent_loop import run_tool_loop


def reply(*calls, content=""):
    return Reply(
        call_id="c1",
        content=content,
        finish_reason="tool_calls" if calls else "stop",
        tokens_in=10,
        tokens_out=5,
        tool_calls=list(calls),
    )


def call(name, arguments, call_id="t1"):
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


TOOLS = [
    {"type": "function", "function": {"name": "probe", "parameters": {}}},
    {"type": "function", "function": {"name": "finish_task", "parameters": {}}},
]


class AgentLoopTests(unittest.TestCase):
    def test_no_tool_calls_returns_reply(self):
        seen = []

        def chat(messages, tools):
            seen.append(list(messages))
            return reply(content="done")

        result = run_tool_loop(
            chat=chat, dispatch=lambda n, a: {}, messages=[{"role": "user", "content": "x"}],
            tools=TOOLS, max_steps=3,
        )
        self.assertEqual(result.stopped_reason, "replied")
        self.assertEqual(result.reply.content, "done")
        self.assertEqual(result.steps, ())
        self.assertEqual(len(seen), 1)

    def test_tool_results_are_appended_and_finish_stops(self):
        dispatched = []
        calls = []

        def chat(messages, tools):
            calls.append(len(messages))
            return reply(call("finish_task", {"reason": "done"}, call_id="t9"))

        def dispatch(name, arguments):
            dispatched.append((name, arguments))
            return {"status": "passed", "rc": 0}

        result = run_tool_loop(
            chat=chat, dispatch=dispatch, messages=[{"role": "user", "content": "x"}],
            tools=TOOLS, max_steps=3,
        )
        self.assertEqual(result.stopped_reason, "finish_tool")
        self.assertEqual(dispatched, [("finish_task", {"reason": "done"})])
        self.assertEqual(len(result.steps), 1)
        self.assertEqual(result.steps[0].call_id, "t9")
        # One completion only: the finish tool ends the stage.
        self.assertEqual(calls, [1])

    def test_step_limit_is_a_hard_stop(self):
        calls = []

        def chat(messages, tools):
            calls.append(1)
            return reply(call("probe", {"x": calls[-1]}, call_id=f"t{calls[-1]}"))

        result = run_tool_loop(
            chat=chat, dispatch=lambda n, a: {"ok": True},
            messages=[{"role": "user", "content": "x"}],
            tools=TOOLS, max_steps=2,
        )
        self.assertEqual(result.stopped_reason, "step_limit")
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(result.steps), 2)

    def test_unknown_tool_is_rejected_before_dispatch(self):
        with self.assertRaises(ModelError) as caught:
            run_tool_loop(
                chat=lambda messages, tools: reply(call("rm_rf", {})),
                dispatch=lambda n, a: self.fail("must not dispatch unknown tool"),
                messages=[{"role": "user", "content": "x"}],
                tools=TOOLS, max_steps=2,
            )
        self.assertEqual(caught.exception.kind, "tool_call")

    def test_invalid_arguments_are_rejected(self):
        bad = {"id": "t1", "function": {"name": "probe", "arguments": "{not json"}}
        with self.assertRaises(ModelError):
            run_tool_loop(
                chat=lambda messages, tools: reply(bad),
                dispatch=lambda n, a: {},
                messages=[{"role": "user", "content": "x"}],
                tools=TOOLS, max_steps=2,
            )


if __name__ == "__main__":
    unittest.main()
