"""Opt-in test adapter; never imported by the production package.

Ranking stays exactly at the frozen framework release. Only the experimental
admission contract changes. No lexical-match fallback may invent a missing card.
"""
from agent.knowledge.runtime import retrieve_runtime, bundle
from admission import decide, POLICY


def retrieve_development(evidence, parent, options, messages, raw_feedback=None):
    _, trace=retrieve_runtime(evidence,parent,options,messages,raw_feedback)
    data,_=bundle()
    mapping={c['card_id']:c for c in data['cards']}
    mapping[data['f24']['card_id']]=data['f24']
    trace['frozen_admission']={'admitted':trace['admitted'],'rejected':trace['rejected'],'reason':trace['reason']}
    trace.update(admitted=[],rejected=[],development_policy=POLICY,production_enabled=False)
    admitted=[]
    for row in trace['retrieved']:
        decision=decide(row['id'],evidence,parent,raw_feedback or '',supplied_messages=messages)
        if decision['admit'] and not admitted:
            admitted.append(mapping[row['id']]);trace['admitted'].append(row['id'])
        else:
            trace['rejected'].append(dict(id=row['id'],reason=decision['reason'] if not decision['admit'] else 'injection_limit'))
        trace.setdefault('predicate_decisions',[]).append(decision)
    if trace['retrieved']:
        trace['reason']='admitted' if admitted else 'correct_empty'
    return admitted,trace
