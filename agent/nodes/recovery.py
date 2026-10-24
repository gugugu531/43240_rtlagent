"""Shared recovery admission checks without dependencies on workflow actions."""

def stop(state, reason):
    return state.update(action="finish", stop_reason=reason, status="stopped")


def rtl_repair_blocker(ctx, state, *, origin):
    """Keep enough time and a generation slot to execute the proposed RTL repair."""
    reason, remaining, required = "", None, None
    if state["round"] >= state["max_rounds"]:
        reason = "round_limit"
    else:
        auxiliary = ctx.config.runtime.auxiliary
        required = auxiliary.minimum_request_s + auxiliary.acceptance_reserve_s
        remaining = ctx.budget.remaining_s()
        if remaining < required:
            reason = "repair_budget"
    if reason:
        ctx.record.emit(
            "repair_unavailable", "result", origin=origin,
            candidate_id=state["target_id"], reason=reason,
            round=state["round"], max_rounds=state["max_rounds"],
            remaining_s=remaining, required_s=required,
        )
    return reason
