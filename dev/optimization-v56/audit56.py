"""Audit v56 observations and emit immutable current-version model evidence."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from agent.knowledge.context import NOTICE
from agent.knowledge.release import fingerprint
from agent.knowledge.research import load_bundle

LOCATIONS = {
    'b51-041': ('33376', 'rag-v56-observation-20261029-r1'),
    'b51-047': ('33376', 'rag-v56-observation-20261029-r1'),
    'b51-051': ('33376', 'rag-v56-observation-20261029-r1'),
    'b51-054': ('33376', 'rag-v56-observation-20261029-r1'),
    'b51-066': ('33376', 'rag-v56-observation-20261029-r1'),
    'b51-055': ('33589', 'rag-v56-observation-20261029-r1'),
    'b51-056': ('33589', 'rag-v56-observation-20261029-r1'),
    'b51-059': ('33589', 'rag-v56-observation-20261029-r1'),
    'b51-063': ('33589', 'rag-v56-observation-20261029-r1'),
    'b51-065': ('33589', 'rag-v56-observation-20261029-r1'),
    'b51-068': ('33376-supplement', 'rag-v56-supplement-20261029-r1'),
}


def load(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def case_root(case_id):
    folder, tag = LOCATIONS[case_id]
    return HERE / 'returned' / folder / 'extracted-r1' / tag / case_id


def audit_case(case, card):
    base = case_root(case['case_id'])
    status = load(base / 'status.json')
    meter = load(base / 'call-meter.json')
    errors = []

    def check(condition, message):
        if not condition:
            errors.append(message)

    check(status.get('status') == 'completed', 'status')
    check(status.get('automatic_retries') is False, 'automatic_retries')
    check(meter == {'attempted_calls': 2, 'max_calls': 2}, 'call_meter')
    check(status.get('card_id') == card['card_id'], 'card_id')
    check(status.get('card_version') == card['version'], 'card_version')
    check(status.get('card_sha256') == fingerprint(card), 'card_sha256')
    attempts = {row.get('arm'): row for row in status.get('attempts', [])}
    check(set(attempts) == {'control', 'card'}, 'arm_set')
    arms = {}
    if set(attempts) == {'control', 'card'}:
        requests = {arm: load(base / arm / 'actual-request.json') for arm in attempts}
        expected = {
            'model': 'qwen38-27b-q4-k-m', 'seed': case['seed'], 'temperature': 0.0,
            'top_p': 1.0, 'max_tokens': 16384,
            'chat_template_kwargs': {'enable_thinking': True},
        }
        for key, value in expected.items():
            check(all(requests[arm].get(key) == value for arm in attempts), 'request_' + key)
        check(requests['control']['messages'][:-1] == requests['card']['messages'][:-1], 'message_prefix')
        check(len(requests['control']['messages']) == len(requests['card']['messages']) == 2, 'message_count')
        if len(requests['control']['messages']) == len(requests['card']['messages']) == 2:
            appended = requests['control']['messages'][-1]['content'] + '\n\n' + NOTICE + '\n\n' + card['projection_text']
            check(requests['card']['messages'][-1]['content'] == appended, 'exact_card_append')
        for arm, row in attempts.items():
            check(row.get('case_id') == case['case_id'] and row.get('card_id') == card['card_id'], arm + '_identity')
            check(row.get('card_sha256') == fingerprint(card), arm + '_card_sha256')
            check(row.get('generation_calls') == 1, arm + '_generation_calls')
            check(row.get('success') is True and row.get('delivered') is True and row.get('error') is None, arm + '_outcome')
            check(row.get('judge', {}).get('passed') is True, arm + '_judge')
            summary = row.get('judge', {}).get('summary', {})
            zero_mismatches = (summary.get('mismatches') == 0 or
                               (summary.get('failed_cases') == [] and summary.get('first_mismatch') is None))
            check(zero_mismatches, arm + '_mismatches')
            check(row.get('assembly', {}).get('sent') == ([] if arm == 'control' else [card['card_id']]), arm + '_sent')
            for relative, digest in row.get('artifacts', {}).items():
                check(sha(base / arm / relative) == digest, arm + '_artifact_' + relative)
            arms[arm] = {
                'success': row.get('success'), 'delivered': row.get('delivered'),
                'comparisons': row.get('judge', {}).get('summary', {}).get('comparisons'),
                'mismatches': row.get('judge', {}).get('summary', {}).get('mismatches'),
                'tokens_in': row.get('tokens_in'), 'tokens_out': row.get('tokens_out'),
                'extra_tokens': row.get('extra_tokens'), 'solution_sha256': row.get('solution_sha256'),
            }
    return {
        'case_id': case['case_id'], 'card_id': card['card_id'], 'version': card['version'],
        'card_sha256': fingerprint(card), 'outcome': 'both_pass' if not errors else 'failed_audit',
        'arms': arms, 'errors': errors,
    }


def verify_receipts():
    rows = []
    for folder, tag in sorted(set(LOCATIONS.values())):
        base = HERE / 'returned' / folder
        archive = base / (tag + '.tar.gz')
        receipt = load(base / (tag + '-receipt.json'))
        ok = (receipt['archive_sha256'] == sha(archive) and receipt['archive_bytes'] == archive.stat().st_size
              and receipt['status'] == 'completed')
        rows.append({'folder': folder, 'tag': tag, 'host': receipt['host'], 'actual_calls': receipt['actual_calls'],
                     'archive_sha256': receipt['archive_sha256'], 'passed': ok})
    return rows


def main():
    bundle = load_bundle()
    cards = {row['card_id']: row for row in bundle['cards']}
    tasks = {row['case_id']: row for row in load(ROOT / 'dev/optimization-v51/tasks.json')['tasks']}
    batch = load(HERE / 'batch.json')
    rows = []
    for item in batch['cards']:
        case = tasks[item['route_case_id']]
        card = cards[item['card_id']]
        assert case['card_id'] == card['card_id'] and case['card_version'] == card['version']
        rows.append(audit_case(case, card))
    excluded_case = tasks['b51-041']
    excluded = audit_case(excluded_case, cards[excluded_case['card_id']])
    receipts = verify_receipts()
    status = 'passed' if all(row['outcome'] == 'both_pass' for row in rows) and all(row['passed'] for row in receipts) else 'failed'
    result = {
        'batch_id': batch['batch_id'], 'status': status, 'rows': rows,
        'promotable_current_version_pairs': sum(row['outcome'] == 'both_pass' for row in rows),
        'actual_generation_calls_for_promoted_batch': 20, 'actual_generation_calls_total_campaign': 22,
        'automatic_retries': False, 'receipts': receipts,
        'excluded_observations': [{
            'case_id': excluded['case_id'], 'card_id': excluded['card_id'], 'version': excluded['version'],
            'outcome': 'card_compile_failure', 'promoted': False, 'errors': excluded['errors'],
            'control_success': excluded['arms'].get('control', {}).get('success'),
            'card_success': excluded['arms'].get('card', {}).get('success'),
        }],
        'activation_changed': False, 'production_cohort_used': False,
    }
    (HERE / 'model-audit.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({key: value for key, value in result.items() if key != 'rows'}, indent=2))
    for row in rows:
        print(row['card_id'], row['outcome'], row['errors'])
    if status != 'passed':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
