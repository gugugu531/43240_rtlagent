"""Combine read-only routing and current-version model evidence."""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load(name):
    return json.loads((HERE / name).read_text())


def main():
    route = load('route-results.json')
    model = load('model-audit.json')
    evidence = {row['card_id']: row for row in model['rows']}
    rows = []
    for row in route['rows']:
        model_row = evidence[row['card_id']]
        checks = dict(row['checks'])
        checks['current_version_model_pair'] = (
            model_row['outcome'] == 'both_pass' and model_row['version'] == row['card_version']
            and model_row['card_sha256'] == row['source_card_sha256']
            and all(arm['success'] and arm['delivered'] for arm in model_row['arms'].values())
        )
        rows.append(row | {'model_evidence': model_row, 'checks': checks, 'passed': all(checks.values())})
    result = {
        'batch_id': route['batch_id'], 'base_release': route['base_release'], 'count': len(rows),
        'passed': sum(row['passed'] for row in rows), 'rows': rows,
        'actual_generation_calls_for_promoted_batch': model['actual_generation_calls_for_promoted_batch'],
        'actual_generation_calls_total_campaign': model['actual_generation_calls_total_campaign'],
        'automatic_retries': model['automatic_retries'], 'activation_changed': False,
        'candidate_only': True, 'production_cohort_used': False,
    }
    (HERE / 'gate-results.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({key: value for key, value in result.items() if key != 'rows'}, indent=2))
    if result['passed'] != result['count'] or model['status'] != 'passed':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
