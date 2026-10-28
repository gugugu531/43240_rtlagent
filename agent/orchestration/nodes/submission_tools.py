"""Model-callable submission and stage-control tools.

These tools only register intent. The submission gateway decides whether the
draft is published, and lifecycle finalization remains host-owned.
"""

import json

from agent.kit import Ctx, tool
from agent.tools.result import (
    RC_INVALID,
    RC_OK,
    RC_UNAVAILABLE,
    ToolResult,
)


@tool("submit_answer")
def submit_answer(ctx: Ctx, code: str, top: str = "", note: str = ""):
    """Register a complete RTL draft as a candidate; the host decides publication."""
    gateway = ctx.store.get("submission")
    if gateway is None:
        return ToolResult.failure(
            tool="submit_answer",
            status="unavailable",
            rc=RC_UNAVAILABLE,
            excerpt="submission gateway is not initialized for this workflow",
            failure_kind="environment",
        )
    try:
        record = gateway.submit_text(
            code, top=top or None, source_stage="submit_answer", note=note
        )
    except ValueError as error:
        return ToolResult.failure(
            tool="submit_answer",
            status="error",
            rc=RC_INVALID,
            excerpt=str(error),
            failure_kind="code",
        )
    candidate_id = record.get("candidate_id")
    # A complete tool submission is usable even if the next tool call or the
    # next model request fails. Establish the fallback now, never overriding an
    # existing evidence-backed selection.
    if candidate_id and ctx.candidates.selected_id is None:
        ctx.candidates.select(
            candidate_id, reason="complete_unverified_fallback"
        )
    return ToolResult(
        tool="submit_answer",
        call_id="",
        rc=RC_OK,
        status="passed",
        excerpt=json.dumps(record, ensure_ascii=False),
        meta={"record": record},
    )


@tool("finish_task")
def finish_task(ctx: Ctx, reason: str = ""):
    """Ask the current stage to stop; the workflow graph still chooses the next node."""
    ctx.store["finish_requested"] = reason or "model_finished"
    return ToolResult(
        tool="finish_task",
        call_id="",
        rc=RC_OK,
        status="passed",
        excerpt="finish requested: " + (reason or "model_finished"),
        meta={"reason": reason or "model_finished"},
    )
