"""Crash-safe final output and its recovery checkpoint."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import time
from typing import Any

from agent.core.candidate import Candidate


class ArtifactStore:
    """Own the answer files of one Agent run.

    ``solution.v`` exists from initialization onward and every replacement is
    atomic. Candidate history belongs to the full recording, not to this store.
    """

    def __init__(self, output_dir: str | os.PathLike[str]) -> None:
        self.output_dir = Path(output_dir)
        self.solution_path = self.output_dir / "solution.v"
        self.selection_path = self.output_dir / "selection.json"
        self.selected: Candidate | None = None

        self.output_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self.solution_path, "")
        atomic_write_json(self.selection_path, {"candidate_id": None})

    def select(self, candidate: Candidate, *, reason: str) -> None:
        """Atomically make candidate the answer available to the harness."""
        # Commit the authoritative checkpoint first. Recovery can complete the
        # answer replacement if the worker stops between these two writes.
        atomic_write_json(self.selection_path, {
            "candidate": candidate.public_dict(), "candidate_id": candidate.id,
            "code": candidate.code, "code_hash": candidate.code_hash,
            "reason": reason, "selected_at": round(time.time(), 6),
        })
        atomic_write_text(self.solution_path, candidate.code)
        self.selected = candidate

    def clear_selection(self, *, reason: str) -> None:
        atomic_write_json(self.selection_path, {"candidate_id": None, "reason": reason})
        atomic_write_text(self.solution_path, "")
        self.selected = None


def atomic_write_json(path: str | os.PathLike[str], value: Any) -> None:
    text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    atomic_write_text(path, text)


def atomic_write_text(path: str | os.PathLike[str], text: str) -> None:
    """Flush a same-directory temporary file, then replace the target."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        _fsync_directory(target.parent)
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _fsync_directory(directory: Path) -> None:
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)
