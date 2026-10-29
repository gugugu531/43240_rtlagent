"""Whole-piece solver context packing using the existing model tokenizer.

The optional-piece policy is adapted from the MIT-licensed upstream
agent/prompts/context.py at fb1c2803e5db0f32b59b9ba9100877f2a0d26412.
"""

import json
import uuid
import time
from contextlib import nullcontext

from .assets import card_text, load_assets, sha256
from .retrieval import retrieve
from .policy import modes, select_skills

NOTICE = (
    "The following material provides optional general methods, not task requirements or checker conclusions. "
    "Use it only when applicable. The original task, interface, and current tool evidence take precedence. "
    "Do not invent unspecified behavior or omit required modules. "
    "Continue to follow the RTL output format specified above."
)


def messages_hash(messages):
    return sha256(json.dumps(messages, ensure_ascii=False, sort_keys=True))


def _prepare(ctx, messages, parent, evidence, *, skill_ids, skill_phases, rag, max_tokens, max_extra_tokens, diagnostic_first=False, skill_mode=None, rag_mode=None, retrieval_options=None, automatic=False, raw_feedback=None):
    started = time.monotonic()
    sm, rm = modes(skill_mode, rag_mode, skill_ids=skill_ids, rag=rag)
    if len(skill_ids) > 2 or len(set(skill_ids)) != len(skill_ids):
        raise ValueError("select at most two distinct skills")
    if not skill_phases or len(set(skill_phases)) != len(skill_phases):
        raise ValueError("skill_phases must be nonempty and unique")
    if type(max_extra_tokens) is not int or not 0 <= max_extra_tokens <= 8192:
        raise ValueError("knowledge_max_tokens must be in 0..8192")
    if type(diagnostic_first) is not bool:
        raise ValueError("diagnostic_first must be boolean")
    phase = "repair" if parent is not None else "generate"
    key = ("knowledge_assets", bool(skill_ids) and sm != 'off', False)
    if key not in ctx.store:
        ctx.store[key] = load_assets(skills=key[1], rag=False)
        ctx.record.emit("knowledge", "resources", resources=ctx.store[key]["resources"])
    assets = ctx.store[key]
    pieces = []
    selected, rejected = select_skills(assets, skill_ids, skill_phases, automatic=automatic) if sm != 'off' else ([], [])
    for skill_id in selected:
        skill, body = assets["skills"][skill_id]
        pieces.append({
            "id": skill_id, "version": skill.version, "kind": "skill",
            "text": f"[Skill {skill_id}@{skill.version}]\n{body}",
            "eligible": phase in skill_phases, "resource_sha256": skill.resource.sha256,
        })
    retrieval = {"reason": "disabled"}
    if rm != 'off':
        if parent is None and (retrieval_options or {}).get('pre_generation', False):
            from .pregen import retrieve_spec
            cards, retrieval = retrieve_spec(ctx.task.prompt, ctx.task.interface,
                                            retrieval_options or {}, messages)
        elif parent is not None and (retrieval_options or {}).get('research_feedback', False):
            from .feedback import retrieve_feedback
            cards, retrieval = retrieve_feedback(ctx.task, evidence, parent,
                                                  retrieval_options or {}, messages)
        else:
            from .runtime import retrieve_runtime
            cards, retrieval = retrieve_runtime(evidence, parent, retrieval_options or {}, messages, raw_feedback)
        from .research import scope_guard
        for card in cards:
            if not scope_guard(card['card_id']):
                retrieval.setdefault('rejected', []).append({'id': card['card_id'], 'reason': 'card_frozen_at_assembly', 'decision_class': 'not_needed'})
                continue
            if card.get('activation_state','restricted') not in ('restricted','legacy_policy'):
                retrieval.setdefault('rejected',[]).append({'id':card['card_id'],'reason':'catalog_shadow_or_hold_at_assembly','decision_class':'unknown'})
                continue
            stage='pre_generation' if parent is None else retrieval.get('stage','post_diagnostic')
            if card.get('injection_stages') is not None and stage not in card['injection_stages']:
                retrieval.setdefault('rejected',[]).append({'id':card['card_id'],'reason':'card_stage_not_authorized_at_assembly','decision_class':'unknown'})
                continue
            pieces.append({
                "id": card['card_id'], "version": card['version'], "kind": "knowledge_card",
                "text": card['projection_text'], "eligible": True,
                "resource_sha256": sha256(json.dumps(card, sort_keys=True)),
            })
    if diagnostic_first and parent is not None:
        pieces.sort(key=lambda piece: piece["kind"] != "knowledge_card")
    assembly_id = uuid.uuid4().hex
    report = {
        "assembly_id": assembly_id, "phase": phase,
        "parent_id": parent.id if parent else None,
        "parent_hash": parent.code_hash if parent else None,
        "required_messages_sha256": messages_hash(messages),
        "output_reserve": max_tokens, "max_extra_tokens": max_extra_tokens,
        "diagnostic_first": diagnostic_first,
        "skill_mode": sm, "rag_mode": rm, "skill_selected": selected, "skill_rejected": rejected,
        "resources": assets["resources"], "retrieval": retrieval, "pieces": [],
    }
    packed = [dict(message) for message in messages]
    base_count = None
    def active(piece):
        return (sm if piece['kind'] == 'skill' else rm) == 'on'
    if any(piece["eligible"] and active(piece) for piece in pieces) and max_extra_tokens:
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
        elif not active(piece):
            reason = "shadow_only"
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
    report.update(messages_sha256=messages_hash(packed), packed_tokens=count,
                  sent=[p['id'] for p in report['pieces'] if p['status'] == 'included'],
                  elapsed_ms=round((time.monotonic()-started)*1000, 3))
    retrieval['actually_sent'] = [p['id'] for p in report['pieces']
                                if p['status'] == 'included' and p['kind'] == 'knowledge_card']
    ctx.record.write_json(f"knowledge/{assembly_id}.json", report)
    ctx.record.emit("knowledge", "assembly", **report)
    return packed, report


def prepare(ctx, messages, parent, evidence, **options):
    """Preflight rejects configuration errors; optional runtime failures fail closed."""
    from agent.llm.client import ModelError
    try:
        remaining = ctx.llm.optional_preparation_budget_s() if hasattr(ctx.llm, 'optional_preparation_budget_s') else None
        if remaining is not None:
            if remaining < 0.01:
                raise ModelError('no optional preparation time', kind='timeout')
            retrieval_options = dict(options.get('retrieval_options') or {})
            retrieval_options['embedding_timeout_s'] = min(retrieval_options.get('embedding_timeout_s', 2.0), remaining / 2)
            options['retrieval_options'] = retrieval_options
        with ctx.llm.request_window(remaining) if remaining is not None else nullcontext():
            return _prepare(ctx, messages, parent, evidence, **options)
    except (ModelError, OSError, ValueError) as error:
        report = {'assembly_id': uuid.uuid4().hex, 'reason': 'optional_knowledge_failure',
                  'error': type(error).__name__, 'pieces': [], 'sent': [],
                  'required_messages_sha256': messages_hash(messages),
                  'messages_sha256': messages_hash(messages)}
        ctx.record.emit('knowledge', 'assembly', **report)
        ctx.record.write_json(f"knowledge/{report['assembly_id']}.json", report)
        return messages, report
