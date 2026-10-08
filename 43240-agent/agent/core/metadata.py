from __future__ import annotations
from collections.abc import Mapping
from typing import Any
import os
import re
import subprocess

def git_metadata(root: str, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Describe the source revision by short commit hash, without remotes or credentials."""
    values = os.environ if env is None else env
    injected_commit = values.get("AGENT_GIT_COMMIT", "").strip()
    if injected_commit:
        raw_dirty = values.get("AGENT_GIT_DIRTY", "").strip().lower()
        return {
            "commit": _short(injected_commit),
            "dirty": raw_dirty in {"1", "true", "yes"} if raw_dirty else None,
            "source": "environment",
        }

    commit = _git(root, "rev-parse", "--short", "HEAD")
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


def _short(commit: str) -> str:
    return commit[:7] if re.fullmatch(r"[0-9a-f]{40}", commit) else commit


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


