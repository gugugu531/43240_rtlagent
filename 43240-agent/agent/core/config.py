"""Validated service configuration; orchestration is configured separately."""
from __future__ import annotations
from dataclasses import dataclass, field
from collections.abc import Mapping
from typing import Any
import math
from urllib.parse import urlsplit
import os
from .model import ModelCallError

class ModelConfigError(ModelCallError):
    def __init__(self, message):
        super().__init__(message, kind="config")

@dataclass(frozen=True)
class ModelConfig:
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
            raise ModelConfigError(f"unknown LLM_BACKEND: {backend!r}")
        if not model:
            raise ModelConfigError("LLM_MODEL must not be empty")
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
                raise ModelConfigError("LLM_BACKEND=openai requires LLM_BASE_URL")
            parsed = urlsplit(base_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ModelConfigError(
                    "LLM_BASE_URL must be an absolute http:// or https:// URL"
                )
            if parsed.username is not None or parsed.password is not None:
                raise ModelConfigError("LLM_BASE_URL must not contain credentials")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "ModelConfig":
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


def _parse_positive_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ModelConfigError(f"{name} must be a positive integer") from exc
    if value <= 0:
        raise ModelConfigError(f"{name} must be a positive integer")
    return value


def _parse_positive_float(env: Mapping[str, str], name: str, default: float) -> float:
    raw = env.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ModelConfigError(f"{name} must be a positive number") from exc
    if not math.isfinite(value) or value <= 0:
        raise ModelConfigError(f"{name} must be a positive finite number")
    return value


def _parse_nonnegative_float(env: Mapping[str, str], name: str,
                             default: float) -> float:
    raw = env.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ModelConfigError(f"{name} must be a non-negative number") from exc
    if not math.isfinite(value) or value < 0:
        raise ModelConfigError(f"{name} must be a non-negative finite number")
    return value


def _positive_int(name: str, value: int | None, default: int) -> int:
    selected = default if value is None else value
    if isinstance(selected, bool) or not isinstance(selected, int) or selected <= 0:
        raise ModelConfigError(f"{name} must be a positive integer")
    return selected


def _positive_float(name: str, value: float | None, default: float) -> float:
    selected = default if value is None else value
    try:
        number = float(selected)
    except (TypeError, ValueError) as exc:
        raise ModelConfigError(f"{name} must be a positive number") from exc
    if not math.isfinite(number) or number <= 0:
        raise ModelConfigError(f"{name} must be a positive finite number")
    return number


def _nonnegative_float(name: str, value: float | None, default: float) -> float:
    selected = default if value is None else value
    try:
        number = float(selected)
    except (TypeError, ValueError) as exc:
        raise ModelConfigError(f"{name} must be a non-negative number") from exc
    if not math.isfinite(number) or number < 0:
        raise ModelConfigError(f"{name} must be a non-negative finite number")
    return number


