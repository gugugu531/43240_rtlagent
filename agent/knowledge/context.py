"""Whole-piece solver context packing using the existing model tokenizer.

The optional-piece policy is adapted from the MIT-licensed upstream
agent/prompts/context.py at fb1c2803e5db0f32b59b9ba9100877f2a0d26412.
"""

import json
import uuid

from .assets import card_text, load_assets, sha256
from .retrieval import retrieve

NOTICE = (
    "以下是可选的通用参考方法，不是题目要求或检查结论。仅在适用时使用；"
    "原题、接口和本次工具证据优先。不得补猜未指定行为，也不得省略所需模块。"
    "最终仍须遵循上文的 RTL 输出格式。"
)


def messages_hash(messages):
    return sha256(json.dumps(messages, ensure_ascii=False, sort_keys=True))


def prepare(ctx, messages, parent, evidence, *, skill_ids, skill_phases, rag, max_tokens, max_extra_tokens):
    if len(skill_ids) > 2 or len(set(skill_ids)) != len(skill_ids):
        raise ValueError("select at most two distinct skills")
    if not skill_phases or len(set(skill_phases)) != len(skill_phases):
        raise ValueError("skill_phases must be nonempty and unique")
    if type(max_extra_tokens) is not int or not 0 <= max_extra_tokens <= 8192:
        raise ValueError("knowledge_max_tokens must be in 0..8192")
    phase = "repair" if parent is not None else "generate"
    key = ("knowledge_assets", bool(skill_ids), rag)
    if key not in ctx.store:
        ctx.store[key] = load_assets(skills=bool(skill_ids), rag=rag)
        ctx.record.emit("knowledge", "resources", resources=ctx.store[key]["resources"])
    assets = ctx.store[key]
    pieces, groups = [], set()
    for skill_id in skill_ids:
        if skill_id not in assets["skills"]:
            raise ValueError("unknown skill: " + skill_id)
        skill, body = assets["skills"][skill_id]
        if skill.conflict_group in groups:
            raise ValueError("conflicting skill methods: " + skill.conflict_group)
        groups.add(skill.conflict_group)
        if not set(skill_phases).issubset(skill.phases):
            raise ValueError("unsupported phase for skill: " + skill_id)
        pieces.append({
            "id": skill_id, "version": skill.version, "kind": "skill",
            "text": f"[Skill {skill_id}@{skill.version}]\n{body}",
            "eligible": phase in skill_phases, "resource_sha256": skill.resource.sha256,
        })
    retrieval = {"reason": "disabled"}
    if rag:
        cards, retrieval = retrieve(assets["cards"], evidence, parent)
        for card in cards:
            pieces.append({
                "id": card.id, "version": card.version, "kind": "knowledge_card",
                "text": card_text(card), "eligible": True,
                "resource_sha256": sha256(card.model_dump_json()),
            })
    assembly_id = uuid.uuid4().hex
    report = {
        "assembly_id": assembly_id, "phase": phase,
        "parent_id": parent.id if parent else None,
        "parent_hash": parent.code_hash if parent else None,
        "required_messages_sha256": messages_hash(messages),
        "output_reserve": max_tokens, "max_extra_tokens": max_extra_tokens,
        "resources": assets["resources"], "retrieval": retrieval, "pieces": [],
    }
    packed = [dict(message) for message in messages]
    base_count = None
    if any(piece["eligible"] for piece in pieces) and max_extra_tokens:
        base_count = ctx.llm.tokenize(messages)
    report["required_tokens"] = base_count
    limit = ctx.config.services.model.max_model_len
    count, seen, included = base_count, set(), False
    for piece in pieces:
        text = piece["text"]
        digest = sha256(text)
        reason = "included"
        if not piece["eligible"]:
            reason = "phase_mismatch"
        elif not max_extra_tokens:
            reason = "knowledge_budget"
        elif digest in seen or any(text in message["content"] for message in messages):
            reason = "duplicate"
        elif base_count + max_tokens > limit:
            reason = "required_output_reserve"
        if reason == "included":
            trial = [dict(message) for message in packed]
            trial[-1]["content"] += "\n\n" + (NOTICE + "\n\n" if not included else "") + text
            next_count = ctx.llm.tokenize(trial)
            if next_count + max_tokens > limit:
                reason = "context_limit"
            elif next_count - base_count > max_extra_tokens:
                reason = "knowledge_budget"
            else:
                packed, count, included = trial, next_count, True
                seen.add(digest)
        report["pieces"].append({
            k: v for k, v in piece.items() if k not in ("text", "eligible")
        } | {"text_sha256": digest, "status": reason})
    report.update(messages_sha256=messages_hash(packed), packed_tokens=count)
    ctx.record.write_json(f"knowledge/{assembly_id}.json", report)
    ctx.record.emit("knowledge", "assembly", **report)
    return packed, report
