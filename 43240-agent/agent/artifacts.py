"""Crash-safe final output and optional per-candidate development artifacts."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import time
from typing import Any

from .candidate import Candidate


class ArtifactStore:
    """Own files produced by one Agent run.

    ``solution.v`` exists from initialization onward and every replacement is
    atomic. Candidate history is optional because it is useful during
    development but is not part of the submission protocol.
    """

    def __init__(self, output_dir: str | os.PathLike[str], *,
                 save_candidates: bool = False) -> None:
        self.output_dir = Path(output_dir)
        self.solution_path = self.output_dir / "solution.v"
        self.candidate_dir = self.output_dir / "candidates"
        self.selection_path = self.output_dir / "selection.json"
        self.save_candidates = save_candidates
        self.selected: Candidate | None = None

        self.output_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self.solution_path, "")
        if self.save_candidates:
            self.candidate_dir.mkdir(parents=True, exist_ok=True)

    def save_candidate(self, candidate: Candidate) -> None:
        if not self.save_candidates:
            return
        atomic_write_text(self.candidate_dir / f"{candidate.id}.v", candidate.code)
        atomic_write_json(
            self.candidate_dir / f"{candidate.id}.json",
            candidate.public_dict(),
        )

    def select(self, candidate: Candidate, *, reason: str) -> None:
        """Atomically make candidate the answer available to the harness."""
        atomic_write_text(self.solution_path, candidate.code)
        self.selected = candidate
        if self.save_candidates:
            atomic_write_json(
                self.selection_path,
                {
                    "candidate_id": candidate.id,
                    "code_hash": candidate.code_hash,
                    "reason": reason,
                    "selected_at": round(time.time(), 6),
                },
            )


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
