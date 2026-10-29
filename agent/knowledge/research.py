"""Hash-bound research assets and a shared fail-closed candidate scope guard."""

import json
import re
from functools import lru_cache

from .assets import read_resource, sha256, _unique
from .release import fingerprint

RESEARCH_RELEASE = 'rag-catalog-v3-rc4.6'
SCOPE_PATH = 'knowledge/research-scope.json'
BUNDLE_PATH = 'knowledge/research-v3.json'
LOCK_PATH = 'knowledge/research-v3-lock.json'
VECTOR_PATH = 'knowledge/research-v3-vectors.json'
VECTOR_LOCK_PATH = 'knowledge/research-v3-vectors-lock.json'


def implementation_hash():
    files = ('agent/knowledge/pregen.py', 'agent/knowledge/research.py', 'agent/knowledge/context.py',
             'agent/knowledge/runtime.py', 'agent/knowledge/policy.py',
            'agent/knowledge/feedback.py', 'agent/knowledge/catalog.py', 'agent/knowledge/spec_methods.py',
            'agent/knowledge/pregen_methods.py', 'agent/knowledge/pregen_methods_v55.py',
            'agent/knowledge/pregen_methods_v56.py',
            'agent/nodes/checks.py', 'agent/nodes/design.py')
    return fingerprint({name: sha256(read_resource(name)) for name in files})


def load_scope():
    raw = read_resource(SCOPE_PATH, limit=2_097_152)
    lock = json.loads(read_resource(LOCK_PATH), object_pairs_hook=_unique)
    if sha256(raw) != lock['scope_sha256']:
        raise ValueError('research_scope_hash_mismatch')
    scope = json.loads(raw, object_pairs_hook=_unique)
    rows = scope['cards']
    ids = [r['candidate_id'] for r in rows]
    if len(ids) != 136 or len(set(ids)) != len(ids):
        raise ValueError('research_scope_identity_mismatch')
    allowed = [r for r in rows if r['status'] == 'allowed_research']
    frozen = [r for r in rows if r['status'] == 'frozen']
    if len(allowed) != 97 or len(frozen) != 39:
        raise ValueError('research_scope_count_mismatch')
    return scope


def scope_guard(card_id, scope=None):
    scope = scope if scope is not None else load_scope()
    row = next((r for r in scope['cards'] if r['candidate_id'] == card_id), None)
    if row:
        return row['status'] == 'allowed_research'
    return not card_id.startswith(('v8-', 'v9-'))


def render(card):
    fields = ('narrow_fact', 'safe_example', 'minimal_modification', 'mandatory_final_check', 'stop_condition')
    return f"[Knowledge Card {card['card_id']}@{card['version']}] {card['title']}\n" + '\n'.join(
        f'{key}: {card[key]}' for key in fields if card.get(key))


def document_text(card):
    return '\n'.join([card['title'], card.get('family', ''), *card.get('keywords', []),
                      card['narrow_fact'], *card.get('applies_when', [])])


def validate_bundle(data, lock, scope):
    if data['release_id'] != RESEARCH_RELEASE or lock['release_id'] != RESEARCH_RELEASE:
        raise ValueError('research_release_identity_mismatch')
    cards, docs, rules = data['cards'], data['documents'], data['rules']
    ids = [r['card_id'] for r in cards]
    if (len(ids) != data['card_count'] or len(set(ids)) != len(ids)
            or not ids or len(ids) > 512):
        raise ValueError('research_card_identity_mismatch')
    if any(len(rows) != len(cards) or {r['card_id'] for r in rows} != set(ids)
           for rows in (docs, rules)):
        raise ValueError('research_rule_document_identity_mismatch')
    if any(not scope_guard(cid, scope) for cid in ids):
        raise ValueError('frozen_card_in_release')
    if {cid for cid in ids if cid.startswith(('v8-', 'v9-'))} != {
            r['candidate_id'] for r in scope['cards'] if r['status'] == 'allowed_research'}:
        raise ValueError('research_allowed_coverage_mismatch')
    mapping = {r['card_id']: r for r in cards}
    for card in cards:
        if card['projection_text'] != render(card):
            raise ValueError('research_render_mismatch')
    for row in rules + docs:
        card = mapping[row['card_id']]
        if row['card_version'] != card['version'] or row['card_sha256'] != fingerprint(card):
            raise ValueError('research_card_binding_mismatch')
    for doc in docs:
        if doc['text_sha256'] != sha256(document_text(mapping[doc['card_id']])):
            raise ValueError('research_document_projection_mismatch')
    for name, value in [('cards_sha256', cards), ('policy_sha256', rules), ('index_sha256', docs)]:
        if lock[name] != fingerprint(value):
            raise ValueError('research_' + name + '_mismatch')
    if lock['model_sha256'] != fingerprint(data['model']):
        raise ValueError('research_model_binding_mismatch')
    if re.search(r'[\u3400-\u9fff]', json.dumps(cards, ensure_ascii=False)):
        raise ValueError('research_card_contains_non_english_text')


@lru_cache(maxsize=1)
def load_bundle():
    lock = json.loads(read_resource(LOCK_PATH), object_pairs_hook=_unique)
    if lock['implementation_sha256'] != implementation_hash():
        raise ValueError('research_implementation_hash_mismatch')
    raw = read_resource(BUNDLE_PATH, limit=8_388_608)
    if sha256(raw) != lock['bundle_sha256']:
        raise ValueError('research_bundle_hash_mismatch')
    data = json.loads(raw, object_pairs_hook=_unique)
    if sha256(read_resource('knowledge/catalog-v3.json'))!=lock['catalog_sha256']:
        raise ValueError('research_catalog_hash_mismatch')
    validate_bundle(data, lock, load_scope())
    from .catalog import validate_catalog
    validate_catalog(data)
    return data


def validate_vector_index(index, data):
    """Accept only a complete index of real vectors bound to this document view."""
    from .runtime import vector
    if (index['release_id'] != data['release_id'] or index['model'] != data['model']
            or index['documents_sha256'] != fingerprint(data['documents'])):
        raise ValueError('research_vector_index_identity_mismatch')
    rows = index['vectors']
    if len(rows) != data['card_count'] or {r['card_id'] for r in rows} != {r['card_id'] for r in data['cards']}:
        raise ValueError('research_vector_coverage_mismatch')
    documents = {r['card_id']: r for r in data['documents']}
    if any(r['text_sha256'] != documents[r['card_id']]['text_sha256'] for r in rows):
        raise ValueError('research_vector_text_binding_mismatch')
    return {r['card_id']: vector(r['vector'], data['model']['dimensions']) for r in rows}
