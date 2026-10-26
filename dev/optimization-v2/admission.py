"""Development policy v2. No production registration or automatic injection.

Three independent questions: structural applicability, explicit information already
supplied, and measured repair benefit. Passing the first two does not prove the third.
Unsupported facts fail closed. A lexical witness is not a complete SV parser proof.
"""
import hashlib
import json
import re

from agent.knowledge.runtime import bundle
from agent.knowledge.retrieval import retrieve as bound_check

F24 = 'repair-replication-concatenation-syntax'
POLICY = 'development-admission-v2.1'


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
    # Only compiler/repair feedback, not candidate RTL or the public specification.
    text = feedback.casefold()
    if re.search(r'\{\s*\{\s*\w+\s*\{[^{}]+\}\s*\}\s*,', text):
        return 'present', 'outer_concat_code_example'
    if re.search(r'(?:wrap|enclose|surround|add).*replication.*(?:outer|additional|another).*'
                 r'(?:concatenation|braces)', text, re.S):
        return 'present', 'outer_concat_instruction'
    if re.search(r'(?:outer|additional|another).*(?:brace|concatenation)', text, re.S):
        return 'uncertain', 'possibly_equivalent_feedback'
    return 'not_explicitly_supplied', None


def decide(card_id, evidence, parent, feedback='', *, supplied_messages=()):
    data, release_hash = bundle()
    result = dict(policy_id=POLICY, release_sha256=release_hash, card_id=card_id,
                  candidate_sha256=parent.code_hash if parent else None,
                  feedback_sha256=digest(feedback), admit=False, applicability='unknown',
                  information_delta='unknown', measured_benefit='not_established',
                  witness=None, production_enabled=False)
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
            return reject('missing_fact_predicate_not_implemented' if rule['decision']=='eligible_when_missing_fact'
                          else rule['decision'])
        result.update(card_version=data['f24_admission']['card_version'],
                      card_sha256=data['f24_admission']['card_sha256'])
        if not (check.kind=='lint' and item.get('tool')=='xvlog' and item.get('code')=='VRFC 10-4982'
                and "syntax error near ','" in item.get('message','').casefold()):
            return reject('primary_diagnostic_outside_predicate')
        located = re.search(r'\[[^\]\n]+:(\d+)\]', item.get('message',''))
        if not located:
            return reject('diagnostic_source_location_missing')
        matched = [w for w in witnesses(parent.code) if w['comma_line']==int(located[1])]
        if len(matched) != 1:
            return reject('source_witness_missing_or_ambiguous')
        result.update(applicability='narrow_lexical_witness', witness=matched[0])
        if any(data['f24']['projection_text'] in m.get('content','') for m in supplied_messages):
            return reject('knowledge_already_present')
        delta, fact = supplied_fact(feedback)
        result.update(information_delta=delta, supplied_fact=fact)
        if delta=='present':
            return reject('knowledge_already_present')
        if delta=='uncertain':
            return reject('novelty_not_established')
        return result | {'admit':True, 'reason':'development_eligible_not_proven_useful'}
    except (KeyError, TypeError, AttributeError, ValueError):
        return reject('invalid_evidence')
