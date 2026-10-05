from __future__ import annotations
from collections.abc import Mapping
from typing import Any
import os
import subprocess
from urllib.parse import urlsplit, urlunsplit

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


