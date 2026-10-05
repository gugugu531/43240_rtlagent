"""Configuration, frozen experiment inputs and lifecycle acceptance."""
from pathlib import Path
from unittest.mock import patch
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from agent.core.configuration import load_config,resolve_config,RunOverrides,ConfigError,build_run_spec
from agent.core.task import TaskSpec
from agent.recording.metrics import CompletedSample,ModelMetric,MetricResult,collect_metrics
from agent.services.processes import ProcessRequest
from dev.tools.experiment import (TaskSelection,select_tasks,parse_experiment,build_sample_plan,
                                  ExperimentRunner,SampleResult,summarize_experiment,ResolvedExperiment)
from dev.tools.metrics.judge import JudgeMetric


class ConfigurationTests(unittest.TestCase):
    def config(self, root, body):
        path = root/'config.yaml';path.write_text('schema_version: 1\n'+body)
        return load_config(path)

    def test_yaml_environment_cli_provenance_and_secret_reference(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            doc=self.config(root,'workflow: {type: repair_loop}\nservices:\n  model:\n    api_key_env: PRIVATE_MODEL_KEY\n    timeout_s: 50\nruntime:\n  recording: {root: records}\n')
            resolved=resolve_config(doc,env={'LLM_TIMEOUT_S':'80','PRIVATE_MODEL_KEY':'sensitive-value'},
                                    overrides=RunOverrides({'services.model.timeout_s':90}))
            self.assertEqual(resolved.agent.services.model.timeout_s,90)
            self.assertEqual(resolved.sources['services.model.timeout_s'],'cli')
            self.assertEqual(resolved.agent.runtime.recording_root,root/'records')
            self.assertEqual(resolved.agent.services.model.api_key,'sensitive-value')
            self.assertNotIn('sensitive-value',json.dumps(resolved.public_dict()))
            self.assertEqual(resolved.public_dict()['effective']['services']['model']['api_key_env'],'PRIVATE_MODEL_KEY')

    def test_duplicate_unknown_alias_and_invalid_scalar_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            for body in ['workflow: {type: a, type: b}\n','bindings: {}\n','imports: &x [a]\nworkflow: {type: *x}\n',
                         'runtime: {deadline_s: true}\n','runtime: {deadline_s: .nan}\n','imports: [abc, abc]\n']:
                with self.subTest(body=body),self.assertRaises((ConfigError,ValueError)):
                    resolve_config(self.config(root,body),env={})

    def test_http_budget_only_shrinks_and_reserve_is_preserved(self):
        with tempfile.TemporaryDirectory() as t:
            cfg=resolve_config(self.config(Path(t),'runtime: {deadline_s: 30, reserve_s: 2}\n'),env={})
            task=TaskSpec.from_text('x','Implement TopModule.')
            for hard,expected in [(100,30),(1,1)]:
                spec=build_run_spec(task,cfg,output_dir=Path(t)/'out',started_at=time.monotonic(),hard_deadline_s=hard)
                self.assertEqual(spec.options.deadline_s,expected)
                self.assertEqual(spec.options.reserve_s,2)

    def test_bad_config_leaves_trace_and_empty_answer_without_exposing_values(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t); task=root/'task';task.mkdir();(task/'prompt.txt').write_text('Implement TopModule.')
            path=root/'bad.yaml';path.write_text('schema_version: 1\nservices:\n  model:\n    api_key: sensitive-test-secret\n')
            result=subprocess.run([str(ROOT/'run.sh'),str(task),str(root/'out'),'--config',str(path)],
                                  env=dict(os.environ,LLM_BACKEND='mock'),capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0)
            self.assertEqual((root/'out/solution.v').read_text(),'')
            trace=(root/'out/trace.jsonl').read_text()
            self.assertTrue(trace);self.assertNotIn('sensitive-test-secret',trace)
            self.assertTrue(any(json.loads(l).get('reason')=='configuration_or_entry_error' for l in trace.splitlines()))

    def test_shell_configuration_and_record_paths_follow_callers_directory(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);task=root/'task';task.mkdir()
            (task/'prompt.txt').write_text('module TopModule(input a, output q);')
            (root/'options.yaml').write_text('schema_version: 1\n')
            result=subprocess.run([str(ROOT/'run.sh'),'task','out','--config','options.yaml','--record-root','evidence'],
                cwd=root,env=dict(os.environ,LLM_BACKEND='mock'),capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0)
            self.assertIn('module TopModule',(root/'out/solution.v').read_text())
            self.assertEqual(len(list((root/'evidence').glob('*/run.json'))),1)

    def test_explicit_tools_are_per_instance(self):
        from agent.tools import RtlToolchain
        from agent.core.config import ToolConfig
        with tempfile.TemporaryDirectory() as t:
            a=RtlToolchain(config=ToolConfig(part='part_a',bin_dir=t,temp_dir=t))
            b=RtlToolchain(config=ToolConfig(part='part_b',temp_dir='/tmp'))
            self.assertFalse(a.available);self.assertEqual(a.config.part,'part_a')
            self.assertEqual(b.config.part,'part_b')


class ExperimentTests(unittest.TestCase):
    def setup_task(self, root):
        task=root/'tasks'/'one';task.mkdir(parents=True)
        (task/'prompt.txt').write_text('I would like you to implement a module named TopModule with the following interface.\n - input a\n - output q\n')
        (task/'task.json').write_text('{"reference_module":"forbidden.sv"}')
        (task/'forbidden.sv').write_text('reference-marker-must-not-be-visible')
        return task

    def config(self, root, extra=''):
        path=root/'config.yaml'
        path.write_text('schema_version: 1\nservices: {model: {backend: mock}}\nruntime: {deadline_s: 10, reserve_s: 1}\nexperiment:\n  tasks: {root: tasks, ids: [one]}\n  metrics: [runtime, model]\n  samples: 2\n  solve_jobs: 2\n  output_root: runs\n'+extra)
        return resolve_config(load_config(path),env={})

    def test_selection_missing_duplicate_excluded_and_frozen_hashes(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);task=self.setup_task(root)
            manifest=select_tasks(TaskSelection(root/'tasks',('one',)))
            self.assertNotIn('reference',json.dumps(manifest.public_dict()))
            for ids in [('missing',),('one','one'),('../one',)]:
                with self.assertRaises(ConfigError):select_tasks(TaskSelection(root/'tasks',ids))
            excluded=root/'excluded.txt';excluded.write_text('one\n')
            with self.assertRaises(ConfigError):select_tasks(TaskSelection(root/'tasks',('one',),exclude_path=excluded))
            old=manifest.digest;(task/'prompt.txt').write_text('changed')
            self.assertNotEqual(old,select_tasks(TaskSelection(root/'tasks',('one',))).digest)

    def test_parallel_samples_use_shared_runtime_and_do_not_start_judge(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);self.setup_task(root);config=self.config(root);exp=parse_experiment(config)
            manifest=select_tasks(exp.selection)
            with patch.object(JudgeMetric,'collect',side_effect=AssertionError('judge was not selected')):
                result=ExperimentRunner(write_notes=False).run(build_sample_plan(manifest,exp),ResolvedExperiment(config,exp,manifest))
            self.assertEqual(len(result.samples),2)
            run_ids=[]
            for sample in result.samples:
                self.assertIn('module TopModule',(sample.output_dir/'solution.v').read_text())
                trace=(sample.output_dir/'trace.jsonl').read_text()
                self.assertNotIn('reference-marker',trace)
                info=json.loads((sample.output_dir/'run_locator.json').read_text());run_ids.append(info['run_id'])
                task=json.loads((Path(info['record_dir'])/'task.json').read_text())
                self.assertNotIn('reference',json.dumps(task))
                self.assertEqual(sample.metrics[1].values['attempts'],1)
                self.assertIsNone(sample.metrics[1].values['completion_tokens']['known_total'])
                self.assertEqual(json.loads((sample.output_dir/'config.json').read_text())['parent_config'],str(result.output_dir/'config.json'))
            self.assertEqual(len(set(run_ids)),2)
            snapshot=result.output_dir/'source'
            self.assertFalse(any('forbidden' in str(p) for p in snapshot.rglob('*')))
            copied=snapshot/'agent/main.py'
            self.assertEqual(copied.read_text(),(ROOT/'agent/main.py').read_text())

    def test_explicit_external_record_root_is_not_discarded_by_experiment(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);self.setup_task(root);cfg=self.config(root)
            cfg=resolve_config(cfg.document,env={},overrides=RunOverrides({'runtime.recording.root':str(root/'external')}))
            exp=parse_experiment(cfg,{'samples':1});manifest=select_tasks(exp.selection)
            result=ExperimentRunner(write_notes=False).run(build_sample_plan(manifest,exp),ResolvedExperiment(cfg,exp,manifest))
            locator=json.loads((result.samples[0].output_dir/'run_locator.json').read_text())
            self.assertTrue(Path(locator['record_dir']).is_relative_to(root/'external'))
            self.assertTrue((Path(locator['record_dir'])/'run.json').is_file())

    def test_registered_extension_receives_isolated_nodes_and_metrics(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);self.setup_task(root)
            (root/'custom_workflow.py').write_text("""
from agent.core.components import Component
from agent.core.registry import NODE_REGISTRY,WORKFLOW_REGISTRY,build_node
from agent.workflows.single_generate import SingleGenerate
@NODE_REGISTRY.register('test_counter')
class Counter(Component):
    def __init__(self): self.count=0
    def run(self,ctx,input):
        self.count+=1
        ctx.emit('counter',value=self.count)
        return self.count
@WORKFLOW_REGISTRY.register('test_custom')
class Custom(Component):
    def __init__(self):
        self.counter=build_node('test_counter')
        self.base=SingleGenerate()
    def run(self,ctx):
        ctx.execute(self.counter,None)
        return self.base.run(ctx)
""")
            cfg=self.config(root)
            cfg=resolve_config(cfg.document,env={},overrides=RunOverrides({'imports':['custom_workflow'],'workflow.type':'test_custom'}))
            exp=parse_experiment(cfg);manifest=select_tasks(exp.selection)
            with patch.dict(os.environ,PYTHONPATH=str(root)+os.pathsep+os.environ.get('PYTHONPATH','')):
                result=ExperimentRunner(write_notes=False).run(build_sample_plan(manifest,exp),ResolvedExperiment(cfg,exp,manifest))
            for sample in result.samples:
                events=[json.loads(l) for l in (sample.output_dir/'trace.jsonl').read_text().splitlines()]
                counters=[e['value'] for e in events if e.get('event')=='counter']
                self.assertEqual(counters,[1])
                self.assertEqual(sample.metrics[1].values['attempts'],1)
            source=json.loads((result.output_dir/'source/manifest.json').read_text())
            self.assertFalse(source['complete'])
            self.assertEqual(source['unresolved_extensions'],['custom_workflow'])

    def test_real_http_transport_runs_agent_and_original_baseline(self):
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers.get('Content-Length',0)))
                body=json.dumps({'id':'integration','model':'test-model','choices':[{'finish_reason':'stop',
                     'message':{'content':'module TopModule(input a, output q); assign q=a; endmodule'}}],
                     'usage':{'prompt_tokens':1,'completion_tokens':2}}).encode()
                self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with tempfile.TemporaryDirectory() as t:
                root=Path(t);self.setup_task(root);cfg=self.config(root)
                cfg=resolve_config(cfg.document,env={},overrides=RunOverrides({'services.model.backend':'openai',
                    'services.model.model':'test-model','services.model.base_url':f'http://127.0.0.1:{server.server_address[1]}/v1'}))
                exp=parse_experiment(cfg,{'modes':('agent','baseline'),'samples':1});manifest=select_tasks(exp.selection)
                result=ExperimentRunner(write_notes=False).run(build_sample_plan(manifest,exp),ResolvedExperiment(cfg,exp,manifest))
                self.assertEqual({s.mode for s in result.samples},{'agent','baseline'})
                for sample in result.samples:
                    self.assertEqual(sample.solve['status'],'ok')
                    self.assertIn('assign q=a',(sample.output_dir/'solution.v').read_text())
                    self.assertEqual(sample.metrics[1].values['completion_tokens']['known_total'],2)
        finally:server.shutdown();server.server_close()

    def test_whole_experiment_signal_preserves_manifest_and_cancelled_samples(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);self.setup_task(root);cfg=self.config(root)
            (root/'blocked_workflow.py').write_text("""
import time
from agent.core.components import Component
from agent.core.registry import WORKFLOW_REGISTRY
@WORKFLOW_REGISTRY.register('blocked_experiment')
class Blocked(Component):
    def run(self,ctx):
        ctx.emit('blocked_started')
        time.sleep(30)
        return ctx.finish()
""")
            path=root/'config.yaml';text=path.read_text().replace('runtime: {deadline_s: 10, reserve_s: 1}',
                'runtime: {deadline_s: 40, reserve_s: 1}')
            path.write_text(text+'imports: [blocked_workflow]\nworkflow: {type: blocked_experiment}\n')
            env=dict(os.environ,PYTHONPATH=str(root)+os.pathsep+os.environ.get('PYTHONPATH',''))
            proc=subprocess.Popen([sys.executable,str(ROOT/'dev/tools/run.py'),'--config',str(path)],env=env,
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            try:
                deadline=time.monotonic()+5;run=None
                while time.monotonic()<deadline:
                    traces=list((root/'runs').glob('*/samples/agent/one/s*/trace.jsonl'))
                    if traces and any('blocked_started' in p.read_text() for p in traces):
                        run=next((root/'runs').iterdir());break
                    time.sleep(.02)
                self.assertIsNotNone(run)
                proc.send_signal(signal.SIGTERM);proc.wait(timeout=4)
                self.assertEqual(proc.returncode,130)
                self.assertEqual(json.loads((run/'summary.json').read_text())['status'],'cancelled')
                self.assertEqual(json.loads((run/'tasks.json').read_text())['tasks'][0]['task_id'],'one')
                samples=json.loads((run/'metrics.json').read_text())
                self.assertEqual(len(samples),2)
                self.assertTrue(all(s['solve']['status']=='cancelled' for s in samples))
                for p in run.glob('samples/agent/one/s*/records/*/supervision.json'):
                    self.assertEqual(json.loads(p.read_text())['unreaped_pids'],[])
            finally:
                if proc.poll() is None:proc.kill();proc.wait()
                # Generated development note belongs to this test only.
                if run:
                    (ROOT/'dev/docs/experiments'/f'{run.name}.md').unlink(missing_ok=True)

    def test_inputs_modified_after_selection_are_explicit_errors(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);task=self.setup_task(root);cfg=self.config(root);exp=parse_experiment(cfg)
            manifest=select_tasks(exp.selection);(task/'prompt.txt').write_text('changed')
            result=ExperimentRunner(write_notes=False).run(build_sample_plan(manifest,exp),ResolvedExperiment(cfg,exp,manifest))
            self.assertTrue(all(s.solve['status']=='error' for s in result.samples))
            self.assertTrue(all(s.metrics[1].values['attempts']==0 for s in result.samples))

    def test_mock_baseline_and_invalid_cli_overrides_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);self.setup_task(root);cfg=self.config(root)
            for overrides in [{'samples':0},{'solve_jobs':-1},{'metrics':('model','model')},{'modes':('agent','baseline')}]:
                with self.assertRaises(ConfigError):parse_experiment(cfg,overrides)

    def test_cancel_terminates_process_group_and_collects_process_log(self):
        runner=ExperimentRunner(write_notes=False)
        with tempfile.TemporaryDirectory() as t:
            out=Path(t);box=[]
            thread=threading.Thread(target=lambda:box.append(runner._process(
                ProcessRequest((sys.executable,'-u','-c','import time; print("started");time.sleep(30)'),t,30),out)))
            thread.start()
            deadline=time.monotonic()+3
            while time.monotonic()<deadline:
                logs=list((out/'process_logs').glob('*.log'))
                if logs and 'started' in logs[0].read_text():break
                time.sleep(.02)
            runner.cancel();thread.join(2)
            self.assertFalse(thread.is_alive());self.assertEqual(box,[None])
            self.assertIn('started',next((out/'process_logs').glob('*.log')).read_text())

    def test_metric_error_not_zero_score_and_official_aggregation(self):
        bad=MetricResult('judge',1,'error',{})
        good=MetricResult('judge',1,'ok',{'verdict':{'level':3,'coefficient':1,'tool_error':None,'elapsed_s':0}})
        summary=summarize_experiment([SampleResult('a','agent',0,Path('/tmp'),{},(bad,)),
                                     SampleResult('b','agent',0,Path('/tmp'),{},(good,))])
        self.assertEqual(summary['modes']['agent']['judge']['set_score'],1)
        self.assertEqual(summary['modes']['agent']['judge']['tool_errors'],1)
        self.assertEqual(summary['modes']['agent']['judge']['scored_tasks'],1)


class MetricsTests(unittest.TestCase):
    def test_interrupted_and_failed_calls_preserve_unknown_tokens(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);rows=[{'tool':'llm','event':'started','call_id':'m1'},
                              {'tool':'llm','event':'started','call_id':'m2'},
                              {'tool':'llm','event':'failed','call_id':'m2','kind':'timeout'}]
            (root/'trace.jsonl').write_text('\n'.join(json.dumps(x) for x in rows))
            result=ModelMetric().collect(CompletedSample('x','agent',0,root))
            self.assertEqual(result.status,'partial');self.assertEqual(result.values['attempts'],2)
            self.assertEqual(result.values['unfinished'],1);self.assertEqual(result.values['failed'],1)
            self.assertIsNone(result.values['prompt_tokens']['known_total'])

    def test_known_zero_and_unknown_are_distinct(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            (root/'trace.jsonl').write_text(json.dumps({'tool':'llm','event':'succeeded','call_id':'m1','tokens_in':0,'tokens_out':0}))
            result=ModelMetric().collect(CompletedSample('x','agent',0,root))
            self.assertEqual(result.status,'ok');self.assertEqual(result.values['prompt_tokens']['known_total'],0)

    def test_collector_exception_is_explicit_error(self):
        class Failing:
            name,version='custom',1
            def collect(self,sample):raise RuntimeError('do not expose secret')
        result=collect_metrics(CompletedSample('x','agent',0,Path('/tmp')),[Failing()])[0]
        self.assertEqual(result.status,'error');self.assertNotIn('secret',json.dumps(result.public_dict()))


if __name__=='__main__':unittest.main()
