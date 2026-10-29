"""Research feedback search. Relevance is never an information-increment proof.

All 97 mechanically reviewed candidates can be observed here. The other 91
remain shadow/unknown until a generalizable admission predicate is implemented;
historical fixture hashes are deliberately NOT used as an admission shortcut.
"""

import json
import re
import time

from .assets import sha256
from .pregen import decide as decide_spec, PREDICATES, read_vector_index, activation_allows
from .policy import RetrievalOptions
from .research import load_bundle, scope_guard, validate_vector_index
from .runtime import bm25, embed


def bound_feedback(evidence, parent, task=None):
    from agent.rtl.result import checker_hash
    if not parent or not evidence or not evidence.get('execution_id'):
        raise ValueError('missing_current_execution')
    check = evidence.get('check')
    if not check or not check.id or check.candidate_id != parent.id:
        raise ValueError('candidate_identity_mismatch')
    details = check.details
    if details.get('candidate_hash') != parent.code_hash or sha256(parent.code) != parent.code_hash:
        raise ValueError('candidate_source_hash_mismatch')
    if details.get('checker_hash') != checker_hash():
        raise ValueError('checker_implementation_mismatch')
    if check.status != 'failed':
        raise ValueError('not_a_confirmed_failure')
    if check.kind == 'functional':
        # A model diagnosis is not evidence. Require the actual public suite,
        # trace and simulator stages, bound to the current candidate and suite.
        from agent.rtl.identity import suite_hash
        suite = evidence.get('suite')
        if not suite or suite_hash(suite) != details.get('suite_hash'):
            raise ValueError('public_suite_binding_missing')
        if task is None or evidence.get('public_task_sha256') != sha256(task.prompt+'\n'+task.interface):
            raise ValueError('public_task_binding_missing')
        from agent.rtl.suite.model import require_comparable_expectations
        require_comparable_expectations(suite, task_text=task.prompt+'\n'+task.interface)
        from agent.rtl.specification import resolve_requirement
        for requirement in suite.get('requirements', []):
            resolve_requirement(requirement, task.prompt+'\n'+task.interface)
        if (not details.get('failed_cases') or not details.get('first_mismatch')
                or not details.get('traces') or check.rc != 0):
            raise ValueError('functional_counterexample_missing')
        from pathlib import Path
        commands = [Path(c[0]).name for c in check.command if c]
        if commands != ['xvlog', 'xelab', 'xsim']:
            raise ValueError('successful_simulator_execution_missing')
        first = details['first_mismatch']
        trace = [r for r in details['traces'] if r.get('case_id') == first.get('case_id')
                 and r.get('step') == first.get('step')]
        if not trace:
            raise ValueError('counterexample_not_in_trace')
        return 'post_functional_feedback', json.dumps({'first_mismatch': first, 'trace': trace}, sort_keys=True)
    if check.kind in ('lint', 'synth') and check.failure_kind == 'code':
        from .retrieval import retrieve
        _, trace = retrieve([], evidence, parent)
        if trace.get('reason') != 'no_match':
            raise ValueError('diagnostic_binding_invalid:' + str(trace.get('reason')))
        items = details['knowledge_diagnostics']['items']
        primary = next((i for i in items if i.get('severity') == 'error' and not i.get('cascade')), None)
        if (not primary or primary.get('version') != '2026.1'
                or primary.get('process_status') != 'failed'):
            raise ValueError('unsupported_or_missing_primary_diagnostic')
        return 'post_diagnostic', json.dumps(primary, sort_keys=True)
    raise ValueError('unsupported_feedback_kind')


def decide_feedback(card, task, evidence, parent, messages=(), *, data=None, bound=None):
    result = {'card_id': card.get('card_id'), 'admit': False,
              'decision_class': 'unknown', 'reason': 'feedback_predicate_not_implemented'}
    if not scope_guard(card.get('card_id', '')):
        return result | {'decision_class': 'not_needed', 'reason': 'card_frozen'}
    data = data if data is not None else load_bundle()
    expected = next((c for c in data['cards'] if c['card_id'] == card.get('card_id')), None)
    if expected != card:
        return result | {'decision_class': 'failure', 'reason': 'card_asset_mismatch'}
    try:
        stage, text = bound if bound is not None else bound_feedback(evidence, parent, task)
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        return result | {'reason': str(error)}
    result.update(stage=stage, execution_id=evidence['execution_id'], check_id=evidence['check'].id,
                  candidate_hash=parent.code_hash)
    if stage not in card['phases']:
        return result | {'decision_class': 'not_needed', 'reason': 'phase_not_applicable'}
    witness=source_method_witness(card['card_id'],task,parent.code)
    if witness:
        return result|{'decision_class':'not_needed','reason':'specific_method_already_present','witnesses':[witness]}
    supplied = '\n'.join([task.prompt, task.interface, text] + [m.get('content', '') for m in messages])
    # Exact fact/projection repetitions are provably redundant. Semantic
    # paraphrases without a reviewed recognizer remain unknown, not correct_empty.
    for fact in (card['narrow_fact'], card['projection_text']):
        position = supplied.find(fact)
        if position >= 0:
            prefix = supplied[max(0, position-100):position]
            if re.search(r'\b(?:do not|must not|never|false|incorrect|not true)\b', prefix, re.I):
                return result | {'reason': 'conflicting_supplied_fact'}
            return result | {'decision_class': 'not_needed', 'reason': 'knowledge_already_present'}
    if card['card_id'] in PREDICATES:
        decision = decide_spec(card, task.prompt, task.interface,
                               supplied_messages=[*messages,{'role':'user','content':text}], data=data)
        # Public-spec admission is reusable only after feedback identity checks.
        return decision | {'stage': stage, 'execution_id': evidence['execution_id'],
                           'check_id': evidence['check'].id, 'candidate_hash': parent.code_hash}
    return result


def source_method_witness(card_id,task,source):
    """Two bounded source facts; no claim to parse arbitrary Verilog.

    A literal-width select in the actual output assignment already uses that
    method even if its numeric width is wrong. A signed output declaration
    never proves that the shift's left operand is signed.
    """
    code=re.sub(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"',lambda m:' '*len(m[0]),source,flags=re.S)
    module=re.search(r'\bmodule\s+'+re.escape(task.top)+r'\b.*?\bendmodule\b',code,re.S)
    if not module:return None
    body=module[0];inputs={p.name for p in task.expected_interface.ports if p.direction=='input'};outputs={p.name for p in task.expected_interface.ports if p.direction=='output'}
    matches=[]
    if card_id=='v9-lang-indexed-select-constant-width':
        for m in re.finditer(r'\bassign\s+(?P<out>\w+)\s*=\s*(?P<input>\w+)\s*\[\s*(?P<base>\w+)\s*\+:\s*(?P<width>\d+)\s*\]\s*;',body):
            if m['out'] in outputs and m['input'] in inputs and m['base'] in inputs and int(m['width'])>0:matches.append(m)
    elif card_id=='v9-lang-arithmetic-right-sign':
        signed=set()
        for declaration in re.finditer(r'\b(?:input|wire|reg|logic)\s+signed\s*(?:\[[^\]]+\])?\s*(\w+)',body):signed.add(declaration[1])
        for m in re.finditer(r'\bassign\s+(?P<out>\w+)\s*=\s*(?P<left>\$signed\s*\(\s*\w+\s*\)|\w+)\s*>>>\s*[^;]+;',body):
            if m['out'] in outputs and (m['left'] in signed or m['left'].startswith('$signed')):matches.append(m)
    if len(matches)!=1:return None
    m=matches[0];start=module.start()+m.start();end=module.start()+m.end()
    return {'source':'current_candidate','start':start,'end':end,'text':source[start:end],'source_sha256':sha256(source),'scope':task.top}


def retrieve_feedback(task, evidence, parent, options, messages=()):
    options = RetrievalOptions.model_validate(options)
    started = time.monotonic()
    trace = {'retrieved': [], 'admitted': [], 'rejected': [], 'actually_sent': [],
             'requested_strategy': options.strategy, 'effective_strategy': options.strategy}
    def done(cards, reason):
        trace.update(reason=reason, elapsed_ms=round((time.monotonic()-started)*1000, 3))
        trace['empty_kind'] = ('not_empty' if cards else 'failure' if 'error' in trace
            else 'not_needed' if trace['rejected'] and all(r['decision_class']=='not_needed'
                for r in trace['rejected']) else 'unknown')
        return cards, trace
    try:
        check = (evidence or {}).get('check')
        if check and (check.status in ('timeout', 'unavailable', 'error')
                      or check.failure_kind in ('environment', 'timeout')):
            trace['error'] = 'check_execution_failure'
            return done([], 'check_execution_failure')
        try:
            stage, feedback = bound_feedback(evidence, parent, task)
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            return done([], 'unconfirmed_feedback:' + str(error))
        try:
            data = load_bundle()
        except Exception as error:
            trace['error'] = type(error).__name__+': '+str(error)
            return done([], 'research_asset_failure')
        trace.update(stage=stage, release_id=data['release_id'],
                     candidate_hash=parent.code_hash, check_id=evidence['check'].id,
                     execution_id=evidence['execution_id'])
        cards = [c for c in data['cards'] if c['card_id'].startswith(('v8-', 'v9-'))
                 and scope_guard(c['card_id']) and c['retrieval_enabled'] and stage in c['phases']]
        query = task.prompt + '\n' + task.interface + '\n' + feedback
        if len(query) > 24000:
            return done([], 'feedback_query_too_long')
        trace.update(query_sha256=sha256(query), search_pool_count=len(cards))
        rankings = {}
        lexical = [dict(card_id=c['card_id'], title=c['title'], keywords=c['keywords'],
            applies_when=c['applies_when'], not_applicable_when=[], guidance=[c['narrow_fact']], verification=[])
            for c in cards]
        if options.strategy in ('bm25', 'hybrid'):
            rankings['bm25'] = bm25(lexical, query)
        if options.strategy in ('dense', 'hybrid'):
            try:
                vectors = validate_vector_index(read_vector_index(), data)
                q = embed(data, 'Instruct: Retrieve a narrow RTL fact for the bound public failure.\nQuery: '+query, options, trace)
                rankings['dense'] = sorted([(c['card_id'], sum(a*b for a,b in zip(q, vectors[c['card_id']])))
                    for c in cards], key=lambda r: (-r[1], r[0]))
            except Exception as error:
                trace.update(error=type(error).__name__+': '+str(error), effective_strategy='empty')
                return done([], 'embedding_unavailable')
        if options.strategy == 'exact':
            return done([], 'research_feedback_requires_ranked_search')
        if options.strategy == 'hybrid':
            scores = {}
            for rows in rankings.values():
                for rank, (cid, _) in enumerate(rows, 1): scores[cid] = scores.get(cid, 0)+1/(60+rank)
            ranking = sorted(scores.items(), key=lambda r: (-r[1], r[0]))
        else:
            ranking = rankings.get(options.strategy, [])
        mapping = {c['card_id']: c for c in cards}
        admitted = []
        for cid, score in ranking[:options.retrieve_k]:
            trace['retrieved'].append({'id': cid, 'score': score})
            decision = decide_feedback(mapping[cid], task, evidence, parent, messages,
                                       data=data, bound=(stage, feedback))
            if decision['admit'] and not activation_allows(mapping[cid],stage):
                decision=decision|{'admit':False,'decision_class':'unknown','reason':'catalog_shadow_or_hold'}
            if decision['admit'] and len(admitted) < options.inject_k:
                admitted.append(mapping[cid]); trace['admitted'].append(cid)
            else:
                if decision['admit']:
                    decision |= {'admit': False, 'decision_class': 'unknown', 'reason': 'injection_limit'}
                trace['rejected'].append(decision)
        return done(admitted, 'admitted' if admitted else 'empty')
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        return done([], 'unconfirmed_feedback:' + str(error))
    except Exception as error:
        trace['error'] = type(error).__name__+': '+str(error)
        return done([], 'optional_retrieval_failure')
