"""Fixed release / fixed development admission; retrieval metrics are not repair gains."""
import json
from collections import defaultdict
from pathlib import Path
import sys
import time

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE/'framework' if (HERE/'framework').is_dir() else HERE.parents[1]))
from agent.knowledge.runtime import bundle, bm25, query_projection
from admission import decide, digest
from test_admission import fixture

def project(query, instruction):
    return (f"Instruct: {instruction}\nQuery: diagnostic: {query['query_text']}"
            f"\nstage: {query['stage']}\ntool: {query['tool']}\ntool version: {query['tool_version']}"
            f"\nerror code: {query.get('error_code') or 'none'}\nconstructs: {', '.join(query['constructs']) or 'none'}")


def main():
    release,release_hash=bundle()
    fixtures=json.loads((HERE/'retrieval-fixtures.json').read_text())
    assert fixtures['dataset_role']=='development'
    vectors={q['query_id']:q for q in fixtures['frozen_query_vectors']}
    queries=[]
    # Only the 13 already frozen development query IDs enter this evaluation.
    for q in fixtures['queries']:
            if q['query_id'] not in vectors:
                continue
            assert q['dataset_role']=='development'
            projection=project(q,fixtures['projection']['query_instruction'])
            assert digest(json.dumps(projection,ensure_ascii=False,sort_keys=True,separators=(',',':')))==vectors[q['query_id']]['text_sha256']
            queries.append(q)
    assert len(queries)==len(vectors)==13
    runtime_cache=None
    if '--runtime-projection' in sys.argv:
        runtime_cache=json.loads((HERE/'runtime-query-vectors.json').read_text())
        assert runtime_cache['release_sha256']==release_hash
        vectors={q['query_id']:q for q in runtime_cache['queries']}
        assert set(vectors)=={q['query_id'] for q in queries}
        for q in queries:
            expected=query_projection(release,dict(message=q['query_text'],tool=q['tool'],
                         version=q['tool_version'],code=q['error_code']),q['stage'])
            assert vectors[q['query_id']]['query_sha256']==digest(expected)
    labels={q['family_id']:q for q in fixtures['labels']}
    # The fixed index projection retains diagnostic constructs. This is explicitly
    # an offline rank comparison, not a claim that runtime's constructs:none is equal.
    rows=[]
    for q in queries:
        cards=[c for c in release['cards'] if (not c['stages'] or q['stage'] in c['stages'])
               and (not c['tools'] or q['tool'] in c['tools'])
               and (not c['tool_versions'] or q['tool_version'] in c['tool_versions'])]
        ids={c['card_id'] for c in cards}
        t=time.perf_counter()
        exact=sorted([(c['card_id'],100.) for c in cards if q['error_code'] in c['error_codes']])
        exact_ms=(time.perf_counter()-t)*1000
        t=time.perf_counter(); lexical=bm25(cards,q['query_text']);bm25_ms=(time.perf_counter()-t)*1000
        t=time.perf_counter(); vector=vectors[q['query_id']]['vector']
        dense=sorted([(d['card_id'],sum(x*y for x,y in zip(vector,d['vector'])))
                      for d in release['documents'] if d['card_id'] in ids],key=lambda r:(-r[1],r[0]))
        dense_ms=(time.perf_counter()-t)*1000
        t=time.perf_counter();scores=defaultdict(float)
        for ranking in (exact,lexical,dense):
            for rank,(key,_) in enumerate(ranking,1):scores[key]+=1/(60+rank)
        hybrid=sorted(scores.items(),key=lambda r:(-r[1],r[0]))
        hybrid_ms=exact_ms+bm25_ms+dense_ms+(time.perf_counter()-t)*1000
        relevant=set(labels[q['family_id']]['must_retrieve'])
        allowed=relevant|set(labels[q['family_id']]['may_retrieve'])
        for strategy,ranking,ms in [('exact',exact,exact_ms),('bm25',lexical,bm25_ms),
                                    ('dense',dense,dense_ms),('hybrid',hybrid,hybrid_ms)]:
            top=[c for c,_ in ranking[:5]]
            # Queries lack a bound original RTL/check. Never manufacture eligibility.
            decisions=[decide(key,None,None,q['query_text']) for key in top]
            rows.append(dict(query_id=q['query_id'],family=q['family_id'],strategy=strategy,top5=top,
                             recall5=len(relevant&set(top))/len(relevant),
                             top1_relevant=bool(top and top[0] in allowed),
                             reciprocal_rank=next((1/(i+1) for i,key in enumerate(top) if key in relevant),0.),
                             ranking_only_ms=ms,admission=decisions,sent=[],repair_gain=None))
    summary={}
    for strategy in ('exact','bm25','dense','hybrid'):
        selected=[r for r in rows if r['strategy']==strategy]
        summary[strategy]={k:sum(r[k] for r in selected)/len(selected)
                           for k in ('recall5','top1_relevant','reciprocal_rank','ranking_only_ms')}
        summary[strategy].update(query_count=13,proven_repair_benefit=None,
                                runtime_admission='not_evaluable_without_bound_RTL_and_execution')
    report=dict(status='development_only_not_acceptance',framework_commit='dc32c2f',
                release_sha256=release_hash,index_sha256=release['index_sha256'],
                policy='development-admission-v2.1',retrieve_k=5,inject_k=1,rrf_k=60,
                label_status='historical_topical_oracle_not_proof_of_marginal_value',
                holdout_used=False,queries_sha256=digest(queries),
                query_projection='runtime_constructs_none' if runtime_cache else 'frozen_offline_with_constructs_not_runtime_constructs_none',
                latency_scope='local_ranking_only_excludes_query_encoding_and_generation',
                strategies=summary,rows=rows)
    if runtime_cache:
        report['query_encoding_ms']=[q['embedding_ms'] for q in runtime_cache['queries']]
    filename='runtime-retrieval-comparison.json' if runtime_cache else 'retrieval-comparison.json'
    (HERE/filename).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(summary,indent=2))


if __name__=='__main__':main()
