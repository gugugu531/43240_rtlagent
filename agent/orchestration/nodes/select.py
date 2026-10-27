"""Answer selection writes solution.v atomically through CandidateStore."""

from agent.kit import Ctx, State, node


@node("select", reads=["target_id"], writes=[])
def select(ctx: Ctx, state: State) -> State:
    if state.get("target_id"):
        ctx.candidates.select(state["target_id"], reason="single_generate")
    return state


@node("finish", reads=["stop_reason", "status"], writes=["stop_reason", "status"])
def finish(ctx: Ctx, state: State) -> State:
    return state.update(
        stop_reason=state.get("stop_reason") or "single_generate",
        status=state.get("status") or "completed",
    )


@node(
    "repair_decide",
    reads=["has_candidate", "failure_kind", "round", "check_passed", "max_rounds"],
    writes=["action", "stop_reason", "status"],
)
def decide(ctx: Ctx, state: State) -> State:
    max_rounds = state["max_rounds"]
    failure = state.get("failure_kind", "")
    if state.get("has_candidate") and state.get("check_passed") and not failure:
        return state.update(
            action="finish", stop_reason="synth_passed", status="completed"
        )
    retry = failure in ("code", "extraction") and state["round"] < max_rounds
    reason = (
        "round_limit"
        if failure in ("code", "extraction")
        else "verification_unavailable"
        if failure == "environment"
        else failure
    )
    ctx.record.emit(
        "failure_decision",
        "result",
        action="repair" if retry else "stop",
        reason=failure,
        round=state["round"],
    )
    return state.update(
        action="repair" if retry else "finish", stop_reason=reason, status="stopped"
    )
