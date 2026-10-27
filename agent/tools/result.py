"""Stable tool output envelope shared by host calls and model tool calls.

The runtime must not import RTL domain types, so conversion from CheckResult
uses the attributes the domain result already guarantees instead of importing
it. Full output stays in artifacts; models only see a bounded excerpt.
"""

from dataclasses import dataclass, field
import json

EXCERPT_LIMIT = 2048

# rc values are part of the public tool contract (see docs/agent-interfaces.md).
RC_OK = 0
RC_FAILED = 1
RC_INVALID = 2
RC_TIMEOUT = 3
RC_UNAVAILABLE = 4

_STATUS_RC = {
    "passed": RC_OK,
    "failed": RC_FAILED,
    "timeout": RC_TIMEOUT,
    "unavailable": RC_UNAVAILABLE,
    "error": RC_FAILED,
    "skipped": RC_OK,
}


TRUNCATION_MARKER = "\n[truncated]"


def truncate_excerpt(text, limit=EXCERPT_LIMIT):
    """Cut to a UTF-8 boundary; the marker counts toward the byte limit."""
    text = str(text or "")
    raw = text.encode("utf-8", errors="backslashreplace")
    if len(raw) <= limit:
        return text, False
    marker = TRUNCATION_MARKER.encode("ascii")
    if limit <= len(marker):
        return marker[:limit].decode("ascii"), True
    kept = raw[: limit - len(marker)].decode("utf-8", errors="ignore")
    return kept + TRUNCATION_MARKER, True


@dataclass(frozen=True)
class ToolResult:
    tool: str
    call_id: str
    rc: int
    status: str
    excerpt: str
    artifacts: tuple[str, ...] = ()
    elapsed_s: float = 0.0
    truncated: bool = False
    failure_kind: str = "unknown"
    meta: dict = field(default_factory=dict)

    def to_dict(self):
        return {
            "tool": self.tool,
            "call_id": self.call_id,
            "rc": self.rc,
            "status": self.status,
            "excerpt": self.excerpt,
            "artifacts": list(self.artifacts),
            "elapsed_s": self.elapsed_s,
            "truncated": self.truncated,
            "failure_kind": self.failure_kind,
            "meta": self.meta,
        }

    def to_model_dict(self):
        """Model-visible view: no full details, commands, or host-only payloads."""
        visible = ("blocking", "candidate_id", "check_id")
        return {
            "tool": self.tool,
            "call_id": self.call_id,
            "rc": self.rc,
            "status": self.status,
            "excerpt": self.excerpt,
            "artifacts": list(self.artifacts),
            "truncated": self.truncated,
            "failure_kind": self.failure_kind,
            "meta": {key: self.meta[key] for key in visible if key in self.meta},
        }

    @classmethod
    def from_check_result(cls, result, *, tool="", call_id=""):
        status = getattr(result, "status", "error")
        excerpt, truncated = truncate_excerpt(getattr(result, "summary", ""))
        details = getattr(result, "details", None) or {}
        return cls(
            tool=tool or getattr(result, "kind", "") or "check",
            call_id=call_id,
            rc=_STATUS_RC.get(status, RC_FAILED),
            status=status,
            excerpt=excerpt,
            artifacts=tuple(getattr(result, "log_paths", ()) or ()),
            elapsed_s=float(getattr(result, "elapsed_s", 0.0) or 0.0),
            truncated=truncated,
            failure_kind=getattr(result, "failure_kind", "unknown"),
            meta={
                "blocking": bool(getattr(result, "blocking", False)),
                "command": [list(item) for item in getattr(result, "command", ()) or ()],
                "candidate_id": getattr(result, "candidate_id", None),
                "check_id": getattr(result, "id", None),
                "details": dict(details),
            },
        )

    @classmethod
    def from_value(cls, value, *, tool="", call_id="", status="passed", rc=RC_OK):
        if isinstance(value, dict):
            try:
                text = json.dumps(value, ensure_ascii=False, sort_keys=True)
            except (TypeError, ValueError):
                text = str(value)
        else:
            text = str(value)
        excerpt, truncated = truncate_excerpt(text)
        return cls(
            tool=tool,
            call_id=call_id,
            rc=rc,
            status=status,
            excerpt=excerpt,
            truncated=truncated,
            meta={"value_type": type(value).__name__},
        )

    @classmethod
    def failure(cls, *, tool="", call_id="", status="error", rc=RC_FAILED,
                excerpt="", failure_kind="unknown", meta=None):
        text, truncated = truncate_excerpt(excerpt)
        return cls(
            tool=tool,
            call_id=call_id,
            rc=rc,
            status=status,
            excerpt=text,
            truncated=truncated,
            failure_kind=failure_kind,
            meta=dict(meta or {}),
        )
