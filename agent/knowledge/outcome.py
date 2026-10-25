"""Join observed lineage without inventing an external benchmark score."""
import json
from .assets import sha256


def summarize(trace_path, solution_path):
    rows = [json.loads(line) for line in trace_path.read_text().splitlines() if line.strip()]
    selections = [r for r in rows if r['tool'] == 'select' and r['event'] == 'result']
    creations = [r for r in rows if r['tool'] == 'candidate' and r['event'] == 'create']
    selected = selections[-1] if selections else {}
    latest = creations[-1] if creations else {}
    selected_id = selected.get('candidate_id')
    solution_hash = sha256(solution_path.read_bytes())
    return {'schema_version': 1, 'selected_candidate_id': selected_id,
            'latest_complete_candidate_id': latest.get('candidate_id'),
            'selected_latest_complete': selected_id is not None and selected_id == latest.get('candidate_id'),
            'solution_sha256': solution_hash,
            'solution_matches_selection': bool(selected and solution_hash == selected.get('code_hash')),
            'selection_reason': selected.get('reason'), 'external_score': None,
            'external_scored_candidate_id': None,
            'assemblies': [r for r in rows if r['tool'] == 'knowledge' and r['event'] == 'assembly'],
            'deliveries': [r for r in rows if r['tool'] == 'extract'],
            'checks': [r for r in rows if (r['tool'] == 'knowledge' and r['event'] == 'check_evidence')
                       or (r['tool'] in ('interface', 'lint', 'synth', 'functional') and r['event'] == 'result')],
            'costs': [r for r in rows if r.get('elapsed_s') is not None or r.get('tokens_out') is not None],
            'model_results': [r for r in rows if r['tool'] == 'knowledge' and r['event'] == 'model_result']}
