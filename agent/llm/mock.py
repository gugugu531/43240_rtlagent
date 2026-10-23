"""MockTransport 与严格离线重放，不提供题目参考实现。"""

from __future__ import annotations

import json
import re
from pathlib import Path

import httpx


def _placeholder(messages):
    text = "\n".join(
        message.get("content") or ""
        for message in messages
        if message.get("role") == "user"
    )
    match = re.search(
        r"\bmodule\s+\w+\s*(?:#\s*\([^;]*?\)\s*)?\([^;]*?\)\s*;", text, re.S
    )
    header = match.group() if match else "module TopModule();"
    return (
        header
        + "\n// MOCK BACKEND: placeholder only, no functional claim.\nendmodule\n"
    )


class Replay:
    """每条记录包含完整 request JSON 和 response JSON；顺序与请求必须相同。"""

    def __init__(self, entries):
        self.entries, self.index = entries, 0

    def __call__(self, request):
        if self.index >= len(self.entries):
            return httpx.Response(409, json={"error": "replay exhausted"})
        entry = self.entries[self.index]
        actual = json.loads(request.content) if request.content else None
        if (
            entry.get("method", "POST") != request.method
            or entry.get("path", "/v1/chat/completions") != request.url.path
            or entry["request"] != actual
        ):
            return httpx.Response(
                409, json={"error": "replay request mismatch", "index": self.index}
            )
        self.index += 1
        return httpx.Response(entry.get("status_code", 200), json=entry["response"])

    def assert_consumed(self):
        if self.index != len(self.entries):
            raise AssertionError(
                f"replay consumed {self.index}/{len(self.entries)} records"
            )


def make_transport(*, replay_path=None, responses=None):
    """responses 按 purpose 给出响应队列，用于自编例；耗尽会明确报错。"""
    if replay_path:
        replay = Replay(json.loads(Path(replay_path).read_text(encoding="utf-8")))
        transport = httpx.MockTransport(replay)
        transport.replay = replay
        return transport

    queues = {purpose: list(values) for purpose, values in (responses or {}).items()}

    def handle(request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "mock-model"}]})
        payload = json.loads(request.content)
        if request.url.path.endswith("/tokenize"):
            # 只供流程测试；此数值不代表真实 tokenizer 的计数。
            return httpx.Response(
                200, json={"count": len(json.dumps(payload["messages"])) // 4 + 1}
            )
        if request.url.path.endswith("/chat/completions"):
            purpose = request.extensions.get("purpose", "generate")
            if purpose in queues:
                if not queues[purpose]:
                    return httpx.Response(
                        409,
                        json={
                            "error": "mock response queue exhausted",
                            "purpose": purpose,
                        },
                    )
                content = queues[purpose].pop(0)
                if isinstance(content, dict):
                    return httpx.Response(200, json=content)
            else:
                content = (
                    "{}"
                    if "response_format" in payload
                    else _placeholder(payload["messages"])
                )
            return httpx.Response(
                200,
                json={
                    "model": "mock-model",
                    "choices": [
                        {
                            "message": {"role": "assistant", "content": content},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": None, "completion_tokens": None},
                },
            )
        return httpx.Response(404, json={"error": "unknown mock endpoint"})

    return httpx.MockTransport(handle)
