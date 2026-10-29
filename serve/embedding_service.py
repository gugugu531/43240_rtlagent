"""Launch the hash-pinned CPU embedding service for the catalog profile."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))

def file_hash(path):
    result=hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda:source.read(8*1024*1024),b''):result.update(block)
    return result.hexdigest()

def main():
    p=argparse.ArgumentParser();p.add_argument('--binary',type=Path,required=True);p.add_argument('--model',type=Path,required=True);p.add_argument('--port',type=int,default=8020);p.add_argument('--check-only',action='store_true');args=p.parse_args()
    from agent.knowledge.research import load_bundle
    data=load_bundle();lock=json.loads((ROOT/'knowledge/embedding-runtime-lock.json').read_text())
    if file_hash(args.model)!=data['model']['file_sha256']:raise ValueError('embedding_weight_hash_mismatch')
    if file_hash(args.binary)!=lock['binary_sha256']:raise ValueError('embedding_program_hash_mismatch')
    for name,digest in lock['libraries'].items():
        if file_hash(args.binary.parent/name)!=digest:raise ValueError('embedding_library_hash_mismatch:'+name)
    if not 1<=args.port<=65535:raise ValueError('embedding_invalid_port')
    cmd=[str(args.binary),'-m',str(args.model),'--alias',data['model']['runtime_alias'],'--host','127.0.0.1','--port',str(args.port),'--embedding','--pooling','last','-c','4096','-b','2048','-ub','2048','-np','1','-t','4','--no-webui']
    if args.check_only:
        print(json.dumps({'status':'passed','weight_sha256':data['model']['file_sha256'],'runtime_binary_sha256':lock['binary_sha256'],'libraries_verified':len(lock['libraries']),'command':cmd}));return
    env=dict(os.environ);env['LD_LIBRARY_PATH']=str(args.binary.parent)+':'+env.get('LD_LIBRARY_PATH','')
    os.execvpe(cmd[0],cmd,env)

if __name__=='__main__':main()
