"""One explicitly launched, detached development batch. No new tasks or auto-tuning.

12 fixed single-call arms; six-hour global wall cap, one active batch, no retries.
This module supervises only its own experimental process, never a model server.
"""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import urllib.request

HERE=Path(__file__).resolve().parent


def atomic(path,data):
    temporary=path.with_suffix(path.suffix+'.tmp')
    with temporary.open('w') as handle:
        json.dump(data,handle,indent=2);handle.flush();os.fsync(handle.fileno())
    os.replace(temporary,path)


def now():return datetime.now(timezone.utc).isoformat()


def verify():
    manifest=json.loads((HERE/'cloud-batch-manifest.json').read_text())
    for name,expected in manifest['files'].items():
        assert hashlib.sha256((HERE/name).read_bytes()).hexdigest()==expected,name
    return manifest


def worker(case,arm):
    import run_skill_pilot as pilot
    # Cancellation unwinds the model/tool cleanup blocks. No service is restarted.
    def cancel(signum,frame):raise KeyboardInterrupt('Batch cancellation')
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,cancel)
    row=next(r for r in json.loads((HERE/'inputs.json').read_text()) if r['case']==case)
    result=pilot.run(row,arm)
    return 1 if result.get('error') else 0


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--worker',nargs=2,metavar=('CASE','ARM'))
    args=parser.parse_args()
    manifest=verify()
    os.environ['PATH']='/opt/python/bin:/tools/Xilinx/2026.1/Vivado/bin:/usr/bin:/bin'
    if args.worker:return worker(*args.worker)
    if not args.execute:
        print(json.dumps({'status':'verified_not_started','planned_calls':len(manifest['queue'])}))
        return 0
    lock=(HERE/'batch.lock').open('a')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    status_path=HERE/'batch-status.json'
    if status_path.exists():raise SystemExit('Previous batch status exists; explicit audit required before any restart')
    start=time.monotonic();deadline=start+21600
    state=dict(batch_id=manifest['batch_id'],pid=os.getpid(),started_at=now(),status='preflight',
               planned_calls=len(manifest['queue']),completed=[],current=None,
               wall_limit_s=21600,production_promotions=False,acceptance=False)
    atomic(status_path,state)
    child=None
    def cancel(signum,frame):raise KeyboardInterrupt('Supervisor cancellation')
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,cancel)
    try:
        subprocess.run([sys.executable,str(HERE/'run_skill_pilot.py')],check=True,timeout=60)
        with urllib.request.urlopen('http://127.0.0.1:8010/health',timeout=10) as response:
            assert json.load(response)['status']=='ok'
        for job in manifest['queue']:
            # Never start a new arm without enough time for its declared worst case.
            if deadline-time.monotonic()<1900:
                state['status']='stopped_before_deadline';break
            output=HERE/'runs'/job['case']/job['arm']
            output.mkdir(parents=True,exist_ok=True)
            state.update(status='running',current=job,updated_at=now());atomic(status_path,state)
            with (output/'worker.log').open('a') as stream:
                child=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--worker',job['case'],job['arm']],
                        stdout=stream,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,start_new_session=True)
                try:rc=child.wait(timeout=min(1870,deadline-time.monotonic()))
                except subprocess.TimeoutExpired:
                    child.terminate()
                    try:child.wait(timeout=30)
                    except subprocess.TimeoutExpired:child.kill();child.wait()
                    raise RuntimeError('arm_wall_timeout; stopped without retry')
                child=None
            result_path=output/'result.json'
            if rc or not result_path.is_file():raise RuntimeError('worker_failed_or_missing_result')
            result=json.loads(result_path.read_text())
            if result.get('error'):raise RuntimeError(result['error'])
            state['completed'].append({**job,'result':str(result_path.relative_to(HERE)),
                    'scored_candidate':result['scored_candidate'],
                    'complete_new_draft':result['complete_new_draft'],
                    'checker_accepted':result['checker_accepted'],'judge':result['judge']})
            atomic(HERE/'batch-results.json',state['completed'])
            atomic(status_path,state)
        else:state['status']='completed'
    except BaseException as error:
        state.update(status='stopped_on_error',error=f'{type(error).__name__}: {error}')
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
            try:child.wait(timeout=30)
            except subprocess.TimeoutExpired:child.kill();child.wait()
        state.update(ended_at=now(),elapsed_s=time.monotonic()-start)
        atomic(status_path,state)
        print(json.dumps(state),flush=True)
    return 0 if state['status']=='completed' else 1


if __name__=='__main__':raise SystemExit(main())
