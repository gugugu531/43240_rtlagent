"""Run immutable current-card two-arm observations on one experimental host."""
import argparse
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
import sys
import tarfile
import urllib.request

V52 = Path('/root/rtl-rag-cohort52-20261029-r1')
V51 = Path('/root/rtl-rag-mechanical51-20261029-r2')
HERE51 = V51 / 'dev/optimization-v51'
sys.path[:0] = [str(V52 / 'dev/optimization-v42'), str(V52 / 'dev/optimization-v37'), str(V52)]

from common42 import fingerprint, load, save, sha
from judge37 import simulation
from worker42 import attempt

EXPECTED_CARD_HASHES = {
    'b51-041': '979ee268edb1b2df8633aa15c5e95956b9c67218e187c2eaf397c8a6d0c77818',
    'b51-047': '190a9fd24b100759a7da9893e8869c896153ff42e245c023ab9de6e0cad9d037',
    'b51-051': 'c75d868345a963dae95b2cb6c62d7de3317beac4dbde619e422fdae15dc85a48',
    'b51-066': 'f4821e201167204ecc74492d73c1ad1937a5913e286cc7399768707a9be0e4a4',
    'b51-054': '0d8b8214af6d41554d323b64225ca2eebe03ddf6241cb0036a02499ad9c6ca35',
    'b51-055': '769e698765faa6a6914b77c884b4125290cb94fb48144030265980cf1550bc24',
    'b51-056': '2bfa1522be1e81daf8377caa8032e9adc8ba80498410663e9a67424c2f23fd79',
    'b51-059': '1119bc4f6694ade7163a948a4a011dfb0033f10ebe86e69d535dfef92c8fba1e',
    'b51-063': '28f6ba612e16d7b0a20d774864e70182a23b329383f800a922c47e2d60b199cd',
    'b51-065': '5cefeb7ea1b15e883f4f495c60bedaa993c6473c080cf2ae4daf62e9f8394ab6',
    'b51-068': 'afd1d554d495fe3759d18c8a88b44b876360f573417a7616388e27fa7f1fc3bb',
}


def health():
    with urllib.request.urlopen('http://127.0.0.1:8010/health', timeout=5) as response:
        service = json.load(response)
    with urllib.request.urlopen('http://127.0.0.1:8010/slots', timeout=5) as response:
        slots = json.load(response)
    return service.get('status') == 'ok' and not any(row.get('is_processing') for row in slots)


def expected_target_failure(case, check):
    allowed = case.get('allow_target_compile_failure')
    return not check['passed'] and (check['failure_kind'] == 'functional' or (allowed and check['failure_kind'] == 'compile'))


def run_case(case, card, output, order):
    output.mkdir(parents=True, exist_ok=False)
    state = {
        'case_id': case['case_id'], 'card_id': card['card_id'], 'card_version': card['version'],
        'card_sha256': fingerprint(card), 'status': 'running', 'automatic_retries': False,
        'started_utc': datetime.now(timezone.utc).isoformat(), 'attempts': [],
    }
    save(output / 'status.json', state)
    meter = {'attempted_calls': 0, 'max_calls': 2}
    save(output / 'call-meter.json', meter)
    try:
        checks = {name: simulation(case, case[name], output / 'preflight' / name)
                  for name in ('reference', 'target', 'adjacent')}
        passed = (checks['reference']['passed'] and expected_target_failure(case, checks['target']) and
                  not checks['adjacent']['passed'] and checks['adjacent']['failure_kind'] == 'functional')
        preflight = {'passed': passed, 'checks': checks, 'case_sha256': fingerprint(case)}
        save(output / 'preflight.json', preflight)
        if not passed:
            state['status'] = 'mechanical_needs_revision'
            return state
        if not health():
            raise RuntimeError('model_not_idle')
        arms = ['control', 'card'] if order % 2 == 0 else ['card', 'control']
        for arm in arms:
            row = attempt(case, card, preflight, arm, output / arm, meter, case['seed'])
            state['attempts'].append(row)
            save(output / 'status.json', state)
        state['status'] = 'completed'
    except Exception as error:
        state.update(status='infrastructure_failure', error=type(error).__name__ + ': ' + str(error))
    finally:
        state['finished_utc'] = datetime.now(timezone.utc).isoformat()
        save(output / 'status.json', state)
    return state


def main(host, case_ids, tag):
    tasks = {row['case_id']: row for row in load(HERE51 / 'tasks.json')['tasks']}
    cards = {row['card_id']: row for row in load(HERE51 / 'candidate-bundle.json')['cards']}
    root = Path('/root/' + tag)
    root.mkdir(parents=True, exist_ok=False)
    summary = {'host': host, 'case_ids': case_ids, 'status': 'running', 'automatic_retries': False, 'cases': []}
    save(root / 'summary.json', summary)
    with Path('/root/rtlagent-v12-model-8010.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for order, case_id in enumerate(case_ids):
            case = tasks[case_id]
            card = cards[case['card_id']]
            if fingerprint(card) != EXPECTED_CARD_HASHES[case_id] or card['version'] != case['card_version']:
                raise ValueError('current_card_identity_mismatch:' + case_id)
            state = run_case(case, card, root / case_id, order)
            summary['cases'].append({'case_id': case_id, 'card_id': card['card_id'], 'status': state['status'],
                                     'attempted_calls': len(state['attempts'])})
            save(root / 'summary.json', summary)
            if state['status'] != 'completed':
                break
    summary['status'] = 'completed' if len(summary['cases']) == len(case_ids) and all(row['status'] == 'completed' for row in summary['cases']) else 'failed'
    save(root / 'summary.json', summary)
    archive = Path('/root/' + tag + '.tar.gz')
    with tarfile.open(archive, 'w:gz') as tar:
        for path in root.rglob('*'):
            if path.is_file() and 'xsim.dir' not in path.parts and path.suffix not in ('.pb', '.jou'):
                tar.add(path, arcname=str(path.relative_to(root.parent)), recursive=False)
    receipt = {'host': host, 'status': summary['status'], 'archive_sha256': sha(archive.read_bytes()),
               'archive_bytes': archive.stat().st_size, 'actual_calls': sum(row['attempted_calls'] for row in summary['cases'])}
    save(Path('/root/' + tag + '-receipt.json'), receipt)
    print(json.dumps(receipt))
    if summary['status'] != 'completed':
        raise SystemExit(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', type=int, required=True)
    parser.add_argument('--cases', nargs='+', required=True)
    parser.add_argument('--tag', default='rag-v56-observation-20261029-r1')
    args = parser.parse_args()
    main(args.host, args.cases, args.tag)
