"""Generation with optional knowledge-base retrieval for the RAG routes."""

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
    skill_mode: Literal["off", "shadow", "on"] | None = None,
    rag_mode: Literal["off", "shadow", "on"] | None = None,
    retrieval: dict = {},
    knowledge_max_tokens: int = 2048,
) -> State:
    from agent.domain.knowledge.policy import modes
    from agent.domain.knowledge import guided as knowledge

    sm, rm = modes(skill_mode, rag_mode, skill_ids=skill_ids, rag=rag)
    ctx.store["knowledge_rag_enabled"] = rm != "off"
    parent = ctx.candidates.get(state["target_id"]) if state.get("target_id") else None
    messages = ctx.prompts.render(
        prompt,
        task=ctx.task,
        feedback=state.get("feedback", ""),
        parent=parent,
        plan=ctx.store.get("plan"),
    )
    report = {"mode": rm, "skills": sm, "strategy": retrieval.get("strategy", "bm25")}
    if rm != "off":
        query = ctx.task.prompt + "\n" + ctx.task.interface
        mode = "rag" if rm in ("on", "shadow") else "off"
        try:
            cards, found = knowledge.retrieve(
                query,
                mode=mode,
                limit=retrieval.get("retrieve_k", 5),
                strategy=retrieval.get("strategy", "bm25"),
                embedding_url=retrieval.get("embedding_url", ""),
                embedding_timeout_s=retrieval.get("embedding_timeout_s", 2.0),
            )
            report.update(found)
        except (OSError, ValueError, RuntimeError) as error:
            report.update(error=type(error).__name__ + ": " + str(error), selected=[])
            cards = []
        if rm == "on" and cards:
            pieces = []
            used = 0
            for card in cards[: retrieval.get("inject_k", 1)]:
                text = knowledge.card_text(card)
                if used + len(text) > knowledge_max_tokens:
                    break
                pieces.append(text)
                used += len(text)
            if pieces:
                messages[-1]["content"] += (
                    "\n\n## Optional knowledge (not task requirements)\n\n"
                    + "\n\n".join(pieces)
                )
                report["sent"] = [card["card_id"] for card in cards[: len(pieces)]]
        ctx.record.emit("knowledge", "retrieval", **report)
    with ctx.llm.request_window(timeout_s):
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
