"""One asset registry with independently retained diagnostic and research policy."""
import json
from .assets import read_resource, sha256, _unique
from .release import fingerprint, validate_release

CATALOG_PATH='knowledge/catalog-v3.json'


def validate_catalog(bundle):
    catalog=json.loads(read_resource(CATALOG_PATH),object_pairs_hook=_unique)
    if catalog['release_id']!=bundle['release_id'] or catalog['cards_sha256']!=fingerprint(bundle['cards']):
        raise ValueError('catalog_bundle_identity_mismatch')
    cards={c['card_id']:c for c in bundle['cards']}
    if len(catalog['entries'])!=len(cards) or {e['card_id'] for e in catalog['entries']}!=set(cards):
        raise ValueError('catalog_entry_identity_mismatch')
    raw=read_resource('knowledge/runtime-v1.json',limit=8_388_608)
    legacy=json.loads(raw,object_pairs_hook=_unique)
    lock=json.loads(read_resource('knowledge/runtime-lock.json'),object_pairs_hook=_unique)
    validate_release(legacy,lock,raw,read_resource('knowledge/cards.json'))
    if catalog['legacy_release_sha256']!=sha256(raw):
        raise ValueError('catalog_legacy_policy_changed')
    legacy_ids={c['card_id'] for c in legacy['cards']}
    for entry in catalog['entries']:
        c=cards[entry['card_id']]
        if entry['version']!=c['version'] or entry['card_sha256']!=fingerprint(c) or entry['state']!=c['activation_state']:
            raise ValueError('catalog_card_policy_binding')
        if c['activation_state'] not in ('legacy_policy','restricted','shadow','hold','mechanical_only'):
            raise ValueError('catalog_unknown_activation_state')
        if c['card_id'] in legacy_ids and entry['policy_adapter']!='legacy_diagnostic':
            raise ValueError('catalog_legacy_policy_adapter')
        if c['activation_state']=='restricted' and not c['injection_eligible']:
            raise ValueError('catalog_restricted_without_predicate_permission')
    return catalog
