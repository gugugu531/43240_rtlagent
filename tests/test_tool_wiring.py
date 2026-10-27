"""Tool schemas must reach the chat request, not just the loop helper."""

from contextlib import nullcontext
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from agent.llm.types import Reply
from agent.nodes.adaptive import _generation_reply, _request
from agent.workflows.adaptive_verify import AdaptiveParameters


class ToolWiringTests(unittest.TestCase):
    def test_request_forwards_tools_to_chat(self):
        seen = {}

        class Ledger:
            last_denial = None

            def reserve(self, *args, **kwargs):
                return object()

            def snapshot(self):
                return {}

        def chat(messages, **kwargs):
            seen.update(kwargs)
            return SimpleNamespace(call_id="m1", finish_reason="stop")

        data = {
            "settings": {"temperature": 0.0, "top_p": 1.0},
            "ledger": Ledger(),
            "attempted": set(),
            "request_outcomes": {},
        }
        ctx = SimpleNamespace(
            store={"adaptive": data},
            llm=SimpleNamespace(permitted=lambda permit: nullcontext(), chat=chat),
            record=SimpleNamespace(write_json=lambda *a, **k: None,
                                   emit=lambda *a, **k: None),
        )
        tools = [{"type": "function", "function": {"name": "finish_task"}}]
        _request(
            ctx, "review", [{"role": "user", "content": "x"}],
            limits={"timeout_s": 10, "max_tokens": 100}, tools=tools,
        )
        self.assertEqual(seen["tools"], tools)
        self.assertEqual(seen["purpose"], "adaptive_review")

    def test_generation_loop_passes_submit_tool_and_dispatches_it(self):
        settings = AdaptiveParameters(tool_steps=2).model_dump(mode="json")
        data = {"settings": settings, "request_outcomes": {}, "analysis": None}
        ctx = SimpleNamespace(
            store={"adaptive": data},
            tool_schema=lambda name: {
                "type": "function",
                "function": {"name": name, "parameters": {}},
            },
        )
        calls, dispatched = [], []

        def fake_request(ctx_arg, stage, messages, **kwargs):
            calls.append((stage, kwargs.get("tools")))
            if stage == "draft":
                return Reply(
                    "m1", "", "tool_calls", 1, 1,
                    [{
                        "id": "t1",
                        "type": "function",
                        "function": {
                            "name": "submit_answer",
                            "arguments": '{"code": "module TopModule();\\nendmodule\\n"}',
                        },
                    }],
                )
            return Reply("m2", "done", "stop", 1, 1, [])

        def dispatch(name, arguments):
            dispatched.append((name, arguments))
            return {"tool": name, "rc": 0}

        ctx.dispatch = dispatch
        with patch("agent.nodes.adaptive._request", side_effect=fake_request):
            outcome = _generation_reply(
                ctx, stage="draft", messages=[{"role": "user", "content": "x"}]
            )

        self.assertEqual(outcome.stopped_reason, "replied")
        self.assertEqual([stage for stage, _ in calls], ["draft", "draft_tool_2"])
        for _, tools in calls:
            names = {tool["function"]["name"] for tool in tools}
            self.assertEqual(names, {"submit_answer", "finish_task"})
        self.assertEqual(dispatched[0][0], "submit_answer")
        self.assertIn("module TopModule", dispatched[0][1]["code"])


if __name__ == "__main__":
    unittest.main()
