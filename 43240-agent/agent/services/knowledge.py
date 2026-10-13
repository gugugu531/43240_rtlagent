"""Versioned exact-error retrieval from a reviewed, tool-validated local subset."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from agent.prompts.context import ContextPiece

CODE = re.compile(r'(?:VRFC|SYNTH) \d+-\d+')


def load_corpus(path):
    path = Path(path)
    if path.stat().st_size > 1024 * 1024:
        raise ValueError('repair corpus exceeds size limit')
    corpus = json.loads(path.read_text())
    if corpus.get('schema_version') != 1 or corpus.get('status') != 'validated_repair_subset':
        raise ValueError('only a validated repair subset can enter the solver')
    ids = set()
    if not isinstance(corpus.get('cards'), list) or not isinstance(corpus.get('sources'), dict):
        raise ValueError('invalid repair corpus')
    for card in corpus['cards']:
        if (card['id'] in ids or not re.fullmatch('[a-z][a-z0-9-]*', card['id'])
                or card['kind'] != 'repair' or card['tool_validation'] != 'independent_examples_passed'
                or not card.get('validation_sha256') or not re.fullmatch('[0-9a-f]{64}', card['validation_sha256'])):
            raise ValueError('invalid or unvalidated repair card')
        ids.add(card['id'])
        for key in ('codes', 'tools', 'versions', 'guidance', 'verify', 'cautions', 'source_ids'):
            if not isinstance(card.get(key), list) or not card[key] or any(not isinstance(v, str) or not v for v in card[key]):
                raise ValueError('invalid repair card field')
        if any(CODE.fullmatch(code) is None for code in card['codes']):
            raise ValueError('invalid error namespace')
        if any(source not in corpus['sources'] for source in card['source_ids']):
            raise ValueError('unknown card source')
        fragments = card.get('message_contains_any', [])
        if (not isinstance(fragments, list)
                or any(not isinstance(v, str) or not v.strip() for v in fragments)):
            raise ValueError('invalid diagnostic message conditions')
        if re.search(r'\bProb\d{3}_|/tasks/|\b(?:ref|tb)\.s[vh]\b', json.dumps(card), re.I):
            raise ValueError('benchmark-specific material is forbidden')
    return corpus


def retrieve_repair_guides(corpus, *, codes, tool, version, diagnostics=(), limit=2, max_chars=2400):
    if type(limit) is not int or not 1 <= limit <= 2 or type(max_chars) is not int or max_chars < 0:
        raise ValueError('invalid guidance limits')
    result = dict(pieces=(), hits=[], omitted=[], rejected=[], reason='no_match', corpus_sha256=hashlib.sha256(
        json.dumps(corpus, sort_keys=True, ensure_ascii=False).encode()).hexdigest())
    if not tool or not version:
        result['reason'] = 'tool_or_version_unknown'
        return result
    selected = [c for c in corpus['cards'] if tool in c['tools'] and version in c['versions']
                and set(codes).intersection(c['codes'])]
    selected.sort(key=lambda c: c['id'])
    eligible = []
    for card in selected:
        fragments = card.get('message_contains_any', [])
        matched_messages = [d.message.casefold() for d in diagnostics
                            if d.code in card['codes'] and d.severity == 'ERROR'
                            and d.tool == tool and d.version == version]
        if fragments and not any(fragment.casefold() in message
                                 for fragment in fragments for message in matched_messages):
            result['rejected'].append(dict(id=card['id'], reason='diagnostic_message_mismatch'))
            continue
        eligible.append(card)
    pieces, chars = [], 0
    for card in eligible:
        if len(result['hits']) >= limit:
            result['omitted'].append(card['id'])
            continue
        matched = sorted(set(codes).intersection(card['codes']))
        text = (f"[参考知识 {card['id']}] {card['title']}\n适用条件：{card['applies_when']}\n"
                + '建议：' + '；'.join(card['guidance']) + '\n验证：' + '；'.join(card['verify'])
                + '\n边界：' + '；'.join(card['cautions']) + '\n来源编号：' + ', '.join(card['source_ids'])
                + '\n状态：仅用独立小例子验证；题面和自身工具证据优先，本卡不保证功能正确。')
        result['hits'].append(dict(id=card['id'], codes=matched,
            sha256=hashlib.sha256(json.dumps(card, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
            source_ids=card['source_ids']))
        if chars + len(text) > max_chars:
            result['omitted'].append(card['id'])
            continue
        pieces.append(ContextPiece(card['id'], text, tuple(card['source_ids'])))
        chars += len(text)
    result['pieces'] = tuple(pieces)
    result['reason'] = ('matched' if pieces else 'character_budget' if eligible
                        else 'diagnostic_message_mismatch' if selected else 'no_match')
    return result
