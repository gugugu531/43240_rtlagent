"""Submission protocol regression tests, including real file-based commands."""
import concurrent.futures
import importlib.util
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
AVAILABLE = all(importlib.util.find_spec(name) for name in ('fastapi', 'httpx'))
if AVAILABLE:
    from fastapi.testclient import TestClient
    from serve import serve_api as api

AUTH = {'Authorization': 'Bearer test-token'}


def finished(client, job_id, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get('/v1/jobs/' + job_id, headers=AUTH)
        if response.json()['status'] == 'done':
            return response.json()
        time.sleep(0.005)
    raise AssertionError('job did not finish')


@unittest.skipUnless(AVAILABLE, 'FastAPI and httpx required')
class ServeTests(unittest.TestCase):
    def setUp(self):
        self.token = patch.object(api, 'TOKEN', 'test-token')
        self.token.start()
        self.addCleanup(self.token.stop)

    def test_auth_validation_health_and_unknown_job(self):
        with patch.dict(os.environ, LLM_BACKEND='mock'), TestClient(api.app) as client:
            for method, url, kwargs in [('get', '/v1/health', {}),
                                       ('get', '/v1/jobs/missing', {}),
                                       ('post', '/v1/solve', {'json': {'task_id':'a', 'prompt':'x'}})]:
                self.assertEqual(getattr(client, method)(url, **kwargs).status_code, 401)
            self.assertEqual(client.get('/v1/jobs/missing', headers=AUTH).status_code, 404)
            for fields in ({'mode':'typo'}, {'deadline_s':0}, {'deadline_s':-1}):
                self.assertEqual(client.post('/v1/solve', headers=AUTH,
                    json=dict(task_id='a', prompt='x', **fields)).status_code, 422)
            for mode in ('agent', 'baseline'):
                self.assertEqual(api.SolveRequest(task_id='x', prompt='x', mode=mode).deadline_s, 900)
                self.assertEqual(client.post('/v1/solve', headers=AUTH,
                    json=dict(task_id='a', prompt='x', mode=mode, deadline_s=901)).status_code, 422)
            self.assertTrue(client.get('/v1/health', headers=AUTH).json()['ready'])
            with patch.object(api, 'TOKEN', ''):
                self.assertEqual(client.get('/v1/health', headers=AUTH).status_code, 500)
        response = Mock()
        response.json.return_value = {'data':[{'id':'actual-model'}]}
        with patch.dict(os.environ, LLM_BACKEND='openai', LLM_MODEL='actual-model',
                        MODEL_NAME='actual-model', LLM_BASE_URL='http://127.0.0.1:8000/v1'), \
             patch.object(api.requests, 'get', return_value=response), TestClient(api.app) as client:
            self.assertEqual(client.get('/v1/health', headers=AUTH).status_code, 200)
            response.json.return_value = {'data':[{'id':'other-model'}]}
            self.assertEqual(client.get('/v1/health', headers=AUTH).status_code, 503)

    def test_health_rejects_unshared_thinking_config_before_advertising_ready(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp)/'config.yaml'
            config.write_text('schema_version: 1\nservices:\n  model:\n    enable_thinking: false\n')
            with patch.dict(os.environ, LLM_BACKEND='mock', AGENT_CONFIG=str(config)), \
                 patch('baseline.load_generation', return_value={}), TestClient(api.app) as client:
                self.assertEqual(client.get('/v1/health', headers=AUTH).status_code, 503)
                with patch('baseline.load_generation', return_value={'chat_template_kwargs': {'enable_thinking': False}}):
                    self.assertEqual(client.get('/v1/health', headers=AUTH).status_code, 200)

    def test_immediate_response_concurrent_nonce_and_serial_queue(self):
        entered, release = threading.Event(), threading.Event()
        calls = []
        def solver(req, submitted, stopping):
            calls.append(req.task_id)
            entered.set()
            release.wait(3)
            return req.task_id, ''
        with patch.object(api, '_solve', side_effect=solver), TestClient(api.app) as client:
            body = dict(task_id='first', nonce='once', prompt='x')
            started = time.monotonic()
            first = client.post('/v1/solve', headers=AUTH, json=body)
            self.assertEqual(first.status_code, 202)
            self.assertLess(time.monotonic() - started, 0.5)
            self.assertEqual(set(first.json()), {'job_id','task_id','status'})
            self.assertTrue(entered.wait(1))
            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                    repeated = list(pool.map(lambda _: client.post('/v1/solve', headers=AUTH, json=body).json(), range(16)))
                self.assertEqual({row['job_id'] for row in repeated}, {first.json()['job_id']})
                second = client.post('/v1/solve', headers=AUTH, json=dict(task_id='second', prompt='x')).json()
                self.assertEqual(client.get('/v1/jobs/'+second['job_id'], headers=AUTH).json()['status'], 'queued')
                self.assertEqual(calls, ['first'])
            finally:
                release.set()
            self.assertEqual(finished(client, second['job_id'])['solution'], 'second')
            self.assertEqual(calls, ['first','second'])
            self.assertEqual(client.post('/v1/solve', headers=AUTH, json=body).json()['status'], 'done')

    def test_expired_queue_never_launches_and_worker_survives_errors(self):
        entered, release = threading.Event(), threading.Event()
        real_solve = api._solve
        def solver(req, submitted, stopping):
            if req.task_id == 'block':
                entered.set()
                release.wait(3)
                return '', ''
            if req.task_id == 'error':
                raise OSError('sensitive detail')
            return real_solve(req, submitted, stopping)
        with patch.object(api, '_solve', side_effect=solver), TestClient(api.app) as client:
            client.post('/v1/solve', headers=AUTH, json=dict(task_id='block', prompt='x'))
            self.assertTrue(entered.wait(1))
            expired = client.post('/v1/solve', headers=AUTH, json=dict(task_id='expired', prompt='x', deadline_s=1)).json()
            # Advance only this submitted timestamp; no timing-dependent sleep.
            with api.app.state.jobs.lock:
                api.app.state.jobs.jobs[expired['job_id']]['submitted'] -= 2
            with patch.object(api.ProcessExecutor, 'start') as launch:
                release.set()
                result = finished(client, expired['job_id'])
                launch.assert_not_called()
            self.assertEqual(result['solution'], '')
            self.assertIn('queue_deadline', result['trace'])
            error = client.post('/v1/solve', headers=AUTH, json=dict(task_id='error', prompt='x')).json()
            result = finished(client, error['job_id'])
            self.assertIn('OSError', result['trace'])
            self.assertNotIn('sensitive', result['trace'])
            self.assertTrue(api.app.state.jobs.thread.is_alive())

    def test_expired_queue_is_done_while_previous_job_is_still_running(self):
        entered, release = threading.Event(), threading.Event()
        calls = []
        def solver(req, *_):
            calls.append(req.task_id)
            entered.set()
            release.wait(3)
            return '', ''
        with patch.object(api, '_solve', side_effect=solver), TestClient(api.app) as client:
            first = client.post('/v1/solve', headers=AUTH, json=dict(task_id='block', prompt='x')).json()
            self.assertTrue(entered.wait(1))
            try:
                for mode in ('agent', 'baseline'):
                    body = dict(task_id=mode, mode=mode, nonce=mode, prompt='x', deadline_s=1)
                    expired = client.post('/v1/solve', headers=AUTH, json=body).json()
                    with api.app.state.jobs.lock:
                        api.app.state.jobs.jobs[expired['job_id']]['submitted'] -= 2
                    result = client.get('/v1/jobs/'+expired['job_id'], headers=AUTH).json()
                    self.assertEqual(result['status'], 'done')
                    self.assertEqual(result['solution'], '')
                    self.assertIn('queue_deadline', result['trace'])
                    self.assertEqual(client.post('/v1/solve', headers=AUTH, json=body).json()['status'], 'done')
                self.assertEqual(client.get('/v1/jobs/'+first['job_id'], headers=AUTH).json()['status'], 'running')
            finally:
                release.set()
            api.app.state.jobs.queue.join()
            self.assertEqual(calls, ['block'])


    def test_real_mock_command_and_repeated_requests(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(api, 'SCRATCH', temp), \
             patch.dict(os.environ, LLM_BACKEND='mock', AGENT_WORKFLOW='single_generate',
                        AGENT_RECORD_ROOT=str(Path(temp)/'records')), TestClient(api.app) as client:
            for i in range(3):
                req = dict(task_id=f't{i}', prompt=(ROOT.parent/'tasks/example/example_ex03_lfsr8/prompt.txt').read_text())
                job = client.post('/v1/solve', headers=AUTH, json=req).json()
                result = finished(client, job['job_id'])
                self.assertIn('module TopModule', result['solution'])
                self.assertTrue(any(json.loads(line)['tool']=='supervisor' for line in result['trace'].splitlines()))
            self.assertEqual(len(list((Path(temp)/'records').glob('*/task.json'))), 3)
            self.assertEqual(set(Path(temp).iterdir()), {Path(temp)/'records'})

    def test_baseline_timeout_reaps_descendants_preserves_answer_and_next_job(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pid_file = root/'child.pid'
            script = root/'run_baseline.sh'
            script.write_text('#!/bin/bash\n'
                'echo "module Saved; endmodule" > "$2/solution.v"\n'
                'echo "{}" > "$2/trace.jsonl"\n'
                f'sleep 60 &\necho $! > "{pid_file}"\nwait\n')
            script.chmod(0o755)
            with patch.object(api, 'ROOT', temp), patch.object(api, 'SCRATCH', temp), TestClient(api.app) as client:
                job = client.post('/v1/solve', headers=AUTH, json=dict(task_id='baseline', mode='baseline',
                                  prompt='x', deadline_s=1)).json()
                result = finished(client, job['job_id'])
                self.assertIn('module Saved', result['solution'])
                self.assertIn('timeout', result['trace'])
                self.assertLess(result['elapsed_s'], 1.5)
                self.assertFalse(Path('/proc', pid_file.read_text().strip()).exists())
                script.write_text('#!/bin/bash\necho next > "$2/solution.v"\n')
                job = client.post('/v1/solve', headers=AUTH, json=dict(task_id='next', mode='baseline', prompt='x')).json()
                self.assertEqual(finished(client, job['job_id'])['solution'], 'next\n')

    def test_hundreds_of_requests_keep_nonce_results_and_worker_alive(self):
        with patch.object(api, '_solve', side_effect=lambda req, *_: (req.task_id, '')), TestClient(api.app) as client:
            jobs = []
            for i in range(300):
                body = dict(task_id=f't{i}', nonce=f'n{i}', prompt='x')
                jobs.append((body, client.post('/v1/solve', headers=AUTH, json=body).json()['job_id']))
            for body, job_id in jobs:
                self.assertEqual(finished(client, job_id)['solution'], body['task_id'])
                self.assertEqual(client.post('/v1/solve', headers=AUTH, json=body).json()['job_id'], job_id)
            self.assertEqual(len(api.app.state.jobs.jobs), 300)
            self.assertTrue(api.app.state.jobs.thread.is_alive())

    def test_shutdown_cancels_active_command(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            script = root/'run_baseline.sh'
            pid_file = root/'pid'
            script.write_text(f'#!/bin/bash\necho $$ > "{pid_file}"\nsleep 60\n')
            script.chmod(0o755)
            with patch.object(api, 'ROOT', temp), patch.object(api, 'SCRATCH', temp):
                with TestClient(api.app) as client:
                    job = client.post('/v1/solve', headers=AUTH, json=dict(task_id='stop', mode='baseline', prompt='x')).json()
                    deadline = time.monotonic()+2
                    while not pid_file.exists() and time.monotonic()<deadline:
                        time.sleep(0.005)
                    self.assertTrue(pid_file.exists())
                    started = time.monotonic()
                self.assertLess(time.monotonic()-started, 1)
                self.assertFalse(Path('/proc', pid_file.read_text().strip()).exists())
                self.assertEqual(api.app.state.jobs.get(job['job_id'])['status'], 'done')
                self.assertFalse(api.app.state.jobs.thread.is_alive())


if __name__ == '__main__':
    unittest.main()
