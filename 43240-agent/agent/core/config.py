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
        timeout_s = _parse_positive_float(values, "LLM_TIMEOUT_S", 180.0)

        return cls(
            backend=backend,
            model=model,
            base_url=base_url,
            api_key=api_key,
            timeout_s=timeout_s,
        )

    def public_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "model": self.model,
            "base_url": self.base_url or None,
            "timeout_s": self.timeout_s,
        }


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


def _positive_float(name: str, value: float | None, default: float) -> float:
    selected = default if value is None else value
    try:
        number = float(selected)
    except (TypeError, ValueError) as exc:
        raise ModelConfigError(f"{name} must be a positive number") from exc
    if not math.isfinite(number) or number <= 0:
        raise ModelConfigError(f"{name} must be a positive finite number")
    return number


@dataclass(frozen=True)
class ToolConfig:
    part: str = 'xczu3eg-sbva484-1-e'
    bin_dir: str | None = None
    temp_dir: str = '/tmp'
    keep_work: bool = False

    def __post_init__(self):
        import re
        if not isinstance(self.part, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', self.part):
            raise ValueError('tools.part must be a device identifier')
        if type(self.keep_work) is not bool:
            raise ValueError('tools.keep_work must be boolean')

    @classmethod
    def from_env(cls, env=None):
        values = os.environ if env is None else env
        return cls(part=values.get('RTL_PART', cls.part), bin_dir=values.get('VIVADO_BIN') or None,
                   temp_dir=values.get('AGENT_TMP') or values.get('EDA_TMP') or values.get('TRACK_TMP') or '/tmp',
                   keep_work=values.get('AGENT_KEEP_WORK') == '1')

    def public_dict(self):
        from dataclasses import asdict
        return asdict(self)
