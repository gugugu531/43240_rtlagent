"""Reproducible, label-free publication from reviewed development assets.

python -m agent.knowledge.publish /path/to/development/repository
Only declared card fields and document vectors are released; never queries or gold.
"""
import json
import sys
from pathlib import Path
from .assets import ROOT, sha256
from .policy_english import MISSING_FACTS
from .release import bind_release, validate_release


def publish(source, target=ROOT / 'knowledge'):
    source, target = Path(source) / 'dev/rag', Path(target)
    provenance = {}
    def read(name):
        raw = (source / name).read_bytes()
        provenance[name] = sha256(raw)
        return json.loads(raw)
    corpus = read('corpus/cards-v4-en-candidate.json')
    index = read('indexes/qwen3-embedding-0.6b-q8-v1.json')
    canonical = json.dumps(corpus, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    if sha256(canonical) != index['projection']['corpus_sha256']:
        raise ValueError('source corpus does not match frozen document index')
    if index['model']['dimensions'] != 1024 or index['model']['normalization'] != 'l2':
        raise ValueError('unsupported index vector contract')
    policy = read('review/card-runtime-admission-v2.json')
    f24 = read('runtime/candidate-v5/f24-repair-replication-concatenation-syntax-compact-en.json')
    fields = ('card_id', 'version', 'title', 'stages', 'tools', 'tool_versions',
              'error_codes', 'keywords', 'applies_when', 'not_applicable_when',
              'guidance', 'verification', 'hard_negatives', 'conflict_groups')
    cards = [{key: card.get(key, []) for key in fields} for card in corpus['cards']]
    for card in cards:
        card['projection_text'] = '\n'.join([f"[Knowledge Card {card['card_id']}@{card['version']}] {card['title']}"] +
            [key + ': ' + '; '.join(card[key]) for key in
             ('applies_when', 'not_applicable_when', 'guidance', 'verification', 'hard_negatives')])
    # F24 has a separately frozen compact rendering and no dense vector.
    compact = f24['cards'][0]
    if sha256(compact['projection_text']) != compact['projection_sha256']:
        raise ValueError('F24 projection hash mismatch')
    fcard = {'card_id': compact.get('card_id', compact.get('id')), 'version': compact['version'],
             'projection_text': compact['projection_text']}
    rules = [{key: rule[key] for key in ('card_id', 'decision', 'trigger_variants',
              'requires_missing_fact', 'skip_if_feedback_contains', 'must_not_co_inject')}
             for rule in policy['rules']]
    source_rules = {rule['card_id']:rule for rule in policy['rules']}
    if {r['card_id'] for r in rules if r['requires_missing_fact']} != set(MISSING_FACTS):
        raise ValueError('missing-fact translation coverage changed; review required')
    for rule in rules:
        original = source_rules[rule['card_id']]
        rule['source_card_version'] = original['card_version']
        if rule['requires_missing_fact']:
            if len(rule['requires_missing_fact']) != 1:
                raise ValueError('missing-fact translation count changed; review required')
            rule['requires_missing_fact'] = [MISSING_FACTS[rule['card_id']]]
    checkpoints = []
    for number in range(3, 7):
        addendum = read(f'review/card-runtime-admission-addendum-v{number}.json')
        for rule in addendum['rules']:
            if rule.get('decision') == 'correct_empty' and rule.get('candidate_sha256') and rule.get('feedback_sha256'):
                checkpoints.append({key: rule[key] for key in
                    ('card_id', 'candidate_sha256', 'feedback_sha256')} | {'source_card_version':rule['card_version']})
    release = dict(schema_version=1, release_id='framework-v1', cards=cards, f24=fcard,
                   model=index['model'], projection=index['projection'], documents=index['documents'],
                   rules=rules, checkpoints=checkpoints, provenance=provenance,
                   admission='conservative-v1-unresolved-semantic-conditions-fail-closed')
    target.mkdir(parents=True, exist_ok=True)
    legacy_bytes = (target / 'cards.json').read_bytes()
    release = bind_release(release, legacy_bytes)
    raw = (json.dumps(release, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()
    lock = {key:release[key] for key in ('release_id', 'policy_sha256', 'index_sha256', 'legacy_cards_sha256')}
    lock['release_sha256'] = sha256(raw)
    validate_release(release, lock, raw, legacy_bytes)
    (target / 'runtime-v1.json').write_bytes(raw)
    (target / 'runtime-v1.sha256').write_text(sha256(raw) + '\n')
    (target / 'runtime-lock.json').write_text(json.dumps(lock, sort_keys=True, indent=2) + '\n')
    return sha256(raw)


if __name__ == '__main__':
    print(publish(sys.argv[1]))
