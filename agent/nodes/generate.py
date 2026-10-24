"""Generation is one model call; retry decisions belong to the graph."""

from contextlib import nullcontext
from typing import Literal

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
    skill_ids: list[str] = [],
    skill_phases: list[Literal["generate", "repair"]] = ["generate", "repair"],
    rag: bool = False,
    knowledge_max_tokens: int = 2048,
) -> State:
    # Evidence belongs to one next-generation attempt, including when knowledge
    # is disabled or extraction later fails. Never reuse a previous check.
    evidence = ctx.store.pop("repair_check", None)
    ctx.store["knowledge_rag_enabled"] = rag
    parent = ctx.candidates.get(state["target_id"]) if state.get("target_id") else None
    messages = ctx.prompts.render(
        prompt,
        task=ctx.task,
        feedback=state.get("feedback", ""),
        parent=parent,
        plan=ctx.store.get("plan"),
    )
    assembly = None
    window = ctx.llm.request_window(timeout_s) if skill_ids or rag else nullcontext()
    with window:
        if skill_ids or rag:
            from agent.knowledge.context import prepare

            messages, assembly = prepare(
                ctx, messages, parent, evidence,
                skill_ids=skill_ids, skill_phases=skill_phases, rag=rag,
                max_tokens=max_tokens, max_extra_tokens=knowledge_max_tokens,
            )
        reply = ctx.llm.chat(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
            timeout_s=timeout_s,
            purpose="repair" if parent else "generate",
        )
    if assembly is not None:
        ctx.record.emit(
            "knowledge", "model_result", assembly_id=assembly["assembly_id"],
            messages_sha256=assembly["messages_sha256"], call_id=reply.call_id,
        )
    ctx.store[reply.call_id] = reply
    return state.update(reply_id=reply.call_id, round=state.get("round", 0) + 1)
