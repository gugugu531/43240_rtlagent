"""Shared retrieval/admission boundary. Ranking never authorizes injection."""
from collections import Counter, defaultdict
import json
import math
import re
import time
import subprocess
import shlex
from urllib.parse import urlsplit
from functools import lru_cache
import httpx
from .assets import read_resource, sha256, _unique
from .policy import RetrievalOptions
from .retrieval import retrieve as bound_check
from .release import read_lock, validate_release, validate_options


def document_text(card):
    return 'RTL repair guidance document:\n' + ' '.join(
        [card['title'], *card['keywords'], *card['applies_when'],
         *card['not_applicable_when'], *card['guidance'], *card['verification']])


def vector(value, dimensions):
    if not isinstance(value, list) or len(value) != dimensions or any(
            type(x) not in (int, float) or not math.isfinite(x) for x in value):
        raise ValueError('invalid_embedding_vector')
    norm = math.sqrt(sum(x*x for x in value))
    if norm == 0:
        raise ValueError('zero_embedding_vector')
    return [x/norm for x in value]


@lru_cache(maxsize=1)
def bundle():
    raw = read_resource('knowledge/runtime-v1.json', limit=4_194_304)
    digest = sha256(raw)
    if digest != read_resource('knowledge/runtime-v1.sha256').decode().strip():
        raise ValueError('runtime_release_hash_mismatch')
    data = json.loads(raw, object_pairs_hook=_unique)
    validate_release(data, read_lock(), raw, read_resource('knowledge/cards.json'))
    cards = {c['card_id']: c for c in data['cards']}
    docs = {d['card_id']: d for d in data['documents']}
    rules = {r['card_id']: r for r in data['rules']}
    if (len(cards) != 32 or len(data['cards']) != 32 or len(docs) != 32
            or len(data['documents']) != 32 or len(data['rules']) != 32
            or set(cards) != set(docs) or set(cards) != set(rules)):
        raise ValueError('runtime_release_identity_mismatch')
    for key, doc in docs.items():
        if sha256(json.dumps(document_text(cards[key]), ensure_ascii=False, sort_keys=True, separators=(',', ':'))) != doc['text_sha256']:
            raise ValueError('document_projection_mismatch')
        vector(doc['vector'], data['model']['dimensions'])
        if abs(sum(v*v for v in doc['vector']) - 1.0) > 1e-6:
            raise ValueError('document_vector_not_normalized')
    return data, digest


def tokens(text):
    stop = {'a', 'an', 'and', 'common', 'critical', 'error', 'for', 'from', 'in', 'is',
            'of', 'on', 'or', 'synth', 'the', 'to', 'vrfc', 'warning', 'with', 'xelab', 'xsim', 'xvlog'}
    base = [t.casefold() for t in re.findall(r'[a-z][a-z0-9_+-]*|\d+|[\u3400-\u9fff]', text, re.I)
            if not t.isdigit() and t.casefold() not in stop]
    cjk = ''.join(c for c in text if '\u3400' <= c <= '\u9fff')
    return base + ([cjk] if len(cjk) == 1 else [cjk[i:i+2] for i in range(max(0, len(cjk)-1))])


def bm25(cards, query):
    documents = [tokens(document_text(c).split('\n', 1)[1]) for c in cards]
    frequencies = Counter(t for d in documents for t in set(d))
    average = sum(map(len, documents))/max(1, len(documents))
    ranked = []
    for card, doc in zip(cards, documents):
        counts, score, matched = Counter(doc), 0.0, 0
        for term in sorted(set(tokens(query))):
            f = counts[term]
            if f:
                matched += 1
                score += math.log(1+(len(cards)-frequencies[term]+.5)/(frequencies[term]+.5))*f*2.5/(f+1.5*(.25+.75*len(doc)/max(average, 1)))
        if matched >= 2:
            ranked.append((card['card_id'], score))
    return sorted(ranked, key=lambda x: (-x[1], x[0]))


def query_projection(data, item, stage):
    # Send only a bounded diagnostic, not full prompts, RTL, task IDs or oracle data.
    diagnostic = re.sub(r'(?:/[\w.\-]+){2,}', '<path>', item.get('message', ''))[:2000]
    return (f"Instruct: {data['projection']['query_instruction']}\nQuery: diagnostic: {diagnostic}"
            f"\nstage: {stage}\ntool: {item['tool']}\ntool version: {item['version']}"
            f"\nerror code: {item.get('code') or 'none'}\nconstructs: none")


def embed(data, query, options, trace=None):
    if not options.embedding_url:
        raise ValueError('embedding_endpoint_unconfigured')
    request = {'model': data['model']['runtime_alias'], 'input': [query], 'encoding_format': 'float'}
    url = options.embedding_url.rstrip('/') + '/v1/embeddings'
    if options.embedding_transport == 'ssh':
        parsed = urlsplit(url)
        if (not options.embedding_ssh_host or parsed.scheme != 'http'
                or parsed.hostname not in ('127.0.0.1', 'localhost') or parsed.username or parsed.query or parsed.fragment):
            raise ValueError('ssh_embedding_requires_explicit_host_and_loopback_service')
        remote = shlex.join(['curl', '--fail', '--silent', '--show-error', '--max-time',
            str(options.embedding_timeout_s), '-H', 'Content-Type: application/json', '--data-binary', '@-', url])
        process = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
            '-o', 'ConnectTimeout=3', '-p', str(options.embedding_ssh_port), options.embedding_ssh_host, remote],
            input=json.dumps(request), capture_output=True, text=True,
            timeout=options.embedding_timeout_s, check=True)
        payload = json.loads(process.stdout)
    else:
        with httpx.Client(timeout=options.embedding_timeout_s, trust_env=False,
                          follow_redirects=False) as client:
            response = client.post(url, json=request)
            response.raise_for_status()
            payload = response.json()
    if payload.get('model') != data['model']['runtime_alias']:
        raise ValueError('embedding_model_mismatch')
    if trace is not None:
        trace['embedding_model'] = payload['model']
        trace['embedding_usage'] = payload.get('usage')
    return vector(payload['data'][0]['embedding'], data['model']['dimensions'])


INVALID_REPLICATION = re.compile(r'(?<!\{)\{\s*(?:\d+|[A-Za-z_$][A-Za-z0-9_$]*)\s*\{[^{}]+\}\s*,')


def f24_matches(parent, item, stage):
    code = re.sub(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"', ' ', parent.code, flags=re.S)
    return (stage == 'lint' and item.get('tool') == 'xvlog' and item.get('version') == '2026.1'
            and item.get('code') == 'VRFC 10-4982' and "syntax error near ','" in item.get('message', '').lower()
            and bool(INVALID_REPLICATION.search(code)))


def retrieve_runtime(evidence, parent, options, messages, raw_feedback=None):
    options = RetrievalOptions.model_validate(options)
    started = time.monotonic()
    try:
        if evidence and (not isinstance(evidence.get('execution_id'), str) or not evidence['execution_id']):
            raise ValueError('missing_execution_identity')
        _, trace = bound_check([], evidence, parent)
    except (KeyError, AttributeError, TypeError, ValueError):
        trace = {'reason': 'invalid_check_evidence'}
    trace.update(requested_strategy=options.strategy, effective_strategy=options.strategy,
                 retrieved=[], admitted=[], rejected=[], fallback=options.fallback)
    def done(cards):
        trace['elapsed_ms'] = round((time.monotonic()-started)*1000, 3)
        return cards, trace
    if trace['reason'] != 'no_match':
        return done([])
    check = evidence['check']
    items = [i for i in check.details['knowledge_diagnostics']['items']
             if i.get('severity') == 'error' and not i.get('cascade')]
    if not items:
        trace['reason'] = 'no_primary_diagnostic'
        return done([])
    item = items[0]  # Tool order, never lexicographic code order or secondary messages.
    trace['primary'] = {k: item.get(k) for k in ('code', 'tool', 'version', 'command_index')}
    if item.get('version') != '2026.1' or item.get('process_status') != 'failed':
        trace['reason'] = 'unknown_version_or_nonfailure'
        return done([])
    try:
        data, digest = bundle()
        validate_options(options)
        trace['release_sha256'] = digest
        trace.update(release_id=data['release_id'], policy_sha256=data['policy_sha256'], index_sha256=data['index_sha256'])
        cards = [c for c in data['cards'] if
                 (not c['stages'] or check.kind in c['stages']) and
                 (not c['tools'] or item['tool'] in c['tools']) and
                 (not c['tool_versions'] or item['version'] in c['tool_versions'])]
        exact = [(c['card_id'], 100.0) for c in cards if item.get('code') in c['error_codes']]
        exact.sort()
        rankings = {'exact': exact}
        if options.strategy in ('bm25', 'hybrid'):
            rankings['bm25'] = bm25(cards, item.get('message', ''))
        if options.strategy in ('dense', 'hybrid'):
            query = query_projection(data, item, check.kind)
            trace['query_sha256'] = sha256(query)
            embedding_started = time.monotonic()
            try:
                q = embed(data, query, options, trace)
                ids = {c['card_id'] for c in cards}
                rankings['dense'] = sorted([(d['card_id'], sum(x*y for x,y in zip(q,d['vector'])))
                    for d in data['documents'] if d['card_id'] in ids], key=lambda x:(-x[1],x[0]))
            except (httpx.HTTPError, subprocess.SubprocessError, OSError, ValueError, KeyError, IndexError, TypeError) as error:
                trace.update(embedding_error=type(error).__name__, effective_strategy=options.fallback)
            finally:
                trace['embedding_ms'] = round((time.monotonic()-embedding_started)*1000, 3)
        strategy = trace['effective_strategy']
        if strategy == 'hybrid':
            scores = defaultdict(float)
            for ranking in rankings.values():
                for rank, (key, _) in enumerate(ranking, 1):
                    scores[key] += 1/(60+rank)
            ranking = sorted(scores.items(), key=lambda x:(-x[1],x[0]))
        else:
            ranking = rankings.get(strategy, [])
        narrow = f24_matches(parent, item, check.kind) and strategy != 'empty'
        if narrow:
            # Independent, declared exact safety lane; not a fabricated dense vector.
            ranking.insert(0, (data['f24']['card_id'], 100.0))
        trace['retrieved'] = [{'id': key, 'score': score,
                               'lane': 'restricted_exact' if key == data['f24']['card_id'] else strategy}
                              for key,score in ranking[:options.retrieve_k]]
        rules = {r['card_id']: r for r in data['rules']}
        feedback = '\n'.join(m['content'] for m in messages)
        admitted = []
        for key, score in ranking[:options.retrieve_k]:
            if key == data['f24']['card_id']:
                card, reason = data['f24'], None
                if card['projection_text'] in feedback or '{{N{expr}}, slice}' in feedback:
                    reason = 'knowledge_already_present'
            else:
                rule = rules[key]
                reason = rule['decision']
                if any(c['card_id'] == key and c['card_version'] == rule['card_version']
                       and c['card_sha256'] == rule['card_sha256'] and c['candidate_sha256'] == parent.code_hash
                       and raw_feedback is not None and c['feedback_sha256'] == sha256(raw_feedback)
                       for c in data.get('checkpoints', [])):
                    reason = 'checkpoint_correct_empty'
                elif any(s.casefold() in feedback.casefold() for s in rule['skip_if_feedback_contains']):
                    reason = 'knowledge_already_present'
                elif reason == 'eligible_when_missing_fact':
                    reason = 'missing_fact_not_mechanically_established'
            if reason:
                trace['rejected'].append({'id': key, 'reason': reason})
            elif len(admitted) >= options.inject_k:
                trace['rejected'].append({'id': key, 'reason': 'injection_limit'})
            else:
                admitted.append(card)
                trace['admitted'].append(key)
        trace['reason'] = ('retrieval_unavailable' if strategy == 'empty' and 'embedding_error' in trace
                           else 'admitted' if admitted else 'correct_empty')
        return done(admitted)
    except (OSError, ValueError, KeyError, TypeError) as error:
        trace.update(reason='optional_retrieval_failure', error=type(error).__name__)
        return done([])
