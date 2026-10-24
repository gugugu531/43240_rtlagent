"""同步 httpx 客户端：先保存传输证据，再检查响应。"""

from __future__ import annotations

import copy
import json
import math
import os
import time
from contextlib import contextmanager
from functools import wraps

import httpx


from .types import ModelError, Reply, _get


def _count(value):
    return value if type(value) is int and value >= 0 else None


def _scoped(method):
    @wraps(method)
    def run(self, *args, **kwargs):
        before = set(self._active)
        with self.record.scope():
            try:
                return method(self, *args, **kwargs)
            except BaseException as exc:
                # 包含硬截止信号、解析中断和记录失败，不能伪造一次完整调用。
                for call_id in set(self._active) - before:
                    event = self._active.pop(call_id)
                    self.record.emit(
                        event["tool"],
                        "failed",
                        call_id=call_id,
                        purpose=event["purpose"],
                        rc=1,
                        incomplete=True,
                        elapsed_s=time.monotonic() - event["start"],
                        error_kind="interrupted",
                        error_type=type(exc).__name__,
                        excerpt="request lifecycle interrupted",
                        **self._usage.get(
                            call_id, {"tokens_in": None, "tokens_out": None}
                        ),
                    )
                raise

    return run


def _chat_deadline(method):
    """Share one time window across discovery, prompt preparation and generation."""
    @wraps(method)
    def run(self, *args, **kwargs):
        limit = kwargs.get("timeout_s")
        with self.request_window(limit):
            return method(self, *args, **kwargs)

    return run


class Client:
    def __init__(
        self, config, budget, record, generation, tool_dispatch=None, *, transport=None
    ):
        self.config, self.budget, self.record = config, budget, record
        self.generation = copy.deepcopy(generation)
        self.tool_dispatch = tool_dispatch
        self.replies: dict[str, Reply] = {}
        self.requests: list[dict] = []
        self._usage: dict[str, dict] = {}
        self._active: dict[str, dict] = {}
        self._request_deadline: float | None = None
        self._seq = 0
        self._model = _get(config, "model") or None
        self.base_url = _get(config, "base_url", "http://127.0.0.1:8000/v1").rstrip("/")
        backend = _get(config, "backend", "openai")
        if transport is None and backend in {"mock", "replay"}:
            from .mock import make_transport

            if backend == "replay" and not _get(config, "replay_path"):
                raise ValueError("replay backend requires replay_path")
            transport = make_transport(replay_path=_get(config, "replay_path"))
        # 不从代理环境继承请求头；baseline 请求也不包含认证。
        self.http = httpx.Client(transport=transport, trust_env=False)
        self.replay = getattr(transport, "replay", None)

    @contextmanager
    def request_window(self, timeout_s=None):
        """Bound optional preparation and chat by the same nested request window."""
        limit = timeout_s if timeout_s is not None else _get(self.config, "timeout_s", 180)
        if not math.isfinite(limit) or limit <= 0:
            raise ValueError("chat timeout must be positive and finite")
        deadline = time.monotonic() + self.budget.timeout(limit)
        previous = self._request_deadline
        self._request_deadline = min(deadline, previous) if previous is not None else deadline
        try:
            yield
        finally:
            self._request_deadline = previous

    def assert_replay_consumed(self):
        if self.replay is not None:
            self.replay.assert_consumed()

    def close(self):
        self.http.close()

    def usage_summary(self):
        """包含已开始但没有可用回复的请求；未知用量不能变成零。"""
        summary = {"calls": len(self._usage)}
        for field in ("tokens_in", "tokens_out"):
            values = [usage[field] for usage in self._usage.values()]
            known = sum(value for value in values if value is not None)
            unknown = sum(value is None for value in values)
            summary[field] = None if unknown else known
            summary["known_" + field] = known
            summary["unknown_" + field + "_calls"] = unknown
        return summary

    def _request(
        self,
        method,
        url,
        *,
        payload=None,
        purpose,
        timeout_s,
        authenticated=True,
        call_id=None,
    ):
        if self._request_deadline is not None:
            available = self._request_deadline - time.monotonic()
            if available <= 0:
                self.record.emit(
                    "budget", "model_deadline_exhausted", purpose=purpose,
                    reason="chat deadline exhausted before HTTP request",
                )
                raise ModelError("chat deadline exhausted before HTTP request", kind="timeout")
            timeout_s = min(timeout_s, available)
        self._seq += 1
        call_id = call_id or f"m{self._seq:04d}"
        timeout = self.budget.timeout(
            min(timeout_s, _get(self.config, "timeout_s", 180))
        )
        headers = {"Content-Type": "application/json"}
        api_key = _get(self.config, "api_key")
        if authenticated and api_key:
            headers["Authorization"] = "Bearer " + str(api_key)
        self.record.write_json(
            f"calls/{call_id}/request.json",
            {
                "method": method,
                "url": url,
                "payload": payload,
                "timeout_s": timeout,
            },
        )
        self.record.emit(
            "llm"
            if purpose not in {"models", "tokenize", "apply_template"}
            else purpose,
            "started",
            call_id=call_id,
            purpose=purpose,
        )
        start = time.monotonic()
        event_tool = (
            "llm"
            if purpose not in {"models", "tokenize", "apply_template"}
            else purpose
        )
        self._active[call_id] = {"tool": event_tool, "purpose": purpose, "start": start}
        if event_tool == "llm":
            self._usage[call_id] = {"tokens_in": None, "tokens_out": None}
        try:
            response = self.http.request(
                method,
                url,
                json=payload,
                headers=headers,
                timeout=timeout,
                extensions={"purpose": purpose},
            )
        except httpx.RequestError as exc:
            kind = (
                "timeout" if isinstance(exc, httpx.TimeoutException) else "connection"
            )
            self.record.emit(
                event_tool,
                "failed",
                call_id=call_id,
                purpose=purpose,
                rc=1,
                error_kind=kind,
                elapsed_s=time.monotonic() - start,
                tokens_in=None,
                tokens_out=None,
                excerpt=f"model {kind} failure",
            )
            self._active.pop(call_id, None)
            raise ModelError(
                f"model {kind} failure", kind=kind, call_id=call_id
            ) from exc
        # 无论 HTTP 状态码与 JSON 格式是否有效，保留原始响应。
        self.record.write_text(f"calls/{call_id}/response.txt", response.text)
        self.record.write_json(
            f"calls/{call_id}/http.json", {"status_code": response.status_code}
        )
        json_valid = True
        try:
            body = response.json()
        except ValueError:
            body = None
            json_valid = False
        else:
            self.record.write_json(f"calls/{call_id}/response.json", body)
        if (
            event_tool == "llm"
            and isinstance(body, dict)
            and isinstance(body.get("usage"), dict)
        ):
            self._usage[call_id] = {
                "tokens_in": _count(body["usage"].get("prompt_tokens")),
                "tokens_out": _count(body["usage"].get("completion_tokens")),
            }
        elapsed = time.monotonic() - start
        if self._request_deadline is not None and time.monotonic() >= self._request_deadline:
            # A transport can return late despite its per-I/O timeout. Preserve
            # the received bytes and usage, but do not adopt an expired result.
            self.record.emit(
                event_tool, "failed", call_id=call_id, purpose=purpose, rc=1,
                http_status=response.status_code, error_kind="timeout", elapsed_s=elapsed,
                **self._usage.get(call_id, {"tokens_in": None, "tokens_out": None}),
                excerpt="chat deadline exhausted before response adoption",
            )
            self._active.pop(call_id, None)
            raise ModelError("chat deadline exhausted before response adoption", kind="timeout", call_id=call_id)
        if not response.is_success or not json_valid:
            kind = "http" if not response.is_success else "invalid_json"
            usage = self._usage.get(call_id, {"tokens_in": None, "tokens_out": None})
            self.record.emit(
                event_tool,
                "failed",
                call_id=call_id,
                purpose=purpose,
                rc=1,
                http_status=response.status_code,
                error_kind=kind,
                elapsed_s=elapsed,
                **usage,
                excerpt=f"HTTP {response.status_code}: {kind}",
            )
            self._active.pop(call_id, None)
            raise ModelError(
                f"HTTP {response.status_code}: {kind}", kind=kind, call_id=call_id
            )
        return call_id, body, elapsed

    @_scoped
    def models(self, *, authenticated=True):
        call_id, body, elapsed = self._request(
            "GET",
            self.base_url + "/models",
            purpose="models",
            timeout_s=30,
            authenticated=authenticated,
        )
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, list) or any(
            not isinstance(item, dict) or not isinstance(item.get("id"), str)
            for item in data
        ):
            self._invalid(call_id, "models", "invalid models response", elapsed)
        self.record.emit("models", "finished", call_id=call_id, rc=0, elapsed_s=elapsed)
        self._active.pop(call_id, None)
        return data

    def baseline_model(self):
        if os.environ.get("MODEL_NAME"):
            return os.environ["MODEL_NAME"]
        try:
            models = self.models(authenticated=False)
            return models[0]["id"] if models else "default"
        except ModelError:
            return "default"

    def model(self):
        if self._model is None:
            try:
                models = self.models()
                self._model = (
                    models[0]["id"] if models and models[0]["id"] else "default"
                )
            except ModelError:
                self._model = "default"
        return self._model

    @_scoped
    def tokenize(self, messages, *, model=None, tools=None):
        payload = {
            "model": model or self.model(),
            "messages": messages,
            "add_generation_prompt": True,
            **self.generation,
        }
        if tools:
            payload["tools"] = tools
        llama_cpp = _get(self.config, "tokenizer_protocol", "vllm") == "llama_cpp"
        if llama_cpp:
            template_id, template, elapsed = self._request(
                "POST",
                self.base_url.removesuffix("/v1") + "/apply-template",
                payload=payload,
                purpose="apply_template",
                timeout_s=30,
            )
            prompt = template.get("prompt") if isinstance(template, dict) else None
            if not isinstance(prompt, str) or not prompt:
                self._invalid(
                    template_id,
                    "apply_template",
                    "invalid chat template response",
                    elapsed,
                )
            self.record.emit(
                "apply_template",
                "finished",
                call_id=template_id,
                rc=0,
                elapsed_s=elapsed,
            )
            self._active.pop(template_id, None)
            payload = {"content": prompt, "add_special": True, "parse_special": True}
        url = self.base_url.removesuffix("/v1") + "/tokenize"
        call_id, body, elapsed = self._request(
            "POST",
            url,
            payload=payload,
            purpose="tokenize",
            timeout_s=min(30, _get(self.config, "timeout_s", 180)),
        )
        count = _count(body.get("count")) if isinstance(body, dict) else None
        if llama_cpp:
            tokens = body.get("tokens") if isinstance(body, dict) else None
            count = (
                len(tokens)
                if isinstance(tokens, list)
                and tokens
                and all(type(token) is int and token >= 0 for token in tokens)
                else None
            )
        if count is None:
            self._invalid(
                call_id,
                "tokenize",
                "tokenizer did not return a nonnegative count",
                elapsed,
            )
        self.record.emit(
            "tokenize",
            "finished",
            call_id=call_id,
            rc=0,
            elapsed_s=elapsed,
            tokens_in=count,
            tokens_out=None,
        )
        self._active.pop(call_id, None)
        return count

    def _invalid(self, call_id, purpose, message, elapsed):
        tool = purpose if purpose in {"models", "tokenize", "apply_template"} else "llm"
        usage = self._usage.get(call_id, {"tokens_in": None, "tokens_out": None})
        self.record.emit(
            tool,
            "failed",
            call_id=call_id,
            purpose=purpose,
            rc=1,
            error_kind="response",
            excerpt=message,
            elapsed_s=elapsed,
            **usage,
        )
        self._active.pop(call_id, None)
        raise ModelError(message, call_id=call_id)

    @_scoped
    @_chat_deadline
    def chat(
        self,
        messages,
        *,
        purpose="generate",
        temperature=0.2,
        max_tokens=4096,
        top_p=1.0,
        timeout_s=None,
        response_format=None,
        tools=None,
        baseline=False,
    ):
        model = self.baseline_model() if baseline else self.model()
        limit = _get(self.config, "max_model_len")
        if limit is not None and not baseline:
            count = self.tokenize(messages, model=model, tools=tools)
            max_tokens = min(max_tokens, limit - count)
            if max_tokens <= 0:
                self.record.emit(
                    "budget",
                    "context_exhausted",
                    rc=1,
                    tokens_in=count,
                    max_model_len=limit,
                )
                raise ModelError("prompt exhausts model context", kind="context")
        payload = {
            "model": model,
            "messages": copy.deepcopy(messages),
            "temperature": temperature,
            "top_p": top_p,
            "max_tokens": max_tokens,
            **self.generation,
        }
        if response_format is not None:
            payload["response_format"] = response_format
        if tools:
            payload.update(tools=tools, tool_choice="auto")
        self.requests.append(copy.deepcopy(payload))
        call_id, body, elapsed = self._request(
            "POST",
            self.base_url + "/chat/completions",
            payload=payload,
            purpose=purpose,
            timeout_s=timeout_s
            if timeout_s is not None
            else _get(self.config, "timeout_s", 180),
            authenticated=not baseline,
        )
        try:
            choice = body["choices"][0]
            message = choice["message"]
            if not isinstance(message, dict):
                raise ValueError("message must be an object")
            content, finish = message.get("content"), choice.get("finish_reason")
            if content is not None and not isinstance(content, str):
                raise ValueError("content must be string or null")
            if finish is not None and not isinstance(finish, str):
                raise ValueError("finish_reason must be string or null")
            tool_calls = message.get("tool_calls") or []
            if not isinstance(tool_calls, list) or any(
                not isinstance(call, dict) for call in tool_calls
            ):
                raise ValueError("tool_calls must be an array of objects")
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            self._invalid(
                call_id, purpose, "invalid chat response: " + str(exc), elapsed
            )
        usage = body.get("usage") or {}
        usage = usage if isinstance(usage, dict) else {}
        reply = Reply(
            call_id,
            content or "",
            finish,
            _count(usage.get("prompt_tokens")),
            _count(usage.get("completion_tokens")),
            tool_calls,
            {
                key: message[key]
                for key in ("reasoning", "reasoning_content")
                if key in message
            },
            body.get("model"),
        )
        self.replies[call_id] = reply
        self.record.emit(
            "llm",
            "finished",
            call_id=call_id,
            purpose=purpose,
            rc=0,
            finish_reason=finish,
            tokens_in=reply.tokens_in,
            tokens_out=reply.tokens_out,
            empty_content=not reply.content,
            elapsed_s=elapsed,
            excerpt=reply.content[:2000],
        )
        self._active.pop(call_id, None)
        return reply

    def ask(self, messages, schema, **kwargs):
        from .structured import ask

        return ask(self, messages, schema, **kwargs)

    def run_tools(self, messages, *, tools, max_steps=4, **kwargs):
        """工具 schema 来自运行时同一注册表，分派也走受管理工具入口。"""
        if self.tool_dispatch is None:
            raise ValueError("tool_dispatch is required")
        if max_steps < 1:
            raise ValueError("max_steps must be positive")
        allowed = {tool["function"]["name"] for tool in tools}
        conversation = copy.deepcopy(messages)
        for _ in range(max_steps):
            reply = self.chat(conversation, tools=tools, **kwargs)
            if not reply.tool_calls:
                return reply
            conversation.append(
                {
                    "role": "assistant",
                    "content": reply.content or None,
                    "tool_calls": reply.tool_calls,
                }
            )
            for call in reply.tool_calls:
                try:
                    function, call_id = call["function"], call["id"]
                    name = function["name"]
                    arguments = json.loads(function["arguments"])
                    if (
                        name not in allowed
                        or not isinstance(call_id, str)
                        or not isinstance(arguments, dict)
                    ):
                        raise ValueError("unknown tool or invalid arguments")
                except (KeyError, TypeError, ValueError) as exc:
                    raise ModelError(
                        "invalid tool call", kind="tool_call", call_id=reply.call_id
                    ) from exc
                result = self.tool_dispatch(name, arguments)
                if hasattr(result, "model_dump"):
                    result = result.model_dump(mode="json")
                conversation.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
        raise ModelError("tool-call step limit reached", kind="tool_limit")
