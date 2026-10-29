"""Publish the ten fully gated v56 cards as restricted pre-generation rules."""
from collections import Counter
from copy import deepcopy
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT / 'dev/optimization-v42'), str(ROOT)]

from common42 import fingerprint, load, save, sha
from agent.knowledge.research import (
    RESEARCH_RELEASE, implementation_hash, load_bundle, render, validate_bundle, validate_vector_index,
)


def artifact(path):
    return {'path': path, 'sha256': sha((ROOT / path).read_bytes())}


def main():
    assert RESEARCH_RELEASE == 'rag-catalog-v3-rc4.6'
    batch = load(HERE / 'batch.json')
    gate = load(HERE / 'gate-results.json')
    assert gate['base_release'] == batch['base_release'] == 'rag-catalog-v3-rc4.5'
    assert gate['passed'] == gate['count'] == len(batch['cards']) == 10
    assert gate['actual_generation_calls_for_promoted_batch'] == 20 and gate['activation_changed'] is False
    gate_rows = {row['card_id']: row for row in gate['rows']}
    selected = {row['card_id'] for row in batch['cards']}
    assert set(gate_rows) == selected and all(row['passed'] and all(row['checks'].values()) for row in gate_rows.values())

    data = load(ROOT / 'knowledge/research-v3.json')
    assert data['release_id'] == 'rag-catalog-v3-rc4.5'
    save(HERE / 'prior-bundle.json', data)
    for name in ('catalog-v3.json', 'research-v3-lock.json', 'research-v3-vectors-lock.json'):
        save(HERE / ('prior-' + name), load(ROOT / 'knowledge' / name))
    mapping = {card['card_id']: card for card in data['cards']}
    audit = load(HERE / 'model-audit.json')
    assert audit['status'] == 'passed' and audit['promotable_current_version_pairs'] == 10
    audit_rows = {item['card_id']: item for item in audit['rows']}
    changes = []
    for spec in batch['cards']:
        card = mapping[spec['card_id']]
        row = gate_rows[card['card_id']]
        assert card['activation_state'] == 'shadow'
        candidate = deepcopy(card)
        candidate['injection_eligible'] = True
        if 'pre_generation' not in candidate['phases']:
            candidate['phases'] = ['pre_generation', *candidate['phases']]
        assert fingerprint(candidate) == row['candidate_card_sha256']
        audit_row = audit_rows[card['card_id']]
        assert audit_row['card_id'] == card['card_id'] and audit_row['case_id'] == spec['route_case_id']
        assert audit_row['version'] == card['version'] and audit_row['outcome'] == 'both_pass'
        assert all(arm['success'] and arm['delivered'] for arm in audit_row['arms'].values())
        card.update(
            injection_eligible=True, phases=candidate['phases'], activation_state='restricted',
            injection_stages=['pre_generation'],
        )
        card['feedback_contract']['status'] = 'restricted_pre_generation_only'
        card['publication_evidence']['v56_restricted_promotion'] = {
            'routing_admission_and_tokenizer': artifact('dev/optimization-v56/gate-results.json'),
            'model_audit': artifact('dev/optimization-v56/model-audit.json'),
            'model_evidence_kind': 'current_version_fixed_pair',
            'case_id': audit_row['case_id'], 'route_case_id': spec['route_case_id'],
            'observed_version': audit_row['version'],
            'observed_projection_sha256': sha(render(card).encode()),
            'candidate_policy_card_sha256': row['candidate_card_sha256'],
            'bm25_rank': row['routes']['bm25']['target_rank'],
            'dense_rank': row['routes']['dense']['target_rank'],
            'projection_tokens': row['projection_tokens'],
            'stage_restriction': 'pre_generation_only', 'defaults_changed': False,
        }
        changes.append({'card_id': card['card_id'], 'from': 'shadow', 'to': 'restricted',
                        'injection_stages': ['pre_generation'], 'evidence_kind': 'current_version_fixed_pair'})

    data['release_id'] = RESEARCH_RELEASE
    for row in data['documents'] + data['rules']:
        card = mapping[row['card_id']]
        row['card_sha256'] = fingerprint(card)
        if row in data['rules']:
            row.update(activation_state=card['activation_state'], phases=card['phases'],
                       predicate=card['card_id'] if card['injection_eligible'] else None)
    save(ROOT / 'knowledge/research-v3.json', data)

    catalog = load(ROOT / 'knowledge/catalog-v3.json')
    catalog.update(release_id=RESEARCH_RELEASE, cards_sha256=fingerprint(data['cards']))
    for entry in catalog['entries']:
        card = mapping[entry['card_id']]
        entry.update(card_sha256=fingerprint(card), state=card['activation_state'], phases=card['phases'])
        if entry['card_id'] in selected:
            entry['policy_adapter'] = 'reviewed_public_specification'
    save(ROOT / 'knowledge/catalog-v3.json', catalog)

    lock = load(ROOT / 'knowledge/research-v3-lock.json')
    lock.update(
        release_id=RESEARCH_RELEASE,
        bundle_sha256=sha((ROOT / 'knowledge/research-v3.json').read_bytes()),
        catalog_sha256=sha((ROOT / 'knowledge/catalog-v3.json').read_bytes()),
        cards_sha256=fingerprint(data['cards']), policy_sha256=fingerprint(data['rules']),
        index_sha256=fingerprint(data['documents']), implementation_sha256=implementation_hash(),
    )
    validate_bundle(data, lock, load(ROOT / 'knowledge/research-scope.json'))
    save(ROOT / 'knowledge/research-v3-lock.json', lock)
    index = load(ROOT / 'knowledge/research-v3-vectors.json')
    documents = {row['card_id']: row for row in data['documents']}
    assert all(row['text_sha256'] == documents[row['card_id']]['text_sha256'] for row in index['vectors'])
    index.update(release_id=RESEARCH_RELEASE, documents_sha256=fingerprint(data['documents']))
    validate_vector_index(index, data)
    save(ROOT / 'knowledge/research-v3-vectors.json', index)
    save(ROOT / 'knowledge/research-v3-vectors-lock.json', {
        'release_id': RESEARCH_RELEASE, 'sha256': sha((ROOT / 'knowledge/research-v3-vectors.json').read_bytes()),
    })
    load_bundle.cache_clear()
    load_bundle()
    states = dict(Counter(card['activation_state'] for card in data['cards']))
    assert states == {'legacy_policy': 32, 'restricted': 38, 'shadow': 33, 'mechanical_only': 26}
    note = {
        'release_id': RESEARCH_RELEASE, 'base_release': 'rag-catalog-v3-rc4.5', 'changes': changes,
        'states': states, 'promoted': 10, 'actual_new_model_calls': 20,
        'all_promotions_pre_generation_only': True, 'defaults_changed': False,
        'embedding_vectors_reused': 129, 'card_projection_text_changed': False,
        'original_39_still_frozen': True, 'production_cohort_used': False,
    }
    save(HERE / 'release-note.json', note)
    print(json.dumps(note, indent=2))


if __name__ == '__main__':
    main()
