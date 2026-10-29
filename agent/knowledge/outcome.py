"""Join observed lineage without inventing an external benchmark score."""
from collections import Counter
import json
from .assets import sha256


def classify_attempt(*, delivered, checker_accepted=None, new_hash=None,
                     scored_hash=None, functional_pass=None, environment_error=None,
                     quarantine_reason=None):
    """Score only an explicitly bound NEW draft, never a fallback candidate."""
    if environment_error:
        outcome = 'environment_failure'
    elif delivered is False:
        outcome = 'not_delivered'
    elif delivered is not True:
        outcome = 'delivery_unknown'
    elif checker_accepted is False:
        outcome = 'checker_rejected'
    elif checker_accepted is not True:
        outcome = 'checker_unknown'
    elif not new_hash or not scored_hash:
        outcome = 'new_draft_unscored'
    elif new_hash != scored_hash:
        outcome = 'different_candidate_scored'
    elif type(functional_pass) is not bool:
        outcome = 'functional_result_unknown'
    else:
        outcome = 'new_draft_functional_pass' if functional_pass else 'new_draft_functional_failure'
    attempt_success=True if outcome=='new_draft_functional_pass' else False if outcome in (
        'not_delivered','checker_rejected','new_draft_functional_failure') else None
    return dict(outcome=outcome, new_candidate_sha256=new_hash, scored_candidate_sha256=scored_hash,
                quarantine_reason=quarantine_reason,
                attempt_success=attempt_success,
                eligible_for_attempt_success_rate=not quarantine_reason and attempt_success is not None,
                eligible_for_delivery_rate=not quarantine_reason and not environment_error and type(delivered) is bool,
                effect_comparison_scope='new_draft_functional_score_only; use separate all-attempt success and delivery denominators',
                eligible_for_effect_comparison=not quarantine_reason and outcome in (
                    'new_draft_functional_pass','new_draft_functional_failure'))


def classify_development_result(result):
    """Read explicit experiment fields; legacy unbound scores stay unverified."""
    judge=result.get('judge') or {}
    case=result.get('job',{}).get('case',result.get('case'))
    quarantined='ambiguous_public_selector_contract' if case=='nf-prob062-combinational' else None
    error=result.get('error') or judge.get('tool_error')
    if result.get('checker_failure_kind') in ('environment','checker','timeout','unknown'):
        error=error or result['checker_failure_kind']
    scored_hash=result.get('judge_input_sha256')
    if scored_hash and scored_hash!=result.get('judge_input_sha256_after',scored_hash):
        error='judge_input_changed_during_evaluation'
    accepted=result.get('checker_accepted')
    if judge.get('stages',{}).get('compile') is False:accepted=False
    outcome=classify_attempt(delivered=result.get('complete_new_draft'),checker_accepted=accepted,
        new_hash=result.get('draft_sha256'),scored_hash=scored_hash,
        functional_pass=judge.get('stages',{}).get('simulate'),environment_error=error,
        quarantine_reason=quarantined)
    phases=result.get('delivery',{}).get('phases',[])
    thinking_verified=bool(phases) and all(p.get('thinking') is True for p in phases)
    outcome.update(thinking_on_verified=thinking_verified,environment_error=error)
    if not thinking_verified:
        for key in ('eligible_for_effect_comparison','eligible_for_attempt_success_rate','eligible_for_delivery_rate'):
            outcome[key]=False
    return outcome


def _delivery_state(candidate, deliveries, call_counts):
    """Creation alone is not validation; legacy adaptive events bind by call ID."""
    observed = None
    call_id = candidate.get('source_call_id')
    for delivery in deliveries:
        if type(delivery.get('complete_new_draft')) is not bool:
            continue
        if 'candidate_id' in delivery:
            if delivery['candidate_id'] != candidate['candidate_id']:
                continue
            if delivery.get('source_call_id') is not None and delivery['source_call_id'] != call_id:
                continue
        elif not (call_id and call_counts[call_id] == 1 and delivery.get('source_call_id') == call_id):
            continue
        observed = delivery['complete_new_draft']
    return observed


def summarize(trace_path, solution_path):
    rows = [json.loads(line) for line in trace_path.read_text().splitlines() if line.strip()]
    selections = [r for r in rows if r['tool'] == 'select' and r['event'] == 'result']
    creations = [r for r in rows if r['tool'] == 'candidate' and r['event'] == 'create']
    deliveries = [r for r in rows if r['tool'] == 'extract']
    call_counts = Counter(r.get('source_call_id') for r in creations)
    completeness = {r['candidate_id']: _delivery_state(r, deliveries, call_counts) for r in creations}
    complete = [r for r in creations if completeness[r['candidate_id']] is True]
    selected = selections[-1] if selections else {}
    latest = complete[-1] if complete else {}
    selected_id = selected.get('candidate_id')
    selected_complete = completeness.get(selected_id)
    solution_hash = sha256(solution_path.read_bytes())
    checks=[r for r in rows if r['tool'] in ('interface','lint','synth','functional') and r['event']=='result']
    attempts=[]
    for delivery in deliveries:
        if type(delivery.get('complete_new_draft')) is not bool:continue
        candidate=next((c for c in creations if c['candidate_id']==delivery.get('candidate_id')
                        and c.get('source_call_id')==delivery.get('source_call_id')), {})
        if not candidate and 'candidate_id' not in delivery and call_counts[delivery.get('source_call_id')]==1:
            candidate=next(c for c in creations if c.get('source_call_id')==delivery.get('source_call_id'))
        observed=[c for c in checks if c.get('candidate_id')==candidate.get('candidate_id')] if candidate else []
        environment=next((c.get('failure_kind') for c in observed
                          if c.get('failure_kind') in ('environment','checker','timeout')),None)
        rejected=any(c.get('status')=='failed' and (c['tool']!='interface' or c.get('blocking')) for c in observed)
        approved=any(s.get('candidate_id')==candidate.get('candidate_id') and
                     s.get('reason') in ('checks_passed','synth_passed') for s in selections) if candidate else False
        attempts.append(dict(source_call_id=delivery.get('source_call_id'),
            **classify_attempt(delivered=delivery['complete_new_draft'],
                checker_accepted=False if rejected else True if approved else None,
                new_hash=candidate.get('code_hash'),environment_error=environment)))
    extracted_calls={a['source_call_id'] for a in attempts}
    for row in rows:
        if row['tool']=='llm' and row['event']=='failed' and row.get('call_id') not in extracted_calls:
            attempts.append(dict(source_call_id=row.get('call_id'),stage=row.get('purpose'),
                **classify_attempt(delivered=None,environment_error=row.get('error_kind') or 'model_request_failed')))
    return {'schema_version': 2, 'selected_candidate_id': selected_id,
            'selected_candidate_complete': selected_complete,
            'latest_complete_candidate_id': latest.get('candidate_id'),
            'selected_latest_complete': (selected_id == latest.get('candidate_id')
                                         if selected_complete is not None else None),
            'solution_sha256': solution_hash,
            'solution_matches_selection': bool(selected and solution_hash == selected.get('code_hash')),
            'selection_reason': selected.get('reason'), 'external_score': None,
            'attempts': attempts, 'attempt_counts': dict(Counter(a['outcome'] for a in attempts)),
            'external_scored_candidate_id': None,
            'assemblies': [r for r in rows if r['tool'] == 'knowledge' and r['event'] == 'assembly'],
            'deliveries': deliveries,
            'checks': [r for r in rows if (r['tool'] == 'knowledge' and r['event'] == 'check_evidence')
                       or (r['tool'] in ('interface', 'lint', 'synth', 'functional') and r['event'] == 'result')],
            'costs': [r for r in rows if r.get('elapsed_s') is not None or r.get('tokens_out') is not None],
            'model_results': [r for r in rows if r['tool'] == 'knowledge' and r['event'] == 'model_result']}
