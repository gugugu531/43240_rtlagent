"""LLM backend.

Two backends, one code path:

    LLM_BACKEND=mock      no network, no key. Returns a canned stub derived from
                          the interface. Use this to verify the run.sh contract
                          and the judging pipeline without a GPU or an API key.

    LLM_BACKEND=openai    any OpenAI-compatible /chat/completions endpoint.
                          This covers BOTH a commercial API bought by the team
                          (development only) AND a local vLLM server (what the
                          submission must actually use).

    development   LLM_BASE_URL=https://api.deepseek.com/v1
    local model   LLM_BASE_URL=http://localhost:8000/v1

Only the environment variables change; the agent does not.

NOTE FOR SUBMISSION: the final run happens in an offline sandbox. MODEL.md must
declare locally deployable open weights. A commercial API fails conditions 2.1
and 2.3 of the scoring rules and produces no run-based score at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import os
import re
import time
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlsplit


class LLMError(RuntimeError):
    """Base class for safe, classified model-client failures."""

    kind = "llm_error"
    retryable = False

    def __init__(self, message: str, *, status_code: int | None = None,
                 elapsed_s: float = 0.0):
        super().__init__(message)
        self.status_code = status_code
        self.elapsed_s = elapsed_s

    def public_dict(self) -> dict[str, Any]:
        """Fields that are safe to put in trace.jsonl."""
        return {
            "kind": self.kind,
            "retryable": self.retryable,
            "status_code": self.status_code,
            "elapsed_s": round(self.elapsed_s, 3),
            "message": str(self),
        }


class LLMConfigError(LLMError):
    kind = "config"


class LLMTimeoutError(LLMError):
    kind = "timeout"
    retryable = True


class LLMConnectionError(LLMError):
    kind = "connection"
    retryable = True


class LLMHTTPError(LLMError):
    kind = "http"

    def __init__(self, status_code: int, message: str, *, elapsed_s: float = 0.0):
        super().__init__(message, status_code=status_code, elapsed_s=elapsed_s)
        self.retryable = status_code in {408, 425, 429, 500, 502, 503, 504}


class LLMResponseError(LLMError):
    kind = "response"


@dataclass(frozen=True)
class LLMConfig:
    """Validated configuration for one model service.

    api_key is deliberately excluded from repr() and public_dict().
    """

    backend: str = "mock"
    model: str = "mock-model"
    base_url: str = ""
    api_key: str = field(default="", repr=False)
    max_tokens: int = 4096
    temperature: float = 0.2
    timeout_s: float = 180.0

    def __post_init__(self) -> None:
        backend = self.backend.strip().lower()
        model = self.model.strip()
        base_url = self.base_url.strip().rstrip("/")
        object.__setattr__(self, "backend", backend)
        object.__setattr__(self, "model", model)
        object.__setattr__(self, "base_url", base_url)

        if backend not in {"mock", "openai"}:
            raise LLMConfigError(f"unknown LLM_BACKEND: {backend!r}")
        if not model:
            raise LLMConfigError("LLM_MODEL must not be empty")
        object.__setattr__(
            self, "max_tokens",
            _positive_int("max_tokens", self.max_tokens, self.max_tokens),
        )
        object.__setattr__(
            self, "temperature",
            _nonnegative_float("temperature", self.temperature, self.temperature),
        )
        object.__setattr__(
            self, "timeout_s",
            _positive_float("timeout_s", self.timeout_s, self.timeout_s),
        )

        if backend == "openai":
            if not base_url:
                raise LLMConfigError("LLM_BACKEND=openai requires LLM_BASE_URL")
            parsed = urlsplit(base_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise LLMConfigError(
                    "LLM_BASE_URL must be an absolute http:// or https:// URL"
                )
            if parsed.username is not None or parsed.password is not None:
                raise LLMConfigError("LLM_BASE_URL must not contain credentials")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "LLMConfig":
        values = os.environ if env is None else env
        backend = values.get("LLM_BACKEND", "mock").strip().lower()
        model = values.get("LLM_MODEL", "mock-model").strip()
        base_url = values.get("LLM_BASE_URL", "").strip().rstrip("/")
        api_key = values.get("LLM_API_KEY", "")
        max_tokens = _parse_positive_int(values, "LLM_MAX_TOKENS", 4096)
        temperature = _parse_nonnegative_float(values, "LLM_TEMPERATURE", 0.2)
        timeout_s = _parse_positive_float(values, "LLM_TIMEOUT_S", 180.0)

        return cls(
            backend=backend,
            model=model,
            base_url=base_url,
            api_key=api_key,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout_s=timeout_s,
        )

    def public_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "model": self.model,
            "base_url": self.base_url or None,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "timeout_s": self.timeout_s,
        }


@dataclass(frozen=True)
class LLMResult:
    """Backend-independent result of one model call."""

    text: str
    tokens_in: int = 0
    tokens_out: int = 0
    finish_reason: str | None = None
    elapsed_s: float = 0.0
    model: str | None = None
    request_id: str | None = None
    empty_content: bool = False
    has_reasoning: bool = False

    @property
    def finish(self) -> str | None:
        """Compatibility alias used by the current trace writer."""
        return self.finish_reason


class LLM:
    """Small client for mock or OpenAI-compatible chat-completions backends."""

    def __init__(self, config: LLMConfig | None = None) -> None:
        self.config = config or LLMConfig.from_env()

        # Compatibility attributes. New code should prefer self.config.
        self.backend = self.config.backend
        self.model = self.config.model
        self.base_url = self.config.base_url
        self.api_key = self.config.api_key
        self.max_tokens = self.config.max_tokens
        self.temperature = self.config.temperature
        self.timeout_s = self.config.timeout_s

    def describe(self) -> dict[str, Any]:
        return self.config.public_dict()

    def chat(self, messages: Sequence[Mapping[str, Any]], *,
             timeout_s: float | None = None,
             max_tokens: int | None = None,
             temperature: float | None = None) -> LLMResult:
        """Make exactly one model call.

        This method deliberately does not retry. Retry decisions belong to the
        agent, which knows the remaining wall-clock budget and whether it already
        has a usable candidate.
        """
        call_timeout = _positive_float("timeout_s", timeout_s, self.timeout_s)
        call_max_tokens = _positive_int("max_tokens", max_tokens, self.max_tokens)
        call_temperature = _nonnegative_float(
            "temperature", temperature, self.temperature
        )

        if self.backend == "mock":
            return self._chat_mock(messages)
        if self.backend == "openai":
            return self._chat_openai(
                messages,
                timeout_s=call_timeout,
                max_tokens=call_max_tokens,
                temperature=call_temperature,
            )
        # LLMConfig rejects this, but keep the guard for injected test configs.
        raise LLMConfigError(f"unknown LLM_BACKEND: {self.backend!r}")

    # ---------------------------------------------------------------- openai

    def _chat_openai(self, messages: Sequence[Mapping[str, Any]], *,
                     timeout_s: float, max_tokens: int,
                     temperature: float) -> LLMResult:
        import requests  # imported lazily so mock mode needs no dependency

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model,
            "messages": list(messages),
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }

        started = time.monotonic()
        try:
            resp = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=timeout_s,
            )
        except requests.Timeout as exc:
            elapsed = time.monotonic() - started
            raise LLMTimeoutError(
                f"model request timed out after {elapsed:.2f}s",
                elapsed_s=elapsed,
            ) from exc
        except requests.ConnectionError as exc:
            elapsed = time.monotonic() - started
            raise LLMConnectionError(
                f"could not connect to model service: "
                f"{_safe_exception(exc, secret=self.api_key)}",
                elapsed_s=elapsed,
            ) from exc
        except requests.RequestException as exc:
            elapsed = time.monotonic() - started
            raise LLMConnectionError(
                f"model request failed: {_safe_exception(exc, secret=self.api_key)}",
                elapsed_s=elapsed,
            ) from exc

        elapsed = time.monotonic() - started
        if resp.status_code != 200:
            excerpt = _safe_excerpt(resp.text, secret=self.api_key)
            raise LLMHTTPError(
                resp.status_code,
                f"model service returned HTTP {resp.status_code}: {excerpt}",
                elapsed_s=elapsed,
            )

        try:
            body = resp.json()
        except (ValueError, TypeError) as exc:
            raise LLMResponseError(
                "model service returned invalid JSON",
                elapsed_s=elapsed,
            ) from exc

        return _parse_openai_response(
            body,
            elapsed_s=elapsed,
            fallback_model=self.model,
        )

    # ------------------------------------------------------------------ mock

    def _chat_mock(self, messages: Sequence[Mapping[str, Any]]) -> LLMResult:
        """Return something shaped like a real answer, without a model.

        The point is to exercise the plumbing -- prompt assembly, code
        extraction, tool invocation, trace writing, the HTTP shell -- not to
        produce a correct module. The stub declares the right ports and drives
        every output to zero: it elaborates, so the pipeline runs end to end,
        and it fails simulation, which is honest.
        """
        started = time.monotonic()
        user = "\n".join(
            str(m["content"]) for m in messages if m.get("role") == "user"
        )
        header, outputs = _parse_module(user)
        if header is None:
            # 评测题集不下发 interface.txt，题面里也没有 module 声明，端口清单
            # 是 `- input clk` 这样的列表。桩模式必须走和评测当天同一条路，
            # 否则它验证的链路和真正要跑的那条不是一回事。
            header, outputs = _header_from_prompt(user)

        if header:
            body = header + "\n"
            body += "  // MOCK BACKEND -- placeholder body, not a real solution.\n"
            body += "  // Set LLM_BACKEND=openai to get a generated implementation.\n"
            for name, width in outputs:
                lit = "1'b0" if width <= 1 else f"{width}'b0"
                body += f"  assign {name} = {lit};\n"
            body += "endmodule\n"
        else:
            body = ("// MOCK BACKEND: 既没有 module 声明，也没能从题面解析出端口清单\n")

        text = "以下是实现：\n\n```verilog\n" + body + "```\n"
        return LLMResult(
            text=text,
            tokens_in=len(user) // 4,
            tokens_out=len(text) // 4,
            finish_reason="stop",
            elapsed_s=time.monotonic() - started,
            model=self.model,
            empty_content=not text,
        )


# -------------------------------------------------------- response parsing


def _parse_openai_response(body: Any, *, elapsed_s: float,
                           fallback_model: str) -> LLMResult:
    """Validate the small response subset the agent actually consumes."""
    if not isinstance(body, Mapping):
        raise LLMResponseError(
            "model response must be a JSON object",
            elapsed_s=elapsed_s,
        )

    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LLMResponseError(
            "model response has no choices",
            elapsed_s=elapsed_s,
        )

    choice = choices[0]
    if not isinstance(choice, Mapping):
        raise LLMResponseError(
            "model response choice must be an object",
            elapsed_s=elapsed_s,
        )
    message = choice.get("message")
    if not isinstance(message, Mapping):
        raise LLMResponseError(
            "model response choice has no message object",
            elapsed_s=elapsed_s,
        )

    content = message.get("content")
    if content is None:
        text = ""
    elif isinstance(content, str):
        text = content
    else:
        raise LLMResponseError(
            "model response message.content must be a string or null",
            elapsed_s=elapsed_s,
        )

    finish_reason = choice.get("finish_reason")
    if finish_reason is not None and not isinstance(finish_reason, str):
        raise LLMResponseError(
            "model response finish_reason must be a string or null",
            elapsed_s=elapsed_s,
        )

    usage = body.get("usage")
    if not isinstance(usage, Mapping):
        usage = {}

    response_model = body.get("model")
    if not isinstance(response_model, str) or not response_model:
        response_model = fallback_model
    request_id = body.get("id")
    if not isinstance(request_id, str):
        request_id = None

    reasoning = message.get("reasoning_content")
    if reasoning in (None, ""):
        reasoning = message.get("reasoning")

    return LLMResult(
        text=text,
        tokens_in=_usage_int(usage.get("prompt_tokens")),
        tokens_out=_usage_int(usage.get("completion_tokens")),
        finish_reason=finish_reason,
        elapsed_s=elapsed_s,
        model=response_model,
        request_id=request_id,
        empty_content=not text,
        has_reasoning=reasoning not in (None, "", [], {}),
    )


# ------------------------------------------------------- configuration utils


def _parse_positive_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise LLMConfigError(f"{name} must be a positive integer") from exc
    if value <= 0:
        raise LLMConfigError(f"{name} must be a positive integer")
    return value


def _parse_positive_float(env: Mapping[str, str], name: str, default: float) -> float:
    raw = env.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise LLMConfigError(f"{name} must be a positive number") from exc
    if not math.isfinite(value) or value <= 0:
        raise LLMConfigError(f"{name} must be a positive finite number")
    return value


def _parse_nonnegative_float(env: Mapping[str, str], name: str,
                             default: float) -> float:
    raw = env.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise LLMConfigError(f"{name} must be a non-negative number") from exc
    if not math.isfinite(value) or value < 0:
        raise LLMConfigError(f"{name} must be a non-negative finite number")
    return value


def _positive_int(name: str, value: int | None, default: int) -> int:
    selected = default if value is None else value
    if isinstance(selected, bool) or not isinstance(selected, int) or selected <= 0:
        raise LLMConfigError(f"{name} must be a positive integer")
    return selected


def _positive_float(name: str, value: float | None, default: float) -> float:
    selected = default if value is None else value
    try:
        number = float(selected)
    except (TypeError, ValueError) as exc:
        raise LLMConfigError(f"{name} must be a positive number") from exc
    if not math.isfinite(number) or number <= 0:
        raise LLMConfigError(f"{name} must be a positive finite number")
    return number


def _nonnegative_float(name: str, value: float | None, default: float) -> float:
    selected = default if value is None else value
    try:
        number = float(selected)
    except (TypeError, ValueError) as exc:
        raise LLMConfigError(f"{name} must be a non-negative number") from exc
    if not math.isfinite(number) or number < 0:
        raise LLMConfigError(f"{name} must be a non-negative finite number")
    return number


def _usage_int(value: Any) -> int:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError, OverflowError):
        return 0
    return max(parsed, 0)


def _safe_excerpt(value: Any, *, secret: str = "", limit: int = 500) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ")
    if secret:
        text = text.replace(secret, "[REDACTED]")
    return text[:limit]


def _safe_exception(exc: BaseException, *, secret: str = "") -> str:
    return _safe_excerpt(str(exc), secret=secret, limit=300) or type(exc).__name__


# --------------------------------------------------------------------- utils

_MODULE_RE = re.compile(r"module\s+(\w+)\s*(?:#\s*\([^)]*\)\s*)?\((.*?)\)\s*;", re.DOTALL)


def _header_from_prompt(text: str) -> tuple[str | None, list[tuple[str, int]]]:
    """从题面的端口清单拼出 module 头。

    复用 tools.ports_from_prompt，与 check_interface 用的是同一份解析，
    免得两处对「题面里的端口表」有两套理解。
    """
    from .tools import ports_from_prompt

    name, ports = ports_from_prompt(text)
    if not name or not ports:
        return None, []
    decls = []
    for direction, width, pname in ports:
        w = "" if width <= 1 else f" [{width - 1}:0]"
        decls.append(f"  {direction}{w} {pname}")
    header = f"module {name} (\n" + ",\n".join(decls) + "\n);"
    outputs = [(n, w) for d, w, n in ports if d == "output"]
    return header, outputs


def _parse_module(text: str) -> tuple[str | None, list[tuple[str, int]]]:
    """Return the module header verbatim plus its output ports and widths."""
    m = _MODULE_RE.search(text)
    if not m:
        return None, []

    header = m.group(0)
    outputs: list[tuple[str, int]] = []
    for decl in m.group(2).split(","):
        decl = decl.strip()
        if not decl.lower().startswith("output"):
            continue
        rng = re.search(r"\[\s*(\d+)\s*:\s*(\d+)\s*\]", decl)
        width = abs(int(rng.group(1)) - int(rng.group(2))) + 1 if rng else 1
        name = decl.split()[-1].strip("[]() \t")
        if name:
            outputs.append((name, width))
    return header, outputs
