"""Single-call generation or explicit bounded thinking-on repair stages."""

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
    skill_mode: Literal['off', 'shadow', 'on'] | None = None,
    rag_mode: Literal['off', 'shadow', 'on'] | None = None,
    retrieval: dict = {},
    knowledge_max_tokens: int = 2048,
    delivery_mode: Literal['single', 'thinking_staged'] = 'single',
) -> State:
    # Evidence belongs to one next-generation attempt, including when knowledge
    # is disabled or extraction later fails. Never reuse a previous check.
    evidence = ctx.store.pop("repair_check", None)
    from agent.domain.knowledge.policy import modes
    sm, rm = modes(skill_mode, rag_mode, skill_ids=skill_ids, rag=rag)
    ctx.store["knowledge_rag_enabled"] = rm != 'off'
    parent = ctx.candidates.get(state["target_id"]) if state.get("target_id") else None
    messages = ctx.prompts.render(
        prompt,
        task=ctx.task,
        feedback=state.get("feedback", ""),
        parent=parent,
        plan=ctx.store.get("plan"),
    )
    assembly = None
    window = ctx.llm.request_window(timeout_s)
    with window:
        from agent.domain.knowledge.context import prepare

        messages, assembly = prepare(
            ctx, messages, parent, evidence,
            skill_ids=skill_ids, skill_phases=skill_phases, rag=rag,
            max_tokens=max_tokens, max_extra_tokens=knowledge_max_tokens,
            skill_mode=sm, rag_mode=rm, retrieval_options=retrieval,
            raw_feedback=state.get('feedback', ''),
        )
        if delivery_mode == 'thinking_staged' and parent is not None:
            from agent.llm.repair_delivery import complete
            reply, delivery = complete(ctx, parent, state.get('feedback',''), messages,
                max_tokens=max_tokens, timeout_s=timeout_s, temperature=temperature, top_p=top_p)
            ctx.record.emit('delivery', 'result', **delivery)
            if assembly is not None:
                assembly = dict(assembly, messages_sha256=delivery['messages_sha256'])
        elif delivery_mode in ('single', 'thinking_staged'):
            original = ctx.llm.generation
            try:
                if delivery_mode == 'thinking_staged':
                    from agent.llm.repair_delivery import thinking_generation
                    ctx.llm.generation = thinking_generation(original)
                reply = ctx.llm.chat(
                    messages, temperature=temperature, max_tokens=max_tokens,
                    top_p=top_p, timeout_s=timeout_s,
                    purpose="repair" if parent else "generate",
                )
            finally:
                ctx.llm.generation = original
        else:
            raise ValueError('unknown delivery mode')
    if assembly is not None:
        ctx.record.emit(
            "knowledge", "model_result", assembly_id=assembly["assembly_id"],
            messages_sha256=assembly["messages_sha256"], call_id=reply.call_id,
        )
    ctx.store[reply.call_id] = reply
    return state.update(reply_id=reply.call_id, round=state.get("round", 0) + 1)
