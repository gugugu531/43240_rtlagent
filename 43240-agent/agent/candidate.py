"""Candidate identity and lineage, independent of selection strategy."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import time
from typing import Any


@dataclass(frozen=True)
class Candidate:
    """One complete piece of extracted RTL and its immutable origin metadata."""

    id: str
    code: str
    source_stage: str
    round: int
    parent_id: str | None
    finish_reason: str | None
    extraction_status: str
    created_at: float
    code_hash: str

    def public_dict(self) -> dict[str, Any]:
        """Metadata safe for trace and development artifacts; excludes code."""
        return {
            "id": self.id,
            "source_stage": self.source_stage,
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

    def create(self, code: str, *, source_stage: str, round: int,
               parent_id: str | None = None,
               finish_reason: str | None = None,
               extraction_status: str = "complete") -> Candidate:
        if not code:
            raise ValueError("candidate code must not be empty")
        candidate_id = f"c{self._next:03d}"
        self._next += 1
        return Candidate(
            id=candidate_id,
            code=code,
            source_stage=source_stage,
            round=round,
            parent_id=parent_id,
            finish_reason=finish_reason,
            extraction_status=extraction_status,
            created_at=time.time(),
            code_hash=hashlib.sha256(code.encode("utf-8")).hexdigest(),
        )
