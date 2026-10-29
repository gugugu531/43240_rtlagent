"""Rebind rc4.4 after tightening explicit-inapplicability predicates."""
from pathlib import Path
import copy
import json
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT / 'dev/optimization-v42'), str(ROOT)]

from common42 import fingerprint, load, save, sha
from agent.knowledge.research import implementation_hash, validate_bundle, validate_vector_index, load_bundle


def bind_assets(data):
    mapping = {card['card_id']: card for card in data['cards']}
    for row in data['documents'] + data['rules']:
        row['card_sha256'] = fingerprint(mapping[row['card_id']])
    save(ROOT / 'knowledge/research-v3.json', data)
    catalog = load(ROOT / 'knowledge/catalog-v3.json')
    catalog['cards_sha256'] = fingerprint(data['cards'])
    for entry in catalog['entries']:
        entry['card_sha256'] = fingerprint(mapping[entry['card_id']])
    save(ROOT / 'knowledge/catalog-v3.json', catalog)
    lock = load(ROOT / 'knowledge/research-v3-lock.json')
    lock.update(
        bundle_sha256=sha((ROOT / 'knowledge/research-v3.json').read_bytes()),
        catalog_sha256=sha((ROOT / 'knowledge/catalog-v3.json').read_bytes()),
        cards_sha256=fingerprint(data['cards']),
        policy_sha256=fingerprint(data['rules']),
        index_sha256=fingerprint(data['documents']),
        implementation_sha256=implementation_hash(),
    )
    validate_bundle(data, lock, load(ROOT / 'knowledge/research-scope.json'))
    save(ROOT / 'knowledge/research-v3-lock.json', lock)
    index = load(ROOT / 'knowledge/research-v3-vectors.json')
    index['documents_sha256'] = fingerprint(data['documents'])
    validate_vector_index(index, data)
    save(ROOT / 'knowledge/research-v3-vectors.json', index)
    save(ROOT / 'knowledge/research-v3-vectors-lock.json', {
        'release_id': data['release_id'],
        'sha256': sha((ROOT / 'knowledge/research-v3-vectors.json').read_bytes()),
    })


def bootstrap_lock():
    """Allow the stricter implementation to load the otherwise unchanged bundle."""
    lock = load(ROOT / 'knowledge/research-v3-lock.json')
    lock['implementation_sha256'] = implementation_hash()
    save(ROOT / 'knowledge/research-v3-lock.json', lock)
    load_bundle.cache_clear()
    load_bundle()


def finalize():
    gate = load(HERE / 'gate-results.json')
    assert gate['passed'] == gate['count'] == 10
    assert all(row['checks']['irrelevant_not_needed'] for row in gate['rows'])
    data = load(ROOT / 'knowledge/research-v3.json')
    assert data['release_id'] == 'rag-catalog-v3-rc4.4'
    save(HERE / 'pre-repair-bundle.json', copy.deepcopy(data))
    gate_artifact = {
        'path': 'dev/optimization-v54/gate-results.json',
        'sha256': sha((HERE / 'gate-results.json').read_bytes()),
    }
    selected = {row['card_id'] for row in load(HERE / 'batch.json')['cards']}
    for card in data['cards']:
        if card['card_id'] not in selected:
            continue
        evidence = card['publication_evidence']['v54_restricted_promotion']
        evidence['routing_admission_and_tokenizer'] = gate_artifact
        evidence['predicate_repair'] = {
            'reason': 'explicit_inapplicability_must_resolve_to_not_needed',
            'safety_effect': 'stricter_refusal_only',
            'new_generation_calls': 0,
        }
    bind_assets(data)
    load_bundle.cache_clear()
    load_bundle()
    print(json.dumps({'release_id': data['release_id'], 'repaired_cards': len(selected),
                      'gate_sha256': gate_artifact['sha256']}, indent=2))


if __name__ == '__main__':
    if len(sys.argv) == 2 and sys.argv[1] == '--bootstrap-lock':
        bootstrap_lock()
    else:
        finalize()
