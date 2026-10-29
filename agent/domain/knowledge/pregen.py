"""First-generation retrieval and evidence-based, bounded English admission.

No checker feedback or hidden implementation is accepted as routing evidence.
Implemented methods remain subject to individual publication-state checks.
"""

import json
import re
import time

from .assets import sha256
from .release import fingerprint
from .research import load_bundle, load_scope, scope_guard, document_text, validate_vector_index
from .spec_methods import METHODS, contract_guard
from .pregen_methods import PREGEN_METHODS
from .pregen_methods_v55 import PREGEN_METHODS_V55
from .pregen_methods_v56 import PREGEN_METHODS_V56

PREDICATES = {
    'v9-lang-conditional-x-merge': {
        'required': [r'\b(sel(?:ector)?|mux|select|conditional)\b', r'\b(x/z|x or z|unknown|four.state|4.state|ambiguous selector)\b', r'\b(?:merg\w*|matching|equal bits|differ\w*|every other pair)\b|both[^.\n]{0,40}\b(?:0|zero)\b|0\s*/\s*0[^.\n]{0,80}1\s*/\s*1'],
        'known': [r'\?:', r'\b(?:use|using)\s+(?:the\s+)?(?:ternary|conditional)\s+operator', r'\b\w+\s*\?\s*\w+\s*:\s*\w+'],
        'irrelevant': [r'\b(?:only|strictly)\s+(?:two.state|2.state)', r'\b(?:no|never)\s+(?:unknown|x/z)', r'\b(?:unknown|x/z)[^.\n]{0,50}\b(?:default(?:\s+to)?|force|return)\s+(?:zero|0)\s*(?:[.;]|$)', r'\b(?:rather than|instead of)\s+(?:bitwise\s+)?merg'],
    },
    'v9-lang-indexed-select-constant-width': {
        'required': [r'\b(window|slice|consecutive bits|part.select)\b', r'\b(runtime|variable|dynamic)\b', r'\b(?:\d+|four|three|five|eight).bit\b', r'\b(upward|ascending|increasing)\b', r'\b(?:base|offset)\b[^.\n]{0,65}\b\d+\s+(?:through|to)\s+\d+'],
        'known': [r'\b(?:width|span)\b[^.\n]{0,55}(?:elaboration.time constant|constant expression)', r'\b(?:use|using)\b[^.\n]{0,45}\b(?:constant.width indexed part.select|indexed part.select)\b', r'\+\:\s*(?:\d+|[A-Z_]+)'],
        'irrelevant': [r'\b(?:variable|runtime|dynamic)[ -]+width\b', r'\bdownward\b'],
    },
    'v9-lang-context-before-operation': {
        'required': [r'\b(sum|add|addition)\b', r'\bunsigned\b', r'\b(?:retain|include|including|preserve|exact)\b[^.\n]{0,65}\bcarry\b'],
        'known': [r'\b(?:widen|extend)\b[^.\n]{0,60}\b(?:before|operands|inputs)\b', r'\b(?:wider|wide)\s+(?:temporary|intermediate|sum)', r"\{\s*1'b0\s*,"],
        'irrelevant': [r'\b(?:discard|ignore|drop)\b[^.\n]{0,30}\bcarry\b', r'\bmodulo\b'],
    },
    'v9-lang-nba-rhs-sampling': {
        'required': [r'\b(previous|preceding|prior)\b', r'\b(sample|sampled|tag|value)\b', r'\b(?:rising|posedge|clock)\b', r'\b(?:return|output|publish|emit|expose)\b[^.\n]{0,70}\b(?:previous|prior|preceding)\b[^.\n]{0,35}\b(?:sample|sampled|tag|value|input)\b'],
        'known': [r'\bnon.?blocking\s+assignments?\b[^.\n]{0,80}\b(?:old|pre.edge|previous)\b', r'\bRHS\b[^.\n]{0,45}\b(?:old|pre.edge)\s+values?\b'],
        'irrelevant': [r'\b(?:purely\s+)?combinational\b', r'\bcurrent\s+(?:sample|tag)\s+only\b'],
    },
    'v9-public-sticky-event-memory': {
        'required': [r'\b(event|alarm|pending)\b', r'\b(?:accumulat\w*|sticky|remember|remains?\s+(?:set|high)|retain\w*)\b', r'\b(clear|acknowledge|ack|reset)\b', r'\b(clock|rising|posedge)\b'],
        'known': [r'\bbitwise[ -]+OR\b[^.\n]{0,60}\b(?:previous|pending|old|existing)\b', r'\bpending\s*\|\s*event\w*\b', r'\bevent\w*\s*\|\s*pending\b'],
        'irrelevant': [r'\b(?:one.cycle|single.cycle)\s+pulse\s+only\b', r'\b(?:do not|never)\s+(?:remember|retain|accumulate)\b'],
    },
    'v9-lang-arithmetic-right-sign': {
        'required': [r'\b(?:right.shift|shift\w*[^.\n]{0,70}\bright)\b', r'\b(?:signed|two.s.complement|negative)\b', r'\b(?:preserv\w*\s+(?:the\s+)?sign|sign.fill|divide|negative)\b'],
        'known': [r'\buse\b[^.\n]{0,20}>>>[^.\n]{0,45}\bsigned\s+(?:left\s+)?operand\b', r'\$signed\s*\([^;\n)]+\)\s*>>>', r'\buse\b[^.\n]{0,40}\bsigned\s+arithmetic.right.shift\b'],
        'irrelevant': [r'\b(?:zero.fill|logical.right.shift)\b', r'\bunsigned\s+only\b'],
    },
}
PREDICATES.update(METHODS)
PREDICATES.update(PREGEN_METHODS)
PREDICATES.update(PREGEN_METHODS_V55)
PREDICATES.update(PREGEN_METHODS_V56)


def extract_spec(prompt, interface=''):
    sources = {'prompt': prompt, 'interface': interface}
    groups = {
        'widths': r'\b\d+.bit\b|\[\s*\d+\s*:\s*\d+\s*\]',
        'signedness': r'\b(?:signed|unsigned|two.s.complement)\b',
        'clocks_resets': r'\b(?:rising|falling|posedge|negedge|reset|clock|clk)\b',
        'boundaries': r'\b(?:modulo\s+\d+|\d+\s+(?:through|to)\s+\d+|saturat\w*|terminal|boundary)\b',
        'timing': r'\b(?:previous|preceding|prior|latency|stall|valid|cycle|edge)\b',
        'tools': r'\b(?:Vivado|xvlog|XPM|SystemVerilog|Verilog|20\d\d\.\d+)\b',
    }
    facts = []
    for source, text in sources.items():
        for kind, pattern in groups.items():
            for m in re.finditer(pattern, text, re.I):
                facts.append({'kind': kind, 'source': source, 'start': m.start(), 'end': m.end(), 'text': m[0]})
    return {'stage': 'pre_generation', 'prompt_sha256': sha256(prompt), 'interface_sha256': sha256(interface), 'facts': facts}


def supplied_facts(prompt, messages):
    """Only explicit user facts are redundancy evidence, never generic system
    advice or fenced interface/buggy RTL. Keep source and offsets for audit.
    """
    rows=[{'source':'prompt','text':prompt}]
    for index,message in enumerate(messages):
        if message.get('role','user')!='user':
            continue
        text=re.sub(r'```[^\n]*\n.*?```',lambda m:' '*len(m[0]),message.get('content',''),flags=re.S)
        # Generic renderer boilerplate must not become a semantic witness.
        if '## Previous implementation' in text:
            text=text.split('## Previous implementation',1)[0]
        rows.append({'source':f'user_message_{index}','text':text})
    return rows


def activation_allows(card,stage=None):
    allowed=card.get('activation_state','restricted')=='restricted'
    stages=card.get('injection_stages')
    return allowed and (stages is None or stage in stages)


def decide(card, prompt, interface='', *, supplied_messages=(), data=None):
    result = {'card_id': card.get('card_id'), 'admit': False, 'decision_class': 'unknown',
              'reason': 'predicate_not_implemented', 'stage': 'pre_generation',
              'prompt_sha256': sha256(prompt), 'interface_sha256': sha256(interface), 'witnesses': []}
    def reject(reason, kind='unknown'):
        return result | {'reason': reason, 'decision_class': kind}
    if not scope_guard(card.get('card_id', '')):
        return reject('card_frozen', 'not_needed')
    data = data if data is not None else load_bundle()
    expected = next((x for x in data['cards'] if x['card_id'] == card.get('card_id')), None)
    if expected is None or fingerprint(expected) != fingerprint(card):
        return reject('card_asset_mismatch', 'failure')
    result.update(card_version=card['version'], card_sha256=fingerprint(card))
    if 'pre_generation' not in card['phases']:
        return reject('phase_not_applicable', 'not_needed')
    if not card['injection_eligible']:
        return reject('experimental_injection_not_enabled')
    policy = PREDICATES.get(card['card_id'])
    if policy is None:
        return reject('predicate_not_implemented')
    text = prompt + '\n' + interface
    contexts=supplied_facts(prompt,supplied_messages)
    supplied='\n'.join(c['text'] for c in contexts)
    for context in contexts:
        for fact in (card['projection_text'],card['narrow_fact']):
            pos=context['text'].find(fact)
            if pos>=0:
                if re.search(r'\b(?:never|do not|incorrect|false|not true)\b',context['text'][max(0,pos-90):pos],re.I):
                    return reject('conflicting_supplied_fact')
                return reject('knowledge_already_present','not_needed')
    if any(re.search(p, text, re.I | re.S) for p in policy['irrelevant']):
        return reject('explicitly_inapplicable', 'not_needed')
    guard=contract_guard(card['card_id'],prompt,interface)
    if guard:
        return reject(guard[1],guard[0])
    # Conflicting advice cannot establish that a fact is already safely supplied.
    conflict = re.search(r'\b(?:do not|must not|never)\s+(?:use|preserve|retain|accumulate|merge)|\b(?:behavior|width|latency|interpretation|limits|timing)\b[^.\n]{0,40}\b(?:unspecified|not specified)\b', text, re.I)
    if conflict:
        return reject('conflicting_or_incomplete_contract')
    for context in contexts:
        for pattern in policy['known']:
            match=re.search(pattern,context['text'],re.I)
            if match:
                result['witnesses'].append({'source':context['source'],'start':match.start(),'end':match.end(),'text':match[0]})
                return reject('knowledge_already_present','not_needed')
    for pattern in policy['required']:
        match = re.search(pattern, text, re.I)
        if not match:
            return reject('public_contract_insufficient')
        result['witnesses'].append({'source': 'prompt_and_interface', 'start': match.start(), 'end': match.end(), 'text': match[0]})
    return result | {'admit': True, 'decision_class': 'eligible', 'reason': 'bounded_public_contract'}


def query_projection(prompt, interface=''):
    # Never silently truncate away restrictions from the tail of a specification.
    if len(prompt) + len(interface) > 16000:
        raise ValueError('specification_query_too_long')
    return ('Instruct: Retrieve a narrow RTL implementation fact applicable to the explicit public specification.\n'
            f'Query: specification: {prompt}\ninterface: {interface}\nstage: pre_generation')


def retrieve_spec(prompt, interface, options, messages=()):
    from .runtime import bm25, embed
    from .policy import RetrievalOptions
    options = RetrievalOptions.model_validate(options)
    started = time.monotonic()
    trace = {'stage': 'pre_generation', 'requested_strategy': options.strategy, 'effective_strategy': options.strategy,
             'retrieved': [], 'admitted': [], 'rejected': [], 'actually_sent': [], 'reason': 'no_match',
             'specification': extract_spec(prompt, interface)}
    def done(cards, reason):
        trace.update(reason=reason, elapsed_ms=round((time.monotonic()-started)*1000, 3))
        trace['empty_kind'] = ('not_empty' if cards else 'failure' if 'error' in trace else
            'not_needed' if trace['rejected'] and all(r['decision_class'] == 'not_needed' for r in trace['rejected']) else 'unknown')
        return cards, trace
    try:
        data = load_bundle()
        trace['release_id'] = data['release_id']
        query = query_projection(prompt, interface)
        trace['query_sha256'] = sha256(query)
        cards = [c for c in data['cards'] if c['retrieval_enabled'] and scope_guard(c['card_id'])
                 and 'pre_generation' in c['phases']]
        trace['search_pool_count'] = len(cards)
        # The document view deliberately omits example answers and task-specific stops.
        lexical = [dict(card_id=c['card_id'], title=c['title'], keywords=c['keywords'],
                        applies_when=c['applies_when'], not_applicable_when=[],
                        guidance=[c['narrow_fact']], verification=[]) for c in cards]
        rankings = {}
        if options.strategy in ('bm25', 'hybrid'):
            rankings['bm25'] = bm25(lexical, prompt + '\n' + interface)
        if options.strategy in ('dense', 'hybrid'):
            try:
                index_raw = read_vector_index()
                vectors = validate_vector_index(index_raw, data)
                before = time.monotonic()
                q = embed(data, query, options, trace)
                trace['embedding_ms'] = round((time.monotonic()-before)*1000, 3)
                rankings['dense'] = sorted([(c['card_id'], sum(a*b for a,b in zip(q, vectors[c['card_id']]))) for c in cards], key=lambda x: (-x[1], x[0]))
            except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
                if options.fallback == 'empty':
                    trace['error'] = type(error).__name__ + ': ' + str(error)
                    trace['effective_strategy'] = 'empty'
                    return done([], 'embedding_unavailable')
                raise ValueError('exact_fallback_not_supported_for_specification') from error
        if options.strategy == 'exact':
            return done([], 'diagnostic_exact_not_applicable_to_specification')
        if options.strategy == 'hybrid':
            scores = {}
            for ranking in rankings.values():
                for rank, (cid, _) in enumerate(ranking, 1): scores[cid] = scores.get(cid, 0) + 1/(60+rank)
            ranking = sorted(scores.items(), key=lambda x: (-x[1], x[0]))
        else:
            ranking = rankings.get(options.strategy, [])
        mapping = {c['card_id']: c for c in cards}
        admitted = []
        for cid, score in ranking[:options.retrieve_k]:
            trace['retrieved'].append({'id': cid, 'score': score})
            decision = decide(mapping[cid], prompt, interface, supplied_messages=messages, data=data)
            if decision['admit'] and not activation_allows(mapping[cid],'pre_generation'):
                decision=decision|{'admit':False,'decision_class':'unknown','reason':'catalog_shadow_or_hold'}
            if decision['admit'] and len(admitted) < options.inject_k:
                admitted.append(mapping[cid]); trace['admitted'].append(cid)
            else:
                if decision['admit']: decision = decision | {'admit': False, 'reason': 'injection_limit', 'decision_class': 'unknown'}
                trace['rejected'].append(decision)
        return done(admitted, 'admitted' if admitted else 'empty')
    except Exception as error:
        # Optional retrieval may not prevent the solver from answering.
        trace['error'] = type(error).__name__ + ': ' + str(error)
        return done([], 'optional_retrieval_failure')


def read_vector_index():
    from .assets import read_resource, _unique
    from .research import VECTOR_PATH, VECTOR_LOCK_PATH
    raw = read_resource(VECTOR_PATH, limit=16_777_216)
    lock = json.loads(read_resource(VECTOR_LOCK_PATH), object_pairs_hook=_unique)
    if sha256(raw) != lock['sha256']:
        raise ValueError('research_vector_file_hash_mismatch')
    return json.loads(raw, object_pairs_hook=_unique)
