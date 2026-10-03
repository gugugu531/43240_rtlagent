"""Versioned, append-only trace events and reproducibility metadata."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
import json
import os
import re
import subprocess
import time
import uuid
from typing import Any
from urllib.parse import urlsplit, urlunsplit


TRACE_SCHEMA_VERSION = 1

_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SENSITIVE_FIELDS = {
    "api_key",
    "authorization",
    "cookie",
    "password",
    "secret",
    "access_token",
    "refresh_token",
    "rc_cookie",
    "rc_api_key",
    "fpgachina_token",
}
_SECRET_ENV_KEYS = (
    "LLM_API_KEY",
    "FPGACHINA_TOKEN",
    "RC_COOKIE",
    "RC_API_KEY",
    "GH_TOKEN",
    "GITHUB_TOKEN",
    "HF_TOKEN",
    "HUGGING_FACE_HUB_TOKEN",
)


class Trace:
    """Write JSONL events with stable common fields and secret redaction."""

    def __init__(self, path: str, *, run_id: str | None = None,
                 secrets: Iterable[str] | None = None):
        self.path = path
        self.run_id = _run_id(run_id or os.environ.get("AGENT_RUN_ID", ""))
        self._seq = 0
        self._secrets = _known_secrets(secrets)
        self._fh = open(path, "w", encoding="utf-8")

    def write(self, *, tool: str, **fields: Any) -> None:
        """Append one event; callers cannot override the common fields."""
        self._seq += 1
        event = _redact(fields, self._secrets)
        event.update({
            "schema_version": TRACE_SCHEMA_VERSION,
            "run_id": self.run_id,
            "seq": self._seq,
            "ts": round(time.time(), 3),
            "tool": str(tool),
        })
        self._fh.write(json.dumps(event, ensure_ascii=False) + "\n")
        self._fh.flush()

    def close(self) -> None:
        try:
            self._fh.close()
        except OSError:
            pass


def runtime_metadata(*, max_rounds: int, deadline_s: float, reserve_s: float,
                     resolved_top: str, save_candidates: bool,
                     keep_work: bool, agent_tmp: str | None,
                     env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Return the public, strategy-independent configuration for one run."""
    values = os.environ if env is None else env
    return {
        "agent": {
            "max_rounds": max_rounds,
            "deadline_s": deadline_s,
            "reserve_s": reserve_s,
            "resolved_top": resolved_top,
            "save_candidates": save_candidates,
            "keep_work": keep_work,
            "agent_tmp": agent_tmp,
        },
        "model_request": {
            "backend": values.get("LLM_BACKEND", "mock"),
            "model": values.get("LLM_MODEL", "mock-model"),
            "base_url": _public_url(values.get("LLM_BASE_URL", "")),
            "max_tokens": values.get("LLM_MAX_TOKENS", "4096"),
            "temperature": values.get("LLM_TEMPERATURE", "0.2"),
            "timeout_s": values.get("LLM_TIMEOUT_S", "180"),
        },
        "rtl": {
            "part": values.get("RTL_PART", "xczu3eg-sbva484-1-e"),
        },
    }


def git_metadata(root: str, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Describe the source revision without recording remotes or credentials."""
    values = os.environ if env is None else env
    injected_commit = values.get("AGENT_GIT_COMMIT", "").strip()
    if injected_commit:
        raw_dirty = values.get("AGENT_GIT_DIRTY", "").strip().lower()
        return {
            "commit": injected_commit,
            "dirty": raw_dirty in {"1", "true", "yes"} if raw_dirty else None,
            "source": "environment",
        }

    commit = _git(root, "rev-parse", "HEAD")
    if not commit:
        return {"commit": None, "dirty": None, "source": "unavailable"}
    dirty = _git(
        root,
        "status",
        "--porcelain",
        "--",
        ".",
        ":(exclude)dev",
    )
    return {
        "commit": commit,
        "dirty": bool(dirty),
        "source": "repository",
    }


def _git(root: str, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _run_id(value: str) -> str:
    candidate = value.strip()
    return candidate if _RUN_ID_RE.fullmatch(candidate) else uuid.uuid4().hex


def _public_url(value: str) -> str | None:
    if not value:
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return "[invalid-url]"
    if parsed.username is not None or parsed.password is not None:
        return "[redacted-invalid-url]"
    # Query strings and fragments are unnecessary for the model endpoint and
    # are common places for credentials to be embedded.
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _known_secrets(extra: Iterable[str] | None) -> tuple[str, ...]:
    values = [os.environ.get(name, "") for name in _SECRET_ENV_KEYS]
    if extra is not None:
        values.extend(str(value) for value in extra)
    # Very short values cause accidental replacements in ordinary messages.
    return tuple(sorted({value for value in values if len(value) >= 6}, key=len,
                        reverse=True))


def _redact(value: Any, secrets: Sequence[str], *, key: str | None = None) -> Any:
    if key is not None and key.lower().replace("-", "_") in _SENSITIVE_FIELDS:
        return "[redacted]"
    if isinstance(value, str):
        redacted = value
        for secret in secrets:
            redacted = redacted.replace(secret, "[redacted]")
        return redacted
    if isinstance(value, Mapping):
        return {
            str(item_key): _redact(item_value, secrets, key=str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, tuple):
        return [_redact(item, secrets) for item in value]
    if isinstance(value, list):
        return [_redact(item, secrets) for item in value]
    return value
