"""Shared extraction input and result contracts."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from agent.core.candidate import Candidate
from agent.core.model import ModelReply


ExtractionStatus = Literal["ok", "empty", "incomplete", "target_missing", "ambiguous"]


@dataclass(frozen=True)
class ExtractionResult:
    code: str
    status: ExtractionStatus
    complete: bool
    target_module_found: bool
    module_names: tuple[str, ...]
    multiple_blocks: bool
    suspected_truncation: bool
    diagnostics: tuple[str, ...]

    def trace_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "complete": self.complete,
            "target_module_found": self.target_module_found,
            "module_names": list(self.module_names),
            "multiple_blocks": self.multiple_blocks,
            "suspected_truncation": self.suspected_truncation,
            "diagnostics": list(self.diagnostics),
            "code_bytes": len(self.code.encode("utf-8")),
        }

    def summary_dict(self) -> dict[str, object]:
        return {"status": self.status}


@dataclass(frozen=True)
class ExtractInput:
    reply: ModelReply
    round: int = 1
    parent_id: str | None = None
    source_stage: str = 'generate'


@dataclass(frozen=True)
class ExtractionOutput:
    extraction: ExtractionResult
    candidate: Candidate | None
