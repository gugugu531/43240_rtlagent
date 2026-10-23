"""The unmodified official baseline's messages, sampling and extraction."""

import baseline as official
from agent.kit import Ctx, State, node


@node("baseline_generate", reads=["round"], writes=["reply_id", "round"])
def generate(ctx: Ctx, state: State) -> State:
    # Only prompt.txt is loaded by the task reader. Parsed interface is already
    # present in that text and must not be appended a second time.
    prompt = ctx.task.raw_prompt if ctx.task.raw_prompt is not None else ctx.task.prompt
    ctx.record.emit(
        "prompt_resources",
        "baseline",
        source="baseline.py",
        script_sha256=official.self_sha256(),
        generation=official.load_generation(),
    )
    reply = ctx.llm.chat(
        [
            {"role": "system", "content": official.SYS["rtl"]},
            {"role": "user", "content": prompt},
        ],
        max_tokens=official.MAX_TOKENS,
        temperature=official.TEMPERATURE,
        top_p=official.TOP_P,
        timeout_s=official.TIMEOUT_S,
        baseline=True,
    )
    ctx.store[reply.call_id] = reply
    return state.update(reply_id=reply.call_id, round=state.get("round", 0) + 1)


@node(
    "baseline_extract",
    reads=["reply_id", "round", "target_id"],
    writes=["target_id", "has_candidate"],
)
def extract(ctx: Ctx, state: State) -> State:
    reply = ctx.store[state["reply_id"]]
    code = official.extract(reply.content, "rtl")
    candidate = ctx.candidates.create(
        code,
        call_id=reply.call_id,
        round=state["round"],
        parent_id=state.get("target_id"),
        finish_reason=reply.finish_reason,
    )
    ctx.record.emit(
        "extract",
        "result",
        source_call_id=reply.call_id,
        candidate_id=candidate.id,
        source="baseline.py",
        empty_content=not reply.content,
    )
    return state.update(target_id=candidate.id, has_candidate=True)
