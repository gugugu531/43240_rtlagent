"""Shared manifest thinking configuration and exact upstream baseline parity."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import baseline
from agent.core.model import ModelRequest, ModelCallError
from agent.recording.recorder import RunRecorder
from agent.services.model import MockBackend, ModelService
from dev.tools.submission import stage_submission
from test_baseline_equivalence import server


class GenerationTests(unittest.TestCase):
    def test_empty_manifest_rejects_all_unshared_thinking_options(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(baseline, 'load_generation', return_value={}):
            recorder = RunRecorder(Path(temp))
            self.addCleanup(recorder.close)
            with self.assertRaises(ModelCallError):
                ModelService(MockBackend(), recorder, template_options={'enable_thinking': False})
            service = ModelService(MockBackend(), recorder)
            for profile in ('default', 'baseline_rtl'):
                for options in ({'chat_template_kwargs': {'enable_thinking': False}},
                                {'chat_template_kwargs': {}}, {'reasoning_effort': 'high'}):
                    with self.subTest(profile=profile, options=options), self.assertRaises(ModelCallError):
                        service.chat(ModelRequest([], profile=profile, **options))
            self.assertEqual(service.requests, [])

    def test_manifest_options_are_used_by_both_profiles_and_counter(self):
        class Counter:
            def count(self, messages, *, template_options=None):
                from agent.core.tokens import TokenCount
                self.options = template_options
                return TokenCount(None, 'unavailable', 'test')
        declared = {'chat_template_kwargs':{'enable_thinking':False,'mode':'test','budget':123},
                    'reasoning_effort':'high'}
        for profile in ('default','baseline_rtl'):
            with tempfile.TemporaryDirectory() as temp, patch.object(baseline,'load_generation',return_value=declared):
                counter=Counter(); recorder=RunRecorder(Path(temp))
                service=ModelService(MockBackend(),recorder,token_counter=counter)
                service.chat(ModelRequest([{'role':'user','content':'Implement TopModule.'}],profile=profile))
                sent=service.requests[0]['request']
                self.assertEqual(sent['chat_template_kwargs'],declared['chat_template_kwargs'])
                self.assertEqual(sent['reasoning_effort'],'high')
                self.assertEqual(counter.options,declared['chat_template_kwargs'])
                recorder.close()

    def test_conflicting_settings_are_rejected_before_model_call(self):
        declared={'chat_template_kwargs':{'enable_thinking':False},'reasoning_effort':'high'}
        with tempfile.TemporaryDirectory() as temp, patch.object(baseline,'load_generation',return_value=declared):
            recorder=RunRecorder(Path(temp))
            with self.assertRaises(ModelCallError):
                ModelService(MockBackend(),recorder,template_options={'enable_thinking':True})
            service=ModelService(MockBackend(),recorder)
            for kwargs in ({'chat_template_kwargs':{'enable_thinking':True}}, {'reasoning_effort':'low'}):
                with self.assertRaises(ModelCallError): service.chat(ModelRequest([],**kwargs))
            self.assertEqual(service.requests,[])
            recorder.close()

    def test_matching_partial_settings_inherit_full_manifest_options(self):
        declared={'chat_template_kwargs':{'enable_thinking':False,'budget':128}}
        with tempfile.TemporaryDirectory() as temp, patch.object(baseline,'load_generation',return_value=declared):
            recorder=RunRecorder(Path(temp))
            try:
                service=ModelService(MockBackend(),recorder,template_options={'enable_thinking':False})
                service.chat(ModelRequest([],chat_template_kwargs={'enable_thinking':False}))
                self.assertEqual(service.requests[0]['request']['chat_template_kwargs'],declared['chat_template_kwargs'])
                self.assertEqual(service.template_options,declared['chat_template_kwargs'])
            finally:
                recorder.close()

    def test_declared_policy_rejects_undeclared_thinking_fields(self):
        cases=[({'reasoning_effort':'high'},{'chat_template_kwargs':{'enable_thinking':True}}),
               ({'chat_template_kwargs':{'enable_thinking':False}},{'reasoning_effort':'high'}),
               ({'chat_template_kwargs':{'enable_thinking':False}},
                {'chat_template_kwargs':{'enable_thinking':False,'budget':128}})]
        for declared, supplied in cases:
            with self.subTest(declared=declared,supplied=supplied), tempfile.TemporaryDirectory() as temp, \
                 patch.object(baseline,'load_generation',return_value=declared):
                recorder=RunRecorder(Path(temp))
                try:
                    service=ModelService(MockBackend(),recorder)
                    with self.assertRaises(ModelCallError): service.chat(ModelRequest([],**supplied))
                    self.assertEqual(service.requests,[])
                finally:
                    recorder.close()

    def test_reasoning_only_declaration_rejects_unshared_service_template_option(self):
        with tempfile.TemporaryDirectory() as temp, \
             patch.object(baseline,'load_generation',return_value={'reasoning_effort':'high'}):
            recorder=RunRecorder(Path(temp))
            try:
                with self.assertRaises(ModelCallError):
                    ModelService(MockBackend(),recorder,template_options={'enable_thinking':False})
            finally:
                recorder.close()

    def test_changed_manifest_rejects_replay_before_model_call(self):
        from test_entry_replay import EntryReplayTests
        from support import events
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); staged=root/'submission';stage_submission(ROOT,staged)
            helper=EntryReplayTests()
            task, tools, env=helper.prepare(root)
            with patch('test_entry_replay.ROOT',staged):
                initial=helper.invoke(root,task,env,'search_initial')/'initial.json'
                self.assertTrue(initial.is_file())
                control=helper.invoke(root,task,env,'search_r2',initial)
                self.assertTrue(any(e.get('event')=='initial_replayed' for e in events(control)))
                manifest=json.loads((staged/'manifest.json').read_text())
                manifest['generation']={'chat_template_kwargs':{'enable_thinking':False}}
                (staged/'manifest.json').write_text(json.dumps(manifest))
                rejected=helper.invoke(root,task,env,'search_r2',initial)
                rows=events(rejected)
                self.assertTrue(any(e.get('tool')=='agent' and e.get('event')=='error' and
                                    'initial runtime or model service differs' in e.get('excerpt','') for e in rows))
                self.assertFalse(any(e.get('event')=='initial_replayed' for e in rows))
                self.assertFalse(any(e.get('tool')=='llm' and e.get('event')=='started' for e in rows))

    def test_official_and_agent_requests_and_think_extraction_match_in_isolated_package(self):
        with tempfile.TemporaryDirectory() as temp, server() as http:
            root=Path(temp); staged=root/'submission'; stage_submission(ROOT,staged)
            task=root/'task';task.mkdir();(task/'prompt.txt').write_text('Implement TopModule.')
            http.body={'choices':[{'message':{'content':'<think>module Wrong; endmodule</think>\nmodule TopModule; endmodule'},'finish_reason':'stop'}]}
            env=dict(os.environ,LLM_BACKEND='openai',LLM_BASE_URL=http.url,LLM_MODEL='served-model',
                     MODEL_NAME='served-model',AGENT_WORKFLOW='single_generate',AGENT_RESERVE_S='1')
            for key in ('PYTHONPATH','AGENT_CONFIG','LLM_TIMEOUT_S','AGENT_RECORD_ROOT'):
                env.pop(key,None)
            for generation in ({}, {'chat_template_kwargs':{'enable_thinking':False,'other':2,'nested':{}},
                                    'reasoning_effort':'high','max_tokens':1,'temperature':1}):
                manifest=json.loads((staged/'manifest.json').read_text());manifest['generation']=generation
                (staged/'manifest.json').write_text(json.dumps(manifest))
                http.posts.clear()
                for script in ('run_baseline.sh','run.sh'):
                    out=root/('out-'+script)
                    result=subprocess.run([str(staged/script),str(task),str(out)],cwd=staged,env=env,
                                          capture_output=True,text=True,timeout=10)
                    self.assertEqual(result.returncode,0,result.stderr)
                    self.assertEqual((out/'solution.v').read_text(),'module TopModule; endmodule\n')
                self.assertEqual(len(http.posts),2)
                self.assertEqual(http.posts[0][1],http.posts[1][1])
                payload=http.posts[0][1]
                self.assertEqual(payload['max_tokens'],16384)
                self.assertEqual(payload['temperature'],0)
                if generation:
                    self.assertEqual(payload['chat_template_kwargs'],{'enable_thinking':False,'other':2})
                    self.assertEqual(payload['reasoning_effort'],'high')


if __name__=='__main__':unittest.main()
