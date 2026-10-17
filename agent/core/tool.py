"""Results shared by RTL tool implementations and their callers."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal

TOOL_SUMMARY_LIMIT = 2000
ToolStatus = Literal["ok", "failed", "timeout", "unavailable"]


@dataclass(frozen=True)
class ToolResult:
    """Standard result of one logical RTL tool step.

    ``command`` is nested because lint consists of xvlog followed by xelab.
    Full logs stay out of this object and trace. ``log_paths`` names the one
    saved copy: the supervisor's process logs when present, otherwise a log
    written by the toolchain.
    """

    tool: str
    command: tuple[tuple[str, ...], ...]
    rc: int
    status: ToolStatus
    elapsed_s: float
    summary: str
    log_paths: tuple[str, ...] = ()
    work_dir: str | None = None
    failure_kind: str = "unknown"
    diagnostic_tool: str | None = None
    tool_version: str | None = None
    details: dict = field(default_factory=dict)

    def trace_dict(self) -> dict[str, object]:
        fields: dict[str, object] = {
            "tool": self.tool,
            "command": [list(command) for command in self.command],
            "rc": self.rc,
            "status": self.status,
            "elapsed_s": round(self.elapsed_s, 3),
            "excerpt": self.summary[:TOOL_SUMMARY_LIMIT],
        }
        if self.log_paths:
            fields["log_paths"] = list(self.log_paths)
        if self.work_dir is not None:
            fields["work_dir"] = self.work_dir
        return fields
