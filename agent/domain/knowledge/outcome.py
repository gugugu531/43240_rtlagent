"""Join observed lineage without inventing an external benchmark score."""
from collections import Counter
import json
import re
from .assets import sha256


def classify_attempt(*, delivered, checker_accepted=None, new_hash=None,
                     scored_hash=None, functional_pass=None, environment_error=None,
                     quarantine_reason=None, failure_outcome=None):
    """Score only an explicitly bound NEW draft, never a fallback candidate."""
    if environment_error:
        outcome = 'environment_failure'
    elif failure_outcome:
        outcome = failure_outcome
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
                eligible_for_delivery_rate=not (quarantine_reason or environment_error or failure_outcome)
                and type(delivered) is bool,
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


_GUIDED_RTL_STAGE = re.compile(r'(?:solve(?:_recovery)?|repair_structure|repair_behavior)(?:_[0-9]+)?')


def _legacy_guided_deliveries(rows, explicit_calls):
    """Recover pre-extract-event evidence from each serial guided request."""
    deliveries = {}
    call_id = stage = extraction_status = None
    for row in rows:
        tool, event = row['tool'], row['event']
        if tool == 'llm':
            call_id = stage = extraction_status = None
            purpose = row.get('purpose') or ''
            if event == 'finished' and purpose.startswith('guided_'):
                label = purpose.removeprefix('guided_')
                if _GUIDED_RTL_STAGE.fullmatch(label):
                    call_id = row.get('call_id')
                    # Old multi-repair artifacts sometimes omit the attempt number.
                    stage = re.sub(r'_[0-9]+$', '', label)
            continue
        if not call_id or call_id in explicit_calls:
            continue
        if tool == 'guided' and event == 'artifact':
            name, _, suffix = (row.get('name') or '').rpartition('-')
            if re.sub(r'_[0-9]+$', '', name) != stage:
                continue
            if suffix == 'extraction':
                extraction_status = row.get('status')
            elif suffix == 'failure':
                deliveries[call_id] = dict(
                    source_call_id=call_id, candidate_id=None, complete_new_draft=False,
                    status=extraction_status, source_stage='guided_' + name,
                )
        elif (tool == 'candidate' and event == 'create'
              and row.get('source_call_id') == call_id and row.get('candidate_id')
              and re.sub(r'_[0-9]+$', '', row.get('source_stage') or '') == 'guided_' + stage
              and extraction_status == 'ok' and row.get('extraction_status') == 'ok'):
            deliveries[call_id] = dict(
                source_call_id=call_id, candidate_id=row['candidate_id'], complete_new_draft=True,
                status=extraction_status, source_stage=row['source_stage'],
            )
    return list(deliveries.values())


def _model_failure(row, budget_stop):
    kind = row.get('error_kind')
    if kind == 'interrupted':
        if row.get('error_type') in ('Deadline', 'BudgetExhausted') and budget_stop:
            return budget_stop
        return 'interrupted'
    if kind == 'timeout':
        return 'model_timeout'
    if kind == 'environment':
        return 'environment_failure'
    return 'model_request_failed'


def _check_evidence(checks, candidate):
    """Accept old flat checks and the current Ctx.call envelope for this exact draft."""
    for check in checks:
        output = check.get('output')
        output = output if isinstance(output, dict) else {}
        if check.get('candidate_id', output.get('candidate_id')) != candidate['candidate_id']:
            continue
        details = output.get('details') or check.get('details') or {}
        check_hash = details.get('candidate_hash')
        if not check_hash or check_hash == candidate.get('code_hash'):
            yield {**check, **output}


def _guided_acceptance(verification, candidate):
    """Interpret the final internal check only for its recorded candidate and checker."""
    candidate_hash = candidate.get('code_hash')
    if (not candidate_hash or verification.get('candidate_id') != candidate.get('candidate_id')
            or verification.get('candidate_hash') != candidate_hash
            or verification.get('structural_passed') is not True
            or verification.get('checker_disputed') is not False
            or verification.get('expectations_revised') is not False):
        return None
    method = verification.get('method')
    if method == 'structural':
        return True
    bits = verification.get('compared_bits')
    if (method != 'table' or type(bits) is not int or bits <= 0
            or not all(isinstance(verification.get(k), str) and verification[k]
                       for k in ('checker_hash', 'checker_version'))):
        return None
    status = verification.get('behavior_status')
    if status == 'passed' and verification.get('functional_passed') is True:
        return True
    if status == 'failed' and verification.get('functional_passed') is False:
        return False
    return None


def _trace_rows(path):
    """A process killed mid-write can leave one unfinished JSONL record at EOF."""
    rows = []
    with path.open('rb') as stream:
        for line in stream:
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    if line.endswith(b'\n'):
                        raise
    return rows


def _submission_outcome(rows, published_id, solution_hash, solution, last_write, stop_reason):
    outcome = dict(submission_mode=None, submission_reason=None, submission_finalized=None,
                   fallback_basis=None, submission_structure_status=None)
    registered = False
    for row in reversed(rows):
        if row['tool'] == 'submission' and row.get('policy') == 'author_decides':
            if row['event'] == 'finalized':
                mode = row.get('mode')
                empty = (solution == b'' and mode == 'fallback' and row.get('delivery') == 'empty'
                         and row.get('target_id') is None and row.get('code_hash') is None)
                writer_matches = (last_write.get('tool') == 'publish' if mode == 'fallback'
                                  else last_write.get('tool') == 'select' and last_write.get('reason') == mode)
                bound = (published_id and row.get('target_id') == published_id
                         and row.get('code_hash') == solution_hash and writer_matches)
                if mode in ('structural_auto', 'author_submit', 'fallback') and (bound or empty):
                    outcome.update(submission_mode=mode, submission_reason=row.get('reason'),
                                   submission_finalized=True, fallback_basis=row.get('fallback_basis'),
                                   submission_structure_status=row.get('structure_status'))
                return outcome
            if row['event'] == 'registered':
                registered = True
            if row['event'] == 'started' and solution == b'' and not registered and not published_id:
                outcome.update(submission_mode='fallback', submission_reason=stop_reason or 'unfinalized_checkpoint',
                               submission_finalized=False, fallback_basis='no_complete_candidate',
                               submission_structure_status='not_checked')
                return outcome
            if (row['event'] == 'decision' and last_write.get('tool') == 'select'
                    and row.get('mode') in ('structural_auto', 'author_submit')
                    and last_write.get('reason') == row['mode'] and published_id
                    and row.get('candidate_id') == published_id and row.get('code_hash') == solution_hash):
                outcome.update(submission_mode=row['mode'], submission_reason=row.get('reason'),
                               submission_finalized=False)
                return outcome
            if row['event'] != 'checkpoint' or last_write.get('tool') != 'publish':
                continue
            basis = row.get('fallback_basis')
        elif (row is last_write and row['tool'] == 'publish'
              and row.get('reason') in ('checkpoint:latest_toolchain_passed', 'checkpoint:latest_complete')):
            # A kill between the atomic write and the subsequent checkpoint event.
            basis = row['reason'].removeprefix('checkpoint:')
        else:
            continue
        if published_id and row.get('candidate_id') == published_id and row.get('code_hash') == solution_hash:
            outcome.update(submission_mode='fallback', submission_reason=stop_reason or 'unfinalized_checkpoint',
                           submission_finalized=False, fallback_basis=basis)
            return outcome
    return outcome


def summarize(trace_path, solution_path):
    rows = _trace_rows(trace_path)
    selections = [r for r in rows if r['tool'] == 'select' and r['event'] == 'result']
    creations = [r for r in rows if r['tool'] == 'candidate' and r['event'] == 'create']
    deliveries = [r for r in rows if r['tool'] == 'extract']
    explicit_calls = {r.get('source_call_id') for r in deliveries if type(r.get('complete_new_draft')) is bool}
    deliveries.extend(_legacy_guided_deliveries(rows, explicit_calls))
    call_counts = Counter(r.get('source_call_id') for r in creations)
    completeness = {r['candidate_id']: _delivery_state(r, deliveries, call_counts) for r in creations}
    complete = [r for r in creations if completeness[r['candidate_id']] is True]
    selected = selections[-1] if selections else {}
    latest = complete[-1] if complete else {}
    selected_id = selected.get('candidate_id')
    selected_complete = completeness.get(selected_id)
    solution = solution_path.read_bytes() if solution_path.is_file() else None
    solution_hash = sha256(solution) if solution is not None else None
    # Both operations atomically replace solution.v. Attribute its actual bytes
    # to the last recorded write, including workflows without a submission gateway.
    write = next((r for r in reversed(rows) if r['tool'] in ('publish', 'select')
                  and r['event'] == 'result'), {})
    published_id = None
    if solution and solution.strip() and write.get('code_hash') == solution_hash:
        published_id = write.get('candidate_id')
    stop_reason = next((r.get('reason') for r in reversed(rows)
                        if r['tool'] == 'budget' and r['event'] == 'stopped'), None)
    budget_stop = {'deadline': 'deadline', 'solve budget exhausted': 'budget_exhausted',
                   'cancelled': 'cancelled'}.get(stop_reason)
    checks=[r for r in rows if r['tool'] in ('interface','lint','synth','functional') and r['event']=='result']
    verifications = [r for r in rows if r['tool'] == 'guided' and r['event'] == 'verification']
    attempts=[]
    for delivery in deliveries:
        if type(delivery.get('complete_new_draft')) is not bool:continue
        call_id = delivery.get('source_call_id')
        candidate = next((c for c in creations if c['candidate_id'] == delivery.get('candidate_id')
                          and (call_id is None or c.get('source_call_id') == call_id)), {})
        if 'candidate_id' not in delivery and call_id and call_counts[call_id] == 1:
            candidate = next(c for c in creations if c.get('source_call_id') == call_id)
        observed = list(_check_evidence(checks, candidate)) if candidate else []
        check_failures = {'environment': 'environment_failure', 'checker': 'checker_error',
                          'timeout': 'check_timeout'}
        failure = next((check_failures[c['failure_kind']] for c in observed
                        if c.get('failure_kind') in check_failures), None)
        rejected=any(c.get('status')=='failed' and c.get('failure_kind') in ('code', None)
                     and (c['tool']!='interface' or c.get('blocking')) for c in observed)
        accepted = None
        if not failure:
            if rejected:
                accepted = False
            elif candidate and verifications:
                accepted = _guided_acceptance(verifications[-1], candidate)
            elif candidate and any(s.get('candidate_id') == candidate['candidate_id'] and
                                   s.get('reason') in ('checks_passed', 'synth_passed') for s in selections):
                accepted = True
        delivered = delivery['complete_new_draft'] if candidate or not delivery['complete_new_draft'] else None
        attempts.append(dict(source_call_id=call_id, candidate_id=candidate.get('candidate_id'), checker_accepted=accepted,
            **classify_attempt(delivered=delivered,
                checker_accepted=accepted,
                new_hash=candidate.get('code_hash'), failure_outcome=failure)))
    extracted_calls={a['source_call_id'] for a in attempts}
    for row in rows:
        if row['tool']=='llm' and row['event']=='failed' and row.get('call_id') not in extracted_calls:
            attempts.append(dict(source_call_id=row.get('call_id'),stage=row.get('purpose'),
                error_kind=row.get('error_kind'), error_type=row.get('error_type'),
                **classify_attempt(delivered=None, failure_outcome=_model_failure(row, budget_stop))))
    return {'schema_version': 2, 'selected_candidate_id': selected_id,
            'selected_candidate_sha256': selected.get('code_hash'),
            'published_candidate_id': published_id,
            'published_candidate_sha256': solution_hash if published_id else None,
            'published_candidate_complete': completeness.get(published_id),
            **_submission_outcome(rows, published_id, solution_hash, solution, write, stop_reason),
            'budget_stop': budget_stop,
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
            'guided_verifications': verifications,
            'checks': [r for r in rows if (r['tool'] == 'knowledge' and r['event'] == 'check_evidence')
                       or (r['tool'] in ('interface', 'lint', 'synth', 'functional') and r['event'] == 'result')],
            'costs': [r for r in rows if r.get('elapsed_s') is not None or r.get('tokens_out') is not None],
            'model_results': [r for r in rows if r['tool'] == 'knowledge' and r['event'] == 'model_result']}
