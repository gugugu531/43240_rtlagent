"""Read-only routing and admission gate for the third ten-card batch."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(ROOT)]

import agent.knowledge.pregen as pregen
from agent.knowledge.context import NOTICE
from agent.knowledge.release import fingerprint
from agent.knowledge.research import load_bundle
from predicates55 import IRRELEVANT55, PREDICATES55


def load(path):
    return json.loads(path.read_text())


def tokenize(host, text):
    payload = json.dumps({'content': text}, separators=(',', ':'))
    result = subprocess.run([
        'ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-p', str(host),
        'root@36.150.116.206',
        "curl --fail --silent --show-error --max-time 30 -H 'Content-Type: application/json' --data-binary @- http://127.0.0.1:8010/tokenize",
    ], input=payload, capture_output=True, text=True, timeout=45, check=True)
    return len(json.loads(result.stdout)['tokens'])


def main():
    batch = load(HERE / 'batch.json')
    active = load_bundle()
    assert active['release_id'] == batch['base_release']
    candidate = deepcopy(active)
    selected = {row['card_id'] for row in batch['cards']}
    for card in candidate['cards']:
        if card['card_id'] in selected:
            assert card['activation_state'] == 'shadow'
            card['injection_eligible'] = True
            if 'pre_generation' not in card['phases']:
                card['phases'] = ['pre_generation', *card['phases']]
    pregen.PREDICATES.update(PREDICATES55)
    pregen.load_bundle = lambda: candidate
    cards = {row['card_id']: row for row in candidate['cards']}
    tasks = {row['case_id']: row for row in load(ROOT / 'dev/optimization-v51/tasks.json')['tasks']}
    tasks49 = {row['case_id']: row for row in load(ROOT / 'dev/optimization-v49/tasks.json')['tasks']}
    rows = []
    for item in batch['cards']:
        card = cards[item['card_id']]
        task = tasks[item['route_case_id']]
        direct = {
            'positive': pregen.decide(card, task['prompt'], task['interface'], data=candidate),
            'known': pregen.decide(card, card['narrow_fact'], task['interface'], data=candidate),
            'conflicting': pregen.decide(card, 'This claim is false: ' + card['narrow_fact'], task['interface'], data=candidate),
            'insufficient': pregen.decide(card, 'Implement the required module.', task['interface'], data=candidate),
            'irrelevant': pregen.decide(card, IRRELEVANT55[card['card_id']], task['interface'], data=candidate),
        }
        tampered = deepcopy(card)
        tampered['version'] += '.tampered'
        direct['tampered'] = pregen.decide(tampered, task['prompt'], task['interface'], data=candidate)
        routes = {}
        for strategy in ('bm25', 'dense'):
            options = {'strategy': strategy, 'fallback': 'empty', 'retrieve_k': 5, 'inject_k': 1}
            if strategy == 'dense':
                options.update(
                    embedding_url='http://127.0.0.1:8020', embedding_transport='ssh',
                    embedding_ssh_host='root@36.150.116.206', embedding_ssh_port=item['route_host'],
                    embedding_timeout_s=4.0,
                )
            admitted, trace = pregen.retrieve_spec(task['prompt'], task['interface'], options)
            ids = [row['id'] for row in trace['retrieved']]
            rejected = [row for row in trace['rejected'] if row.get('card_id') == card['card_id']]
            routes[strategy] = {
                'top5': ids,
                'target_rank': ids.index(card['card_id']) + 1 if card['card_id'] in ids else None,
                'target_rejections': rejected,
                'admitted': [row['card_id'] for row in admitted],
                'reason': trace['reason'], 'error': trace.get('error'),
                'elapsed_ms': trace.get('elapsed_ms'), 'embedding_ms': trace.get('embedding_ms'),
            }
        audit = load(ROOT / item['evidence_path'])
        model_row = next(row for row in audit['rows'] if row['case_id'] == item['evidence_case_id'])
        fixture_ok = True
        fixture_fields = ('prompt', 'interface', 'target', 'reference', 'adjacent', 'bench')
        if item['evidence_kind'] == 'identical_fixture':
            observed = tasks49[item['evidence_fixture_id']]
            fixture_ok = all(observed[field] == task[field] for field in fixture_fields)
        else:
            fixture_ok = item['evidence_kind'] == 'independent_public_context'
        token_count = tokenize(item['route_host'], NOTICE + '\n\n' + card['projection_text'])
        checks = {
            'positive_eligible': direct['positive']['decision_class'] == 'eligible',
            'known_not_needed': direct['known']['decision_class'] == 'not_needed',
            'conflicting_not_eligible': direct['conflicting']['decision_class'] != 'eligible',
            'insufficient_not_eligible': direct['insufficient']['decision_class'] != 'eligible',
            'irrelevant_not_needed': direct['irrelevant']['decision_class'] == 'not_needed',
            'tampered_failure': direct['tampered']['decision_class'] == 'failure',
            'bm25_top5': routes['bm25']['target_rank'] is not None,
            'dense_top5': routes['dense']['target_rank'] is not None,
            'shadow_blocks_bm25': any(row.get('reason') == 'catalog_shadow_or_hold' for row in routes['bm25']['target_rejections']),
            'shadow_blocks_dense': any(row.get('reason') == 'catalog_shadow_or_hold' for row in routes['dense']['target_rejections']),
            'token_budget': token_count <= 1024,
            'model_fixture_evidence': fixture_ok,
            'current_version_model_pair': audit['status'] == 'passed' and model_row['card_id'] == card['card_id']
                and model_row['version'] == card['version'] and model_row['outcome'] == 'both_pass'
                and all(arm['success'] and arm['delivered'] for arm in model_row['arms'].values()),
        }
        rows.append({
            'card_id': card['card_id'], 'card_version': card['version'],
            'candidate_card_sha256': fingerprint(card), 'route_case_id': task['case_id'],
            'evidence_path': item['evidence_path'], 'evidence_case_id': item['evidence_case_id'],
            'evidence_kind': item['evidence_kind'], 'direct': direct, 'routes': routes,
            'projection_tokens': token_count, 'model_outcome': model_row['outcome'],
            'checks': checks, 'passed': all(checks.values()),
        })
    result = {
        'batch_id': batch['batch_id'], 'base_release': active['release_id'], 'count': len(rows),
        'passed': sum(row['passed'] for row in rows), 'rows': rows, 'new_model_calls': 0,
        'activation_changed': False, 'candidate_only': True,
    }
    (HERE / 'gate-results.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({key: value for key, value in result.items() if key != 'rows'}, indent=2))
    for row in rows:
        print(row['card_id'], row['passed'], row['routes']['bm25']['target_rank'],
              row['routes']['dense']['target_rank'], row['projection_tokens'],
              [key for key, value in row['checks'].items() if not value])
    if result['passed'] != result['count']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
