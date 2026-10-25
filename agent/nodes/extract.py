"""Extract complete RTL without inventing missing text."""

from agent.kit import Ctx, State, node
from agent.rtl.extract import extract_result


@node(
    "rtl_extract",
    reads=["reply_id", "round", "target_id"],
    writes=["target_id", "has_candidate", "feedback", "failure_kind"],
)
def extract(ctx: Ctx, state: State) -> State:
    reply = ctx.store[state["reply_id"]]
    result = extract_result(reply.content, target_module=ctx.task.top)
    candidate = None
    if result.code and result.complete and result.target_module_found and not result.suspected_truncation:
        candidate = ctx.candidates.create(
            result.code,
            call_id=reply.call_id,
            round=state["round"],
            parent_id=state.get("target_id"),
            source_stage="repair" if state.get("target_id") else "generate",
            extraction_status=result.status,
            finish_reason=reply.finish_reason,
        )
        if ctx.candidates.selected_id is None:
            ctx.candidates.select(candidate.id, reason="complete_fallback")
    ctx.record.emit(
        "extract",
        "result",
        source_call_id=reply.call_id,
        status=result.status,
        diagnostics=list(result.diagnostics),
        candidate_id=candidate.id if candidate else None,
        complete_new_draft=candidate is not None,
        parent_id=state.get('target_id'),
        finish_reason=reply.finish_reason,
        retained_candidate_id=state.get('target_id') if candidate is None else None,
    )
    return state.update(
        target_id=candidate.id if candidate else state.get("target_id"),
        has_candidate=candidate is not None,
        feedback=state.get("feedback", "")
        if candidate
        else "[extraction] " + "; ".join(result.diagnostics),
        failure_kind="" if candidate else "extraction",
    )
