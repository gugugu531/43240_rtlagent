"""Explicit opt-in repair stages. Thinking stays on; costs, not success, are bounded."""
from copy import deepcopy
import json
from agent.knowledge.context import messages_hash
from agent.knowledge.assets import sha256
from agent.llm.structured import strict_json
from agent.runtime.allowance import CompletionLedger, AllowanceError


def thinking_generation(original):
    generation = deepcopy(original)
    kwargs = dict(generation.get('chat_template_kwargs') or {})
    if generation.get('enable_thinking') is False:
        raise ValueError('conflicting top-level thinking control')
    for controls in (generation, kwargs):
        if (controls.get('reasoning_budget') == 0 or controls.get('reasoning_effort') == 'none'
                or controls.get('reasoning') in (False, 'off')):
            raise ValueError('thinking may not be disabled')
    kwargs['enable_thinking'] = True
    generation['chat_template_kwargs'] = kwargs
    return generation


def validate_plan(reply, parent):
    if parent is None or sha256(parent.code) != parent.code_hash:
        return None, 'invalid_candidate_identity'
    if reply.finish_reason != 'stop' or reply.tool_calls:
        return None, 'incomplete_plan'
    try:
        value = strict_json(reply.content)
        if not isinstance(value, dict) or set(value) != {
                'candidate_sha256', 'established_facts', 'edits', 'boundary_check', 'uncertainties'}:
            raise ValueError('schema')
        if value['candidate_sha256'] != parent.code_hash:
            return None, 'stale_plan'
        for field, limit in (('established_facts', 4), ('uncertainties', 2)):
            if not isinstance(value[field], list) or len(value[field]) > limit or any(
                    not isinstance(s, str) or not s.strip() or len(s) > 600 for s in value[field]):
                raise ValueError('schema')
        if not isinstance(value['edits'], list) or len(value['edits']) > 4:
            raise ValueError('schema')
        spans = []
        for edit in value['edits']:
            if not isinstance(edit, dict) or set(edit) != {'old', 'new', 'reason'} or any(
                    not isinstance(s, str) or len(s) > 1600 for s in edit.values()):
                raise ValueError('schema')
            if not edit['old'].strip() or not edit['reason'].strip() or parent.code.count(edit['old']) != 1:
                return None, 'unbound_or_ambiguous_edit'
            start = parent.code.index(edit['old']); end = start + len(edit['old'])
            if any(start < b and a < end for a,b in spans):
                return None, 'overlapping_edits'
            spans.append((start,end))
        if not isinstance(value['boundary_check'], str) or not 0 < len(value['boundary_check']) <= 800:
            raise ValueError('schema')
        return value, 'structure_valid_semantics_unproven'
    except (ValueError, TypeError, KeyError):
        return None, 'invalid_plan'


def complete(ctx, parent, feedback, delivery_messages, *, max_tokens, timeout_s,
             temperature=0., top_p=1.):
    if parent is None or type(max_tokens) is not int or max_tokens < 1024:
        raise ValueError('staged repair requires a current candidate and >=1024 total output tokens')
    # Reject before any call if no followup/check window exists. A token reservation
    # includes thinking AND final content; it does not guarantee code will be produced.
    ledger = CompletionLedger(ctx.budget, ctx.record, max_calls=2, max_output_tokens=max_tokens)
    plan_tokens = max_tokens // 4
    original = deepcopy(ctx.llm.generation)
    enabled = thinking_generation(original)
    phases = []
    def call(stage, messages, tokens, seconds, followup):
        permit = ledger.reserve(stage, tokens, seconds, followup_s=followup, optional=True)
        if permit is None:
            raise AllowanceError(ledger.last_denial)
        ctx.llm.generation = deepcopy(enabled)
        with ctx.llm.permitted(permit):
            reply = ctx.llm.chat(messages, max_tokens=tokens, timeout_s=seconds,
                                 temperature=temperature, top_p=top_p, purpose=stage)
        phases.append(dict(stage=stage, call_id=reply.call_id, thinking=True,
                           messages_sha256=messages_hash(messages), finish_reason=reply.finish_reason,
                           final_characters=len(reply.content)))
        return reply
    try:
        analysis = ctx.prompts.render('repair_analysis.j2', task=ctx.task, parent=parent, feedback=feedback)
        planning = call('repair_plan', analysis, plan_tokens, timeout_s*.25, timeout_s*.75+10)
        plan, reason = validate_plan(planning, parent)
        ctx.record.emit('delivery', 'plan_validation', reason=reason, forwarded=plan is not None,
                        candidate_id=parent.id, candidate_hash=parent.code_hash, source_call_id=planning.call_id)
        final = deepcopy(delivery_messages)
        if plan is not None:
            final[-1]['content'] += ('\n\nStructurally checked planning DATA (not verified conclusions). '
                'The original task takes precedence; verify edits before delivering complete RTL:\n' + json.dumps(plan))
        reply = call('repair_delivery', final, max_tokens-plan_tokens, timeout_s*.75, 10)
        return reply, dict(phases=phases, plan_validation=reason, plan_forwarded=plan is not None,
                           messages_sha256=messages_hash(final), final_delivery_guaranteed=False)
    finally:
        ctx.llm.generation = original
        ctx.record.emit('delivery', 'budget', phases=phases, allowance=ledger.snapshot(),
                        final_delivery_guaranteed=False, raw_thinking_forwarded=False)
