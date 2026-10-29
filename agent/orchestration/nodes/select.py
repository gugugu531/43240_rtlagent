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
