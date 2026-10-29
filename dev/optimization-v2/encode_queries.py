"""Send only the 13 previously frozen de-identified diagnostics to the embedding service.

No framework files, candidate RTL, task prompts, references or testbenches are uploaded.
The SSH command is the existing runtime's fixed curl-to-loopback embedding transport.
"""
import json
from pathlib import Path
import sys
import time

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE/'framework' if (HERE/'framework').is_dir() else HERE.parents[1]))
from agent.knowledge.runtime import bundle, embed, query_projection
from agent.knowledge.policy import RetrievalOptions
from admission import digest

def main():
    output=HERE/'runtime-query-vectors.json'
    if output.exists():
        raise SystemExit('Existing query cache preserved; do not overwrite')
    b,release=bundle()
    fixtures=json.loads((HERE/'retrieval-fixtures.json').read_text())
    ids={q['query_id'] for q in fixtures['frozen_query_vectors']}
    options=RetrievalOptions(embedding_url='http://127.0.0.1:8011',embedding_transport='ssh',
                             embedding_ssh_host='root@36.150.116.206',embedding_ssh_port=31778,
                             embedding_timeout_s=10.)
    rows=[]
    for q in fixtures['queries']:
            if q['query_id'] not in ids:continue
            assert q['dataset_role']=='development'
            query=query_projection(b,dict(message=q['query_text'],tool=q['tool'],
                        version=q['tool_version'],code=q['error_code']),q['stage'])
            trace={};start=time.perf_counter();vector=embed(b,query,options,trace)
            rows.append(dict(query_id=q['query_id'],query_sha256=digest(query),vector=vector,
                             embedding_ms=(time.perf_counter()-start)*1000,**trace))
            print(q['query_id'],round(rows[-1]['embedding_ms'],1),flush=True)
    assert len(rows)==13
    output.write_text(json.dumps(dict(release_sha256=release,projection='runtime_constructs_none',
                                      model=b['model'],queries=rows),indent=2)+'\n')


if __name__=='__main__':main()
