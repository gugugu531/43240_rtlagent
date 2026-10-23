"""Generation is one model call; retry decisions belong to the graph."""

from agent.kit import Ctx, State, node


@node(
    "rtl_generate",
    reads=["feedback", "target_id", "round"],
    writes=["reply_id", "round"],
)
def generate(
    ctx: Ctx,
    state: State,
    *,
    temperature: float = 0.2,
    max_tokens: int = 4096,
    top_p: float = 1.0,
    timeout_s: float = 180,
    prompt: str = "repair.j2",
) -> State:
    parent = ctx.candidates.get(state["target_id"]) if state.get("target_id") else None
    messages = ctx.prompts.render(
        prompt,
        task=ctx.task,
        feedback=state.get("feedback", ""),
        parent=parent,
        plan=ctx.store.get("plan"),
    )
    reply = ctx.llm.chat(
        messages,
        temperature=temperature,
        max_tokens=max_tokens,
        top_p=top_p,
        timeout_s=timeout_s,
        purpose="repair" if parent else "generate",
    )
    ctx.store[reply.call_id] = reply
    return state.update(reply_id=reply.call_id, round=state.get("round", 0) + 1)
