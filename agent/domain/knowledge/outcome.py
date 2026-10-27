"""Join observed lineage without inventing an external benchmark score."""
from collections import Counter
import json
from .assets import sha256


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
    return {'schema_version': 2, 'selected_candidate_id': selected_id,
            'selected_candidate_complete': selected_complete,
            'latest_complete_candidate_id': latest.get('candidate_id'),
            'selected_latest_complete': (selected_id == latest.get('candidate_id')
                                         if selected_complete is not None else None),
            'solution_sha256': solution_hash,
            'solution_matches_selection': bool(selected and solution_hash == selected.get('code_hash')),
            'selection_reason': selected.get('reason'), 'external_score': None,
            'external_scored_candidate_id': None,
            'assemblies': [r for r in rows if r['tool'] == 'knowledge' and r['event'] == 'assembly'],
            'deliveries': deliveries,
            'checks': [r for r in rows if (r['tool'] == 'knowledge' and r['event'] == 'check_evidence')
                       or (r['tool'] in ('interface', 'lint', 'synth', 'functional') and r['event'] == 'result')],
            'costs': [r for r in rows if r.get('elapsed_s') is not None or r.get('tokens_out') is not None],
            'model_results': [r for r in rows if r['tool'] == 'knowledge' and r['event'] == 'model_result']}
