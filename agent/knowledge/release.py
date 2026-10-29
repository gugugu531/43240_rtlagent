"""Version and hash contract shared by publication, configuration and runtime loading."""
import json
import re
from .assets import sha256, read_resource, _unique

RELEASE_ID = 'framework-v1-en.1'
POLICY_ID = 'conservative-v1-en.1'
F24_PREDICATE = 'lint-xvlog-2026.1-first-4982-comma-replication-v1'


def fingerprint(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')))


def policy_content(data):
    return {key: data[key] for key in ('policy_id', 'rules', 'checkpoints', 'f24_admission')}


def index_content(data):
    return {key: data[key] for key in ('model', 'projection', 'documents')}


def bind_release(data, legacy_bytes):
    data.update(schema_version=2, release_id=RELEASE_ID, policy_id=POLICY_ID, language='en')
    cards = {c['card_id']: c for c in data['cards']}
    def bind(row):
        card = cards[row['card_id']]
        row.update(card_version=card['version'], card_sha256=fingerprint(card))
    for row in [*data['rules'], *data['checkpoints'], *data['documents']]:
        bind(row)
    card = data['f24']
    data['f24_admission'] = {'card_id':card['card_id'], 'card_version':card['version'],
                             'card_sha256':fingerprint(card), 'predicate_id':F24_PREDICATE}
    data['policy_sha256'] = fingerprint(policy_content(data))
    data['index_sha256'] = fingerprint(index_content(data))
    data['legacy_cards_sha256'] = sha256(legacy_bytes)
    return data


def read_lock():
    return json.loads(read_resource('knowledge/runtime-lock.json'), object_pairs_hook=_unique)


def validate_options(options, lock=None):
    lock = lock or read_lock()
    if options.release_id != lock['release_id'] or options.release_id != RELEASE_ID:
        raise ValueError('configured_release_id_mismatch')
    for field in ('release_sha256', 'policy_sha256'):
        if getattr(options, field) is not None and getattr(options, field) != lock[field]:
            raise ValueError('configured_' + field + '_mismatch')


def validate_release(data, lock, raw, legacy_bytes):
    if (data['schema_version'] != 2 or data['release_id'] != RELEASE_ID or data['policy_id'] != POLICY_ID
            or data['language'] != 'en' or lock['release_id'] != RELEASE_ID):
        raise ValueError('runtime_release_contract_mismatch')
    if sha256(raw) != lock['release_sha256']:
        raise ValueError('runtime_release_lock_mismatch')
    if re.search(r'[\u3400-\u9fff]', json.dumps(data, ensure_ascii=False)):
        raise ValueError('runtime_release_contains_non_english_source_text')
    for field, value in (('policy_sha256', fingerprint(policy_content(data))),
                         ('index_sha256', fingerprint(index_content(data))),
                         ('legacy_cards_sha256', sha256(legacy_bytes))):
        if data[field] != value or lock[field] != value:
            raise ValueError(field + '_mismatch')
    cards = {c['card_id']:c for c in data['cards']}
    declared = lock.get('card_count', len(data['cards']))
    if type(declared) is not int or not 0 < declared <= 512 or len(cards) != declared or len(data['cards']) != declared:
        raise ValueError('runtime_card_count_mismatch')
    for rows in (data['documents'], data['rules']):
        if len(rows) != declared or {row['card_id'] for row in rows} != set(cards):
            raise ValueError('runtime_release_identity_mismatch')
    for row in [*data['rules'], *data['checkpoints'], *data['documents']]:
        card = cards.get(row['card_id'])
        if card is None or row['card_version'] != card['version'] or row['card_sha256'] != fingerprint(card):
            raise ValueError('card_policy_or_index_binding_mismatch')
    f24 = data['f24']
    expected = {'card_id':f24['card_id'], 'card_version':f24['version'],
                'card_sha256':fingerprint(f24), 'predicate_id':F24_PREDICATE}
    if data['f24_admission'] != expected:
        raise ValueError('f24_binding_mismatch')
