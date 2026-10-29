"""Versioned admission shared by development and opt-in runtime configurations.

Three independent questions: structural applicability, explicit information already
supplied, and measured repair benefit. Passing the first two does not prove the third.
Unsupported facts fail closed. A lexical witness is not a complete SV parser proof.
"""
import hashlib
import json
import re
import posixpath
from pathlib import Path

from agent.knowledge.retrieval import retrieve as bound_check

F24 = 'repair-replication-concatenation-syntax'
POLICY = 'evidence-v1'
GENVAR = 'repair-generate-loop-index'


def implementation_hash():
    root=Path(__file__).resolve().parents[1]
    files=['knowledge/admission.py','knowledge/retrieval.py','rtl/public_interface.py','rtl/vivado.py']
    return digest({name:digest((root/name).read_text()) for name in files})


def digest(value):
    return hashlib.sha256((value if isinstance(value, str) else json.dumps(
        value, sort_keys=True, separators=(',', ':'))).encode()).hexdigest()


def mask(code):
    # Preserve offsets and line numbers; text in comments or strings is not code.
    return re.sub(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"',
                  lambda m: ''.join('\n' if c == '\n' else ' ' for c in m[0]), code, flags=re.S)


def witnesses(code):
    source = mask(code)
    if any(token in source for token in ('`','\\','/*','*/','"')):
        return []  # Preprocessed/escaped syntax needs a real parser.
    # Narrow, complete assignment shape; no arbitrary expression extrapolation.
    atom = r'[A-Za-z_$][\w$]*(?:\[\s*\d+(?:\s*:\s*\d+)?\s*\])?'
    count = r'(?:[1-9]\d*|[A-Za-z_$][\w$]*)'
    expression = re.compile(r'\bassign\s+' + atom + r'\s*=\s*\{\s*' + count
                            + r'\s*\{\s*' + atom + r'\s*\}\s*(?P<comma>,)\s*'
                            + atom + r'\s*\}\s*;')
    return [{'start':m.start(), 'end':m.end(), 'comma_line':source.count('\n',0,m.start('comma'))+1,
             'span_sha256':digest(code[m.start():m.end()])} for m in expression.finditer(source)]


def supplied_fact(feedback):
    # Compiler/repair feedback and surrounding prose, not embedded candidate RTL.
    text = feedback.casefold()
    if re.search(r"(?:do not|don't|never)[^.\n]{0,120}(?:outer|additional|another)[^.\n]{0,60}(?:brace|concatenation)",text):
        return 'uncertain', 'negated_or_conflicting_advice'
    if re.search(r'\{\s*\{\s*\w+\s*\{[^{}]+\}\s*\}\s*,', text):
        return 'present', 'outer_concat_code_example'
    if re.search(r'(?:wrap|enclose|surround|add).*replication.*(?:outer|additional|another).*'
                 r'(?:concatenation|braces)', text, re.S):
        return 'present', 'outer_concat_instruction'
    if re.search(r'(?:outer|additional|another).*(?:brace|concatenation)', text, re.S):
        return 'uncertain', 'possibly_equivalent_feedback'
    return 'not_explicitly_supplied', None


def source_line(item, check, parent):
    location=re.search(r'\[([^\]\n]+):(\d+)\]',item.get('message',''))
    if not location:return None,'diagnostic_source_location_missing'
    binding=check.details.get('source_binding',{})
    paths=binding.get('paths',[])
    if (binding.get('candidate_sha256')!=parent.code_hash or not isinstance(paths,list)
            or not paths or any(not isinstance(path,str) or not path for path in paths)):
        return None,'source_file_binding_missing'
    if posixpath.normpath(location[1]) not in {posixpath.normpath(path) for path in paths}:
        return None,'diagnostic_source_file_mismatch'
    return int(location[2]),None


def _evidence_decide(card_id, evidence, parent, feedback='', *, supplied_messages=()):
    from .research import scope_guard
    if not scope_guard(card_id):
        return {'card_id': card_id, 'admit': False, 'reason': 'card_frozen', 'decision_class': 'not_needed'}
    from .runtime import bundle
    data, release_hash = bundle()
    result = dict(policy_id=POLICY, release_sha256=release_hash, card_id=card_id,
                  candidate_sha256=parent.code_hash if parent else None,
                  feedback_sha256=digest(feedback), admit=False, applicability='unknown',
                  information_delta='unknown', measured_benefit='not_established',
                  witness=None, default_injection_enabled=False)
    def reject(reason):
        return result | {'reason':reason}
    try:
        if not evidence or not isinstance(evidence.get('execution_id'),str) or not evidence['execution_id']:
            return reject('missing_execution_identity')
        if parent is None or digest(parent.code)!=parent.code_hash:
            return reject('candidate_content_hash_mismatch')
        _, binding = bound_check([], evidence, parent)
        if binding['reason'] != 'no_match':
            return reject(binding['reason'])
        result['binding'] = binding['binding']
        check = evidence['check']
        items = [x for x in check.details['knowledge_diagnostics']['items']
                 if x.get('severity') == 'error' and not x.get('cascade')]
        if not items:
            return reject('no_primary_diagnostic')
        item = items[0]
        if item.get('version') != '2026.1' or item.get('process_status') != 'failed':
            return reject('unknown_version_or_nonfailure')
        if card_id != F24:
            rule = next((r for r in data['rules'] if r['card_id']==card_id), None)
            if not rule:
                return reject('unknown_card')
            result.update(card_version=rule['card_version'],card_sha256=rule['card_sha256'])
            if any(c['card_id']==card_id and c['candidate_sha256']==parent.code_hash
                   and c['feedback_sha256']==digest(feedback) and c['card_version']==rule['card_version']
                   and c['card_sha256']==rule['card_sha256'] for c in data.get('checkpoints',[])):
                return reject('checkpoint_correct_empty')
            if any(s.casefold() in feedback.casefold() for s in rule['skip_if_feedback_contains']):
                return reject('knowledge_already_present')
            if card_id == GENVAR:
                if check.kind != 'lint' or item.get('tool') not in ('xvlog','xelab') or item.get('code') != 'VRFC 10-3365':
                    return reject('primary_diagnostic_outside_predicate')
                line,error=source_line(item,check,parent)
                if error:return reject(error)
                matched = [w for w in generate_witnesses(parent.code)
                           if w['line'] == line]
                if len(matched) != 1:
                    return reject('source_witness_missing_or_ambiguous')
                result.update(witness=matched[0],applicability='bounded_generate_structure')
                advice=item.get('message','')+'\n'+feedback
                if re.search(r'\bgenvar\b',advice,re.I) or any(
                        re.search(r'\bgenvar\b',m.get('content',''),re.I) for m in supplied_messages):
                    result['information_delta']='present'
                    return reject('knowledge_already_present')
                # A sanitized diagnostic omitting the compiler's actionable fact is
                # not evidence that this fact was absent from the actual execution.
                return reject('novelty_not_established')
            return reject('missing_fact_predicate_not_implemented' if rule['decision']=='eligible_when_missing_fact'
                          else rule['decision'])
        result.update(card_version=data['f24_admission']['card_version'],
                      card_sha256=data['f24_admission']['card_sha256'])
        if not (check.kind=='lint' and item.get('tool')=='xvlog' and item.get('code')=='VRFC 10-4982'
                and "syntax error near ','" in item.get('message','').casefold()):
            return reject('primary_diagnostic_outside_predicate')
        line,error=source_line(item,check,parent)
        if error:return reject(error)
        matched = [w for w in witnesses(parent.code) if w['comma_line']==line]
        if len(matched) != 1:
            return reject('source_witness_missing_or_ambiguous')
        result.update(applicability='narrow_lexical_witness', witness=matched[0])
        if any(data['f24']['projection_text'] in m.get('content','') for m in supplied_messages):
            return reject('knowledge_already_present')
        surrounding = '\n'.join(re.sub(r'```.*?```', '', m.get('content',''), flags=re.S)
                                for m in supplied_messages)
        delta, fact = supplied_fact(feedback+'\n'+surrounding)
        result.update(information_delta=delta, supplied_fact=fact)
        if delta=='present':
            return reject('knowledge_already_present')
        if delta=='uncertain':
            return reject('novelty_not_established')
        return result | {'admit':True, 'reason':'development_eligible_not_proven_useful'}
    except (KeyError, TypeError, AttributeError, ValueError):
        return reject('invalid_evidence')


def generate_witnesses(code):
    """Bounded structural recognizer, not a general SV parser. Unknown syntax rejects.

    Module/signal names are not fixed. Explicit generate regions, missing index
    declarations and small literal/parameter bounds are established separately.
    Procedural, conditional/nested generate, macros and escaped names are unsupported.
    """
    from agent.rtl.public_interface import _integer
    source=mask(code);result=[]
    if any(t in source for t in ('`','\\','"','/*','*/')):return []
    for module in re.finditer(r'\bmodule\s+(?P<name>[A-Za-z_]\w*)\b(?P<body>.*?)\bendmodule\b',source,re.S):
        body=module['body'];base=module.start('body')
        if re.search(r'\b(?:module|typedef|import|class|function|task|always\w*|initial)\b',body):continue
        parameters={}
        for p in re.finditer(r'\b(?:parameter|localparam)\s+(?:integer\s+|int\s+)?([A-Za-z_]\w*)\s*=\s*([^,;)]+)',body):
            try:parameters[p[1]]=_integer(p[2],parameters)
            except ValueError:pass
        for region in re.finditer(r'\bgenerate\b(?P<content>.*?)\bendgenerate\b',body,re.S):
            content=region['content']
            if re.search(r'\b(?:generate|always\w*|initial|function|task|if|case)\b',content):continue
            loops=list(re.finditer(r'\bfor\s*\(\s*(?P<i>[A-Za-z_]\w*)\s*=\s*(?P<start>[^;]+);\s*'
                r'(?P=i)\s*<\s*(?P<bound>[^;]+);\s*(?P=i)\s*=\s*(?P=i)\s*\+\s*1\s*\)',content))
            if len(loops)!=1:continue
            loop=loops[0];index=loop['i']
            # Require undeclared index and reject ambiguous scope/ownership.
            if re.search(r'\b(?:genvar|integer|int|logic|reg|wire|input|output|parameter|localparam|bit|byte|shortint|longint|time|real|string|event)\b[^;()]*\b'+re.escape(index)+r'\b',body):continue
            try:start=_integer(loop['start'],parameters);bound=_integer(loop['bound'],parameters)
            except ValueError:continue
            if not 0 <= start < bound <= 4096:continue
            offset=base+region.start('content')+loop.start()
            result.append(dict(module=module['name'],index=index,start=start,bound=bound,
                line=source.count('\n',0,offset)+1,scope='explicit_generate',index_declaration='absent',
                source_sha256=digest(code),bound_kind='elaboration_constant'))
    return result


def contract(card_id):
    """Sidecar fields, bound to frozen card identity; do not mutate embedding text."""
    from .runtime import bundle
    data,_=bundle();card=next((c for c in data['cards']+[data['f24']] if c['card_id']==card_id),None)
    if card is None:return None
    rule=next((r for r in data['rules'] if r['card_id']==card_id),{})
    return dict(card_id=card_id,card_version=card['version'],card_sha256=digest(card),
        evidence_already_known=dict(source='Bound primary compiler diagnostic and current source location',
                                    triggers=rule.get('trigger_variants',[])),
        additional_knowledge=card.get('guidance',[card['projection_text']]),
        redundant_when=rule.get('skip_if_feedback_contains',[])+
            (['An outer concatenation example or equivalent instruction is already supplied.'] if card_id==F24 else []),
        missing_fact_claim=rule.get('requires_missing_fact', ['Requires a supported source witness and no supplied correction.']),
        semantic_novelty_proven=False)


def classify(reason):
    if reason in ('knowledge_already_present','checkpoint_correct_empty','not_applicable','model_not_needed'):
        return 'not_needed'
    if reason in ('invalid_evidence','invalid_check_evidence','candidate_content_hash_mismatch','optional_retrieval_failure',
                  'retrieval_unavailable','asset_failure'):
        return 'runtime_failure'
    return 'unknown'


def decide(card_id,evidence,parent,feedback='',*,supplied_messages=(),policy='evidence-v1'):
    if policy not in ('frozen-v1','evidence-v1'):raise ValueError('unknown admission policy')
    from .research import scope_guard
    if not scope_guard(card_id):
        return {'card_id': card_id, 'admit': False, 'reason': 'card_frozen', 'decision_class': 'not_needed'}
    if policy=='evidence-v1':
        result=_evidence_decide(card_id,evidence,parent,feedback,supplied_messages=supplied_messages)
    else:
        from .runtime import bundle
        data,_=bundle();rule=next((r for r in data['rules'] if r['card_id']==card_id),None)
        all_text='\n'.join(m.get('content','') for m in supplied_messages)
        reason=None
        try:
            _, binding=bound_check([],evidence,parent)
            valid=bool(evidence.get('execution_id')) and parent is not None and digest(parent.code)==parent.code_hash and binding['reason']=='no_match'
        except (KeyError,TypeError,AttributeError,ValueError):valid=False
        if not valid:
            reason='invalid_evidence'
        elif card_id==F24:
            from .runtime import f24_matches
            items=[i for i in evidence['check'].details['knowledge_diagnostics']['items']
                   if i.get('severity')=='error' and not i.get('cascade')]
            if not items or not f24_matches(parent,items[0],evidence['check'].kind):
                reason='primary_diagnostic_outside_predicate'
            elif data['f24']['projection_text'] in all_text or '{{N{expr}}, slice}' in all_text:
                reason='knowledge_already_present'
        elif rule:
            reason=rule['decision']
            if any(c['card_id']==card_id and c['card_version']==rule['card_version'] and
                   c['card_sha256']==rule['card_sha256'] and c['candidate_sha256']==parent.code_hash and
                   c['feedback_sha256']==digest(feedback) for c in data.get('checkpoints',[])):
                reason='checkpoint_correct_empty'
            elif any(s.casefold() in all_text.casefold() for s in rule['skip_if_feedback_contains']):
                reason='knowledge_already_present'
            elif reason=='eligible_when_missing_fact':reason='missing_fact_not_mechanically_established'
        else:reason='unknown_card'
        result=dict(admit=reason is None,reason=reason or 'frozen_policy_eligible',card_id=card_id)
    result.update(policy_id=policy,decision_class='eligible' if result['admit'] else classify(result['reason']),
                  measured_benefit='not_established')
    result['information_contract']=contract(card_id)
    return result
