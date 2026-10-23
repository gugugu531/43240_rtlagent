"""Candidate identity and lineage, independent of selection strategy."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import time
from typing import Any


@dataclass(frozen=True)
class Candidate:
    """Extracted output and its origin; completeness is diagnostic, not guaranteed."""

    id: str
    code: str
    source_stage: str
    round: int
    parent_id: str | None
    finish_reason: str | None
    extraction_status: str
    created_at: float
    code_hash: str
    source_call_id: str | None = None

    def public_dict(self) -> dict[str, Any]:
        """Metadata safe for trace and development artifacts; excludes code."""
        return {
            "id": self.id,
            "source_stage": self.source_stage,
            "source_call_id": self.source_call_id,
            "round": self.round,
            "parent_id": self.parent_id,
            "finish_reason": self.finish_reason,
            "extraction_status": self.extraction_status,
            "created_at": round(self.created_at, 6),
            "code_hash": self.code_hash,
            "code_bytes": len(self.code.encode("utf-8")),
        }

    def trace_dict(self) -> dict[str, Any]:
        fields = self.public_dict()
        fields["candidate_id"] = fields.pop("id")
        return fields


class CandidateFactory:
    """Allocate run-local candidate IDs in creation order."""

    def __init__(self, start: int = 1) -> None:
        if start <= 0:
            raise ValueError("candidate sequence must start above zero")
        self._next = start

    def create(
        self,
        code: str,
        *,
        source_stage: str,
        round: int,
        parent_id: str | None = None,
        finish_reason: str | None = None,
        extraction_status: str = "complete",
        source_call_id: str | None = None,
    ) -> Candidate:
        if not code:
            raise ValueError("candidate code must not be empty")
        candidate_id = f"c{self._next:03d}"
        self._next += 1
        return Candidate(
            id=candidate_id,
            code=code,
            source_call_id=source_call_id,
            source_stage=source_stage,
            round=round,
            parent_id=parent_id,
            finish_reason=finish_reason,
            extraction_status=extraction_status,
            created_at=time.time(),
            code_hash=hashlib.sha256(code.encode("utf-8")).hexdigest(),
        )


class CandidateStore:
    """Record candidate lineage and atomically publish every selected answer."""

    def __init__(self, record, output_dir):
        from pathlib import Path

        self.record, self.output_dir = record, Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._factory, self._items = CandidateFactory(), {}
        self.selected_id = None

    def create(
        self,
        code,
        *,
        source_stage="generate",
        round=1,
        parent_id=None,
        finish_reason=None,
        extraction_status="complete",
        source_call_id=None,
        call_id=None,
    ):
        import difflib

        parent = self.get(parent_id) if parent_id else None
        candidate = self._factory.create(
            code,
            source_stage=source_stage,
            round=round,
            parent_id=parent_id,
            finish_reason=finish_reason,
            extraction_status=extraction_status,
            source_call_id=source_call_id or call_id,
        )
        self._items[candidate.id] = candidate
        self.record.write_text(f"candidates/{candidate.id}.v", candidate.code)
        self.record.emit("candidate", "create", **candidate.trace_dict())
        if parent:
            diff = "".join(
                difflib.unified_diff(
                    parent.code.splitlines(True),
                    code.splitlines(True),
                    fromfile=parent.id,
                    tofile=candidate.id,
                )
            )
            self.record.write_text(f"candidates/{candidate.id}.diff", diff)
            self.record.emit(
                "candidate",
                "change",
                candidate_id=candidate.id,
                parent_id=parent.id,
                changed=parent.code_hash != candidate.code_hash,
                added_lines=sum(
                    line.startswith("+") and not line.startswith("+++")
                    for line in diff.splitlines()
                ),
                removed_lines=sum(
                    line.startswith("-") and not line.startswith("---")
                    for line in diff.splitlines()
                ),
            )
        return candidate

    def get(self, candidate_id):
        return self._items[candidate_id] if candidate_id is not None else None

    def values(self):
        return tuple(self._items.values())

    def select(self, candidate_id, reason):
        import os
        import tempfile

        candidate = self.get(candidate_id)
        if candidate is None:
            raise ValueError("selection requires a candidate")
        fd, path = tempfile.mkstemp(
            prefix=".solution-", suffix=".tmp", dir=self.output_dir
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(candidate.code)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(path, self.output_dir / "solution.v")
        finally:
            if os.path.exists(path):
                os.unlink(path)
        self.selected_id = candidate_id
        self.record.emit(
            "select",
            "result",
            candidate_id=candidate_id,
            reason=reason,
            code_hash=candidate.code_hash,
        )
        return candidate
