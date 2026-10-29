"""Development-only, paired single-call repair using the unchanged dc32c2f framework.

The explicit in-memory candidate catalog is NOT a production admission promotion.
No recovery calls, automatic injection, holdout data or service reconfiguration.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import tempfile

HERE = Path(__file__).resolve().parent
FRAMEWORK=HERE/'framework' if (HERE/'framework').is_dir() else HERE.parents[1]
sys.path.insert(0, str(FRAMEWORK))
from agent.config import Config
from agent.knowledge.assets import load_assets, Skill
from agent.kit import State
from agent.llm.client import Client
from agent.nodes.generate import generate
from agent.nodes.extract import extract
from agent.nodes.checks import checks
from agent.prompts import TemplateRenderer
from agent.rtl.candidate import CandidateStore
from agent.rtl.task import TaskSpec
from agent.runtime.budget import Budget
from agent.runtime.context import Ctx
from agent.runtime.process import ProcessManager
from agent.runtime.recorder import Recorder


def save(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,delete=False) as handle:
        json.dump(value,handle,indent=2,ensure_ascii=False)
        handle.write('\n');handle.flush();os.fsync(handle.fileno());temporary=handle.name
    os.replace(temporary,path)


def run(row, arm):
    output = HERE / 'runs' / row['case'] / arm
    if (output / 'result.json').exists():
        return json.loads((output / 'result.json').read_text())
    output.mkdir(parents=True, exist_ok=True)
    # An interrupted call must never be silently regenerated when a batch restarts.
    with (output/'started.json').open('x') as handle:
        json.dump({'case':row['case'],'arm':arm,'started_unix':time.time()},handle)
    config = Config(workflow='repair_loop', tools={
        'interface': {'use':'interface_check'}, 'lint':{'use':'vivado_lint'},
        'synth':{'use':'vivado_synth'}}, services={'model':{
            'backend':'openai', 'base_url':'http://127.0.0.1:8010/v1',
            'model':'qwen38-27b-q4-k-m','max_model_len':65536,
            'tokenizer_protocol':'llama_cpp', 'timeout_s':840}})
    started = time.monotonic()
    record = Recorder(output, level='full')
    budget = Budget(900, 20, record=record)
    processes = ProcessManager(budget, record)
    llm = Client(config.services.model, budget, record,
                 {'chat_template_kwargs':{'enable_thinking':True}, 'seed':20261025})
    ctx = Ctx(task=TaskSpec.from_text(row['case'], row['prompt']), budget=budget,
              llm=llm, record=record, processes=processes,
              candidates=CandidateStore(record, output), prompts=TemplateRenderer(), config=config)
    baseline = ctx.candidates.create(row['candidate'], source_stage='frozen_development', round=0)
    ctx.candidates.select(baseline.id, 'frozen_baseline')
    ids = []
    overlay = None
    if arm in ('skill-v2','boundary-only'):
        assets = load_assets(skills=True, rag=False)
        old, _ = assets['skills'][row['skill_id']]
        body_file=row['body_file'] if arm=='skill-v2' else 'boundary-only.txt'
        body = (HERE / body_file).read_text()
        identity = old.model_dump()
        identity.update(version='2.0.0-dev.1' if arm=='skill-v2' else '2.0.0-boundary-control.1', review_status='frozen_candidate_not_default',
                        resource={'path':'dev/optimization-v2/' + body_file,
                                  'sha256':hashlib.sha256(body.encode()).hexdigest()})
        assets['skills'][row['skill_id']] = (Skill.model_validate(identity), body)
        overlay = {'kind':'explicit_development_overlay_not_production', 'skill':identity}
        assets['resources']['development_overlay'] = overlay
        ctx.store[('knowledge_assets', True, False)] = assets
        ids = [row['skill_id']]
    result = dict(case=row['case'], arm=arm, framework_commit='dc32c2fc4ff5d0a489ba27e70809ad9b7387cbb2',
                  dataset_role='development', acceptance=False, production_promotion=False,
                  overlay=overlay, source_candidate_sha256=baseline.code_hash,
                  complete_new_draft=False, checker_accepted=False, error=None)
    try:
        state = State({'feedback':row['feedback'], 'target_id':baseline.id, 'round':0})
        state = generate(ctx, state, max_tokens=16384, temperature=0., top_p=1., timeout_s=840,
                         skill_ids=ids, skill_mode='on' if ids else 'off', rag_mode='off')
        reply = ctx.store[state['reply_id']]
        result.update(finish_reason=reply.finish_reason, final_characters=len(reply.content))
        assemblies=[json.loads(p.read_text()) for p in record.record_dir.glob('knowledge/*.json')]
        expected=ids
        if not assemblies or assemblies[-1].get('sent')!=expected:
            raise ValueError('actual knowledge inclusion differs from assigned arm')
        result['knowledge_sent']=assemblies[-1]['sent']
        state = extract(ctx, state)
        result['complete_new_draft'] = state['has_candidate']
        if state['has_candidate']:
            result['draft_sha256'] = ctx.candidates.get(state['target_id']).code_hash
            state = checks(ctx, state)
            result['checker_accepted'] = state['check_passed']
        result.update(usage=llm.usage_summary(), model_and_checks_s=time.monotonic()-started)
    except Exception as error:
        result['error'] = f'{type(error).__name__}: {error}'
    finally:
        result['scored_candidate'] = 'new' if ctx.candidates.selected_id != baseline.id else 'old'
        result['selected_sha256'] = ctx.candidates.get(ctx.candidates.selected_id).code_hash
        processes.close()
        llm.close()
        record.close()
    save(output/'model-result.json',result)
    if result['error']:
        result.update(judge=None,judge_rc=None,wall_s=time.monotonic()-started)
        save(output/'result.json',result)
        return result
    # Judge is a post-generation process and never contributes to request construction.
    root = Path('/root/rtl-workflows-20261025/rtlagent-context-skill')
    command = ['/opt/python/bin/python', str(root / 'selftest/judge.py'), '--task',
               str(root / 'tasks' / row['task_id']), '--solution', str(output / 'solution.v'),
               '--outdir', str(output / 'judge_logs'), '--timeout','900',
               '--json', str(output / 'judge.json')]
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=930)
        (output / 'judge.log').write_text(proc.stdout + proc.stderr)
        result['judge'] = json.loads((output / 'judge.json').read_text()) if (output / 'judge.json').exists() else {'error':'missing_result'}
        result['judge_rc'] = proc.returncode
        if proc.returncode or result['judge'].get('tool_error') or result['judge'].get('error'):
            result['error']='judge_infrastructure_failure'
    except Exception as error:
        result.update(judge=None,judge_rc=None,error=f'judge: {type(error).__name__}: {error}')
    result['wall_s'] = time.monotonic() - started
    save(output / 'result.json', result)
    print(json.dumps({k:result[k] for k in ('case','arm','complete_new_draft','checker_accepted','scored_candidate','error','judge')}), flush=True)
    return result


if __name__ == '__main__':
    pin=json.loads((HERE/'framework-pin.json').read_text())
    for path,expected in pin['files'].items():
        assert hashlib.sha256((FRAMEWORK/path).read_bytes()).hexdigest()==expected, path
    for row in json.loads((HERE/'inputs.json').read_text()):
        for field in ('candidate','prompt'):
            assert hashlib.sha256(row[field].encode()).hexdigest()==row[field+'_sha256']
    if '--run-cloud-pilot' not in sys.argv:
        print('Framework and input identities verified. No generation requested.')
        raise SystemExit(0)
    os.environ['PATH'] = '/opt/python/bin:/tools/Xilinx/2026.1/Vivado/bin:/usr/bin:/bin'
    rows = json.loads((HERE / 'inputs.json').read_text())
    results = []
    for i, row in enumerate(rows):
        for arm in (('control','skill-v2') if i % 2 == 0 else ('skill-v2','control')):
            result = run(row, arm)
            results.append(result)
            save(HERE / 'pilot-summary.json', results)
            if result['error']:
                raise SystemExit('Stopped after infrastructure/framework error; no retries')
