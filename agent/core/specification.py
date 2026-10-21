"""Locate public specification evidence without inventing or rewriting it."""
from __future__ import annotations

from collections.abc import Mapping
import re


def source_catalog(task_text: str) -> list[dict]:
    """Stable paragraph IDs and exact offsets into prompt + newline + interface."""
    spans = []
    for match in re.finditer(r'\S.*?(?=\n\s*\n|\Z)', task_text, re.DOTALL):
        text = match.group().rstrip()
        spans.append({'id': f's{len(spans) + 1:04d}', 'start': match.start(),
                      'end': match.start() + len(text), 'text': text})
    return spans


def _normalized(text):
    characters, starts, ends = [], [], []
    for match in re.finditer(r'\s+|\S', text):
        characters.append(' ' if match.group().isspace() else match.group())
        starts.append(match.start())
        ends.append(match.end())
    return ''.join(characters), starts, ends


def resolve_quote(quote: str, task_text: str) -> dict:
    """Return the original span; only whitespace differences are tolerated."""
    if not isinstance(quote, str) or not quote.strip():
        raise ValueError('source quotation must be a nonempty string')
    position = task_text.find(quote)
    if position >= 0:
        start, end = position, position + len(quote)
    else:
        normalized, starts, ends = _normalized(task_text)
        needle = re.sub(r'\s+', ' ', quote.strip())
        position = normalized.find(needle)
        if position < 0:
            raise ValueError('source quotation is absent from the original task')
        start, end = starts[position], ends[position + len(needle) - 1]
    source = next((s for s in source_catalog(task_text)
                   if s['start'] <= start and end <= s['end']), None)
    return {'quote': task_text[start:end], 'source_span': {'start': start, 'end': end},
            'source_id': source['id'] if source else None}


def resolve_requirement(requirement: Mapping, task_text: str) -> dict:
    if not isinstance(requirement, Mapping):
        raise ValueError('requirement must be an object')
    source_id = requirement.get('source_id')
    if source_id is not None:
        source = next((s for s in source_catalog(task_text) if s['id'] == source_id), None)
        if source is None:
            raise ValueError('unknown public source_id')
        quote = requirement.get('quote')
        if quote is None:
            evidence = {'quote': source['text'], 'source_id': source_id,
                        'source_span': {'start': source['start'], 'end': source['end']}}
        else:
            local = resolve_quote(quote, source['text'])
            start, end = local['source_span']['start'], local['source_span']['end']
            evidence = {'quote': source['text'][start:end], 'source_id': source_id,
                        'source_span': {'start': source['start'] + start, 'end': source['start'] + end}}
    else:
        evidence = resolve_quote(requirement.get('quote'), task_text)
    return {**dict(requirement), **evidence}


def normalize_requirements(requirements, task_text: str) -> list[dict]:
    if not isinstance(requirements, (tuple, list)) or not 1 <= len(requirements) <= 64:
        raise ValueError('requirements must contain 1..64 public source references')
    result, seen = [], set()
    for index, item in enumerate(requirements):
        normalized = resolve_requirement(item, task_text)
        identity = normalized.get('id', f'r{index + 1:04d}')
        if not isinstance(identity, str) or not identity.strip() or identity in seen:
            raise ValueError('requirements need unique nonempty ids')
        normalized['id'] = identity
        seen.add(identity)
        result.append(normalized)
    return result
