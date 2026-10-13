"""Check both-mode wire evidence association without a model or GPU."""
from pathlib import Path
import json
import tempfile
import unittest
from baseline import SYS
from dev.tools.generation_sweep import audits_for_run, session_settings, write_report, CONFIG, runner_environment
from unittest.mock import patch


class SweepEvidenceTests(unittest.TestCase):
    def test_runner_env_cannot_override_frozen_config(self):
        with patch.dict('os.environ', {'LLM_MODEL':'wrong', 'AGENT_DEADLINE_S':'999',
                                      'PATH':'tool-path', 'XILINX_VIVADO':'tool-root'}, clear=True):
            env = runner_environment('think-on-greedy', Path('/tmp/audit-test'))
        self.assertNotIn('LLM_MODEL',env)
        self.assertNotIn('AGENT_DEADLINE_S',env)
        self.assertEqual(env['PATH'],'tool-path')
        self.assertEqual(env['XILINX_VIVADO'],'tool-root')
        self.assertEqual(env['MODEL_GATEWAY_PROFILE'],'think-on-greedy')

    def test_legacy_five_session_keeps_default_profiles(self):
        path, profiles = session_settings({})
        self.assertEqual(path, CONFIG.resolve())
        self.assertEqual(profiles, ('think-on-greedy', 'think-off-greedy', 'think-on-sampled'))

    def test_selected_profiles_preserve_order(self):
        _, profiles = session_settings({'profile_order': ['think-on-sampled','think-on-greedy']})
        self.assertEqual(profiles, ('think-on-sampled','think-on-greedy'))

    def test_duplicate_or_unknown_profiles_rejected(self):
        for profiles in ([], ['unknown'], ['think-on-greedy']*2):
            with self.subTest(profiles=profiles), self.assertRaises(ValueError):
                session_settings({'profile_order': profiles})

    def test_prepared_eleven_report_records_44_solves(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = {'status': 'prepared', 'profile_order': ['think-on-greedy','think-on-sampled'],
                     'preflight': {'tasks': {'tasks': [{}]*11}}, 'arms': []}
            session = root/'session'
            with patch('dev.tools.generation_sweep.ROOT',root):
                write_report(session,state)
            report = (session/'README.md').read_text()
            self.assertIn('11 题',report)
            self.assertIn('0/44',report)
            self.assertNotIn('第一与第三组',report)

    def fixture(self, root):
        arm, run, task = root/'arm', root/'run', root/'Task'
        task.mkdir()
        (task/'prompt.txt').write_text('unchanged task prompt')
        run.mkdir()
        (run/'tasks.json').write_text(json.dumps({'tasks': [{'task_id': 'Task', 'directory': str(task)}]}))
        gateway = arm/'gateway'
        gateway.mkdir(parents=True)
        messages = [
            [{'role':'system','content':SYS['rtl']}, {'role':'user','content':'unchanged task prompt'}],
            [{'role':'user','content':'first agent request'}],
            [{'role':'user','content':'second agent request'}],
        ]
        for i, value in enumerate(messages):
            body = {'id': f'call-{i}', 'choices': [{'message': {'content': 'module TopModule; endmodule'},
                                                   'finish_reason': 'stop'}]}
            request = {'messages': value, 'max_tokens': 8192}
            (gateway/f'{i}.request.json').write_text(json.dumps({'original':request,'effective':request}))
            (gateway/f'{i}.response.json').write_text(json.dumps({'raw_text':json.dumps(body),
                                                                  'status':200,'attempts':1,'elapsed_s':.1}))
            if i:
                call = run/'samples/agent/Task/s0/records/test/calls'/f'm{i:03}'
                call.mkdir(parents=True)
                (call/'request.json').write_text(json.dumps(request))
                (call/'response.json').write_text(json.dumps(body))
        return arm, run

    def test_associates_baseline_and_all_agent_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            arm, run = self.fixture(Path(tmp))
            result = audits_for_run(arm, run)
            self.assertEqual([(r['mode'],r['call_index']) for r in result],
                             [('baseline',0),('agent',0),('agent',1)])
            self.assertTrue(all(r['category']=='complete_rtl' for r in result))

    def test_cannot_hide_changed_messages(self):
        with tempfile.TemporaryDirectory() as tmp:
            arm, run = self.fixture(Path(tmp))
            path = arm/'gateway/0.request.json'
            record = json.loads(path.read_text())
            record['effective']['messages'][1]['content'] = 'changed'
            path.write_text(json.dumps(record))
            with self.assertRaisesRegex(ValueError, 'changed messages'):
                audits_for_run(arm, run)

    def test_upstream_failure_stops_comparison(self):
        with tempfile.TemporaryDirectory() as tmp:
            arm, run = self.fixture(Path(tmp))
            path = arm/'gateway/0.response.json'
            record = json.loads(path.read_text())
            record['status'] = 503
            path.write_text(json.dumps(record))
            with self.assertRaisesRegex(ValueError, 'upstream failure'):
                audits_for_run(arm, run)
