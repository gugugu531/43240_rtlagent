"""Differential tests against the unchanged official baseline; no real model."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import baseline as official
from agent.core.config import ModelConfig
from agent.core.configuration import ConfigDocument, RunOverrides, load_config, resolve_config
from agent.core.model import ModelRequest, ModelCallError, ModelReply
from agent.core.registry import build_workflow
from agent.core.runner import Runner, RunOptions
from agent.core.task import TaskSpec
from agent.prompts.builder import assemble_messages
from support import FakeBackend, FakeToolchain, events, tool_result


def response(content='module TopModule; endmodule'):
    return {'choices': [{'message': {'content': content}, 'finish_reason': 'stop'}]}


@contextmanager
def server():
    class Handler(BaseHTTPRequestHandler):
        def send(self, status, body):
            raw = body.encode() if isinstance(body, str) else json.dumps(body).encode()
            self.send_response(status)
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            try:
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_GET(self):
            self.server.gets.append(self.path)
            self.send(self.server.models_status, self.server.models)

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            self.server.posts.append((self.path, body, dict(self.headers)))
            if self.server.delay:
                time.sleep(self.server.delay)
            self.send(self.server.status, self.server.body)

        def log_message(self, *args):
            pass

    http = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    http.posts, http.gets = [], []
    http.models_status, http.models = 200, {'data': [{'id': 'served-model'}]}
    http.status, http.body, http.delay = 200, response(), 0
    http.url = f'http://127.0.0.1:{http.server_port}/v1'
    thread = threading.Thread(target=http.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
    thread.start()
    try:
        yield http
    finally:
        http.shutdown()
        http.server_close()
        thread.join(2)


class BaselineDifferentialTests(unittest.TestCase):
    def task(self, root, prompt='  Implement TopModule.\n\n', interface=None):
        directory = root / 'task'
        directory.mkdir(exist_ok=True)
        (directory / 'prompt.txt').write_text(prompt)
        if interface is not None:
            (directory / 'interface.txt').write_text(interface)
        return directory

    def run_entry(self, root, http, mode, *, model_name=None, timeout=None):
        from agent.core.configuration import ENV_FIELDS
        env = {k: v for k, v in os.environ.items() if k not in (
            *ENV_FIELDS, 'MODEL_NAME', 'TRACK', 'AGENT_CONFIG', 'AGENT_CALLER_CWD',
            'AGENT_TASK_ID', 'RTL_TOP', 'PYTHONPATH', 'LLM_API_KEY')}
        env.update(LLM_BACKEND='openai', LLM_BASE_URL=http.url, LLM_MODEL='ignored-model',
                   LLM_API_KEY='not-sent-in-baseline-mode', PYTHONDONTWRITEBYTECODE='1',
                   RTL_TOP='IgnoredTop', AGENT_GIT_COMMIT='test', AGENT_GIT_DIRTY='false')
        if model_name is not None:
            env['MODEL_NAME'] = model_name
        out = root / mode
        script = 'run_baseline.sh' if mode == 'baseline' else 'run.sh'
        command = [str(ROOT / script), str(root / 'task'), str(out)]
        if timeout is not None:
            # Shorten the in-memory transport timeout only; never edit baseline.py.
            if mode == 'baseline':
                command = [sys.executable, '-B', '-c',
                           f'import baseline; baseline.TIMEOUT_S={timeout!r}; baseline.main()',
                           str(root / 'task'), str(out)]
            else:
                env['LLM_TIMEOUT_S'] = str(timeout)
        done = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(done.returncode, 0, done.stderr)
        return out

    def test_request_and_artifact_match_through_real_entry_points(self):
        cases = [('absent', None, None), ('empty', '', 'explicit-model'),
                 ('whitespace', ' \n\t', None),
                 ('custom_top', '\nmodule Other(input a, output b);\n', ' chosen-model ')]
        with server() as http:
            for label, interface, model_name in cases:
                with self.subTest(label=label), tempfile.TemporaryDirectory() as temp:
                    root = Path(temp)
                    self.task(root, interface=interface)
                    http.posts.clear()
                    base = self.run_entry(root, http, 'baseline', model_name=model_name)
                    agent = self.run_entry(root, http, 'agent', model_name=model_name)
                    self.assertEqual(len(http.posts), 2)
                    self.assertEqual(http.posts[0][0:2], http.posts[1][0:2])
                    for _, payload, headers in http.posts:
                        self.assertNotIn('Authorization', headers)
                        self.assertEqual(set(payload), {'model', 'messages', 'temperature', 'top_p', 'max_tokens'})
                    self.assertEqual((agent / 'solution.v').read_bytes(), (base / 'solution.v').read_bytes())
                    saved = json.loads(next((agent / 'records').glob('*/calls/m001/request.json')).read_text())
                    self.assertEqual(saved['request'], http.posts[1][1])
                    self.assertEqual(saved['timeout_s'], official.TIMEOUT_S)
                    trace = events(agent)
                    self.assertEqual(sum(e['tool'] == 'llm' and e['event'] == 'started' for e in trace), 1)
                    started = next(e for e in trace if e['tool'] == 'llm' and e['event'] == 'started')
                    self.assertEqual(started['service']['model'], http.posts[1][1]['model'])
                    self.assertFalse(any(e['tool'] in ('lint', 'synth', 'check_interface') for e in trace))
                    self.assertTrue(any(e['tool'] == 'model_selection' for e in trace))
                    self.assertTrue((agent / 'selection.json').is_file())
                    self.assertTrue(any(e['tool'] == 'supervisor' for e in trace))

    def test_model_discovery_and_fallback_match(self):
        with server() as http:
            cases = [(200, {'data': [{'id': 'first'}, {'id': 'second'}]}, 'first'),
                     (200, {'data': []}, 'default'), (503, {}, 'default'),
                     (200, 'invalid JSON', 'default'), (200, {'data': [{}]}, 'default')]
            for status, body, expected in cases:
                with self.subTest(body=body), tempfile.TemporaryDirectory() as temp:
                    root = Path(temp); self.task(root)
                    http.models_status, http.models = status, body
                    http.posts.clear()
                    for mode in ('baseline', 'agent'):
                        self.run_entry(root, http, mode)
                    self.assertEqual([p[1]['model'] for p in http.posts], [expected, expected])
                    self.assertEqual(http.posts[0][1], http.posts[1][1])

    def test_extraction_matches_official_for_every_fixture(self):
        fixtures = [
            'module TopModule; endmodule',
            'module helper; endmodule\nmodule TopModule; helper h(); endmodule',
            '```verilog\nmodule TopModule; endmodule\n```\n'
            '```verilog\nmodule TopModule; wire longer_draft; endmodule\n```',
            '```verilog\nmodule Other; endmodule\n```\n'
            '```verilog\nmodule TopModule; endmodule\n```',
            'module TopModule;', '```verilog\nmodule TopModule; endmodule',
            'module Other; endmodule', 'Only an explanation.', '', None,
            '// module TopModule; endmodule\nmodule TopModule; endmodule',
            '```cpp\nnot RTL\n```\nmodule TopModule; endmodule',
        ]
        with server() as http:
            for content in fixtures:
                with self.subTest(content=content), tempfile.TemporaryDirectory() as temp:
                    root = Path(temp); self.task(root)
                    http.body = response(content)
                    base = self.run_entry(root, http, 'baseline', model_name='fixed')
                    agent = self.run_entry(root, http, 'agent', model_name='fixed')
                    expected = official.extract(content or '', 'rtl').encode()
                    self.assertEqual((base / 'solution.v').read_bytes(), expected)
                    self.assertEqual((agent / 'solution.v').read_bytes(), expected)
                    checkpoint = json.loads((agent / 'selection.json').read_text())
                    self.assertEqual(checkpoint['code'].encode(), expected)
                    self.assertEqual(next((agent / 'records').glob('*/candidates/c001.v')).read_bytes(), expected)
                    self.assertTrue(any(e['tool'] == 'extract' for e in events(agent)))

    def test_failed_responses_and_timeouts_leave_empty_outputs_without_retry(self):
        cases = [(503, {'error': 'unavailable'}, 0, None), (200, 'invalid JSON', 0, None),
                 (200, {}, 0, None), (200, response(), .2, .04)]
        with server() as http:
            for status, body, delay, timeout in cases:
                with self.subTest(status=status, delay=delay), tempfile.TemporaryDirectory() as temp:
                    root = Path(temp); self.task(root)
                    http.status, http.body, http.delay = status, body, delay
                    http.posts.clear()
                    for mode in ('baseline', 'agent'):
                        out = self.run_entry(root, http, mode, model_name='fixed', timeout=timeout)
                        self.assertEqual((out / 'solution.v').read_bytes(), b'')
                    self.assertEqual(len(http.posts), 2)
                    failed = [e for e in events(root / 'agent') if e['tool'] == 'llm' and e['event'] == 'failed']
                    self.assertEqual(len(failed), 1)

    def test_connection_failure_matches(self):
        with server() as http:
            url = http.url
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); self.task(root)
            for mode in ('baseline', 'agent'):
                out = self.run_entry(root, SimpleNamespace(url=url), mode, model_name='fixed')
                self.assertEqual((out / 'solution.v').read_bytes(), b'')
            failed = [e for e in events(root / 'agent') if e['tool'] == 'llm' and e['event'] == 'failed']
            self.assertEqual([e['kind'] for e in failed], ['connection'])

    def test_repair_keeps_configured_model_auth_prompt_and_extractor(self):
        with server() as http, tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            directory = self.task(root, interface=' \nmodule Other(input a, output q);\n ')
            task = TaskSpec.from_directory(directory)
            http.body = response('module Other(input a, output q); assign q=a; endmodule')
            cfg = ModelConfig('openai', 'repair-model', http.url, 'repair-secret', 180,
                              baseline_model_name='must-not-affect-repair')
            tools = FakeToolchain([tool_result('lint', 'unavailable', 'not installed')])
            result = Runner(cfg, toolchain_factory=lambda: tools).run(
                task, lambda: build_workflow('repair_loop', max_rounds=1, use_skills=False),
                options=RunOptions(root / 'repair'))
            expected, _ = assemble_messages(task, style='repair', use_skills=False)
            self.assertEqual(http.gets, [])
            self.assertEqual(len(http.posts), 1)
            _, sent, headers = http.posts[0]
            self.assertEqual(sent, dict(model='repair-model', messages=expected,
                                       temperature=.2, max_tokens=4096, stream=False))
            self.assertEqual(headers.get('Authorization'), 'Bearer repair-secret')
            self.assertIn('module Other', result.selected_candidate.code)
            nodes = [e['component']['name'] for e in events(root / 'repair')
                     if e['tool'] == 'node' and e['event'] == 'started']
            self.assertEqual(nodes[:2], ['rtl_generate', 'rtl_extract'])


class BaselineContractTests(unittest.TestCase):
    def test_workflow_defaults_and_explicit_timeout_limits(self):
        for workflow, expected in [('single_generate', official.TIMEOUT_S), ('repair_loop', 180)]:
            cfg = resolve_config(load_config(), env={'AGENT_WORKFLOW': workflow})
            self.assertEqual(cfg.agent.services.model.timeout_s, expected)
            for value in (12, 400):
                cfg = resolve_config(load_config(), env={'AGENT_WORKFLOW': workflow,
                                                         'LLM_TIMEOUT_S': str(value)})
                self.assertEqual(cfg.agent.services.model.timeout_s, value)
        doc = ConfigDocument(None, {'schema_version': 1})
        self.assertEqual(resolve_config(doc, env={}).agent.services.model.timeout_s, official.TIMEOUT_S)
        cfg = resolve_config(doc, env={'LLM_TIMEOUT_S': '10'},
                             overrides=RunOverrides({'services.model.timeout_s': 20}))
        self.assertEqual(cfg.agent.services.model.timeout_s, 20)

    def test_fixed_workflow_rejects_sampling_overrides(self):
        for parameter in ('temperature', 'max_tokens', 'timeout_s'):
            with self.assertRaises(ValueError):
                build_workflow('single_generate', **{parameter: 1})

    def test_raw_input_does_not_change_repair_task_fields(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'prompt.txt').write_text(' \nTask\n ')
            (root / 'interface.txt').write_text(' \n ')
            task = TaskSpec.from_directory(root)
            self.assertEqual((task.prompt, task.interface), ('Task', ''))
            self.assertEqual((task.raw_prompt, task.raw_interface), (' \nTask\n ', ' \n '))

    def test_diagnostics_do_not_veto_baseline_output(self):
        for content, status in [('module TopModule;', 'incomplete'),
                                ('module Other; endmodule', 'target_missing'), ('', 'empty')]:
            with self.subTest(status=status), tempfile.TemporaryDirectory() as temp:
                backend = FakeBackend([ModelReply('x', content)])
                result = Runner(ModelConfig(), backend_factory=lambda _: backend).run(
                    TaskSpec.from_text('test', 'task'), lambda: build_workflow('single_generate'),
                    options=RunOptions(Path(temp)))
                self.assertEqual(result.status, 'completed')
                self.assertEqual(result.selected_candidate.code, official.extract(content, 'rtl'))
                self.assertEqual(result.selected_candidate.extraction_status, status)
                self.assertEqual(len(backend.requests), 1)

    def test_discovery_time_is_charged_to_task_budget(self):
        class SlowDiscovery(FakeBackend):
            def baseline_model(self, timeout_s):
                self.limit = timeout_s
                time.sleep(.06)
                return 'found', 'models'
        with tempfile.TemporaryDirectory() as temp:
            backend = SlowDiscovery([])
            result = Runner(ModelConfig(), backend_factory=lambda _: backend).run(
                TaskSpec.from_text('test', 'task'), lambda: build_workflow('single_generate'),
                options=RunOptions(Path(temp), deadline_s=.04, reserve_s=0))
            self.assertEqual(result.stop_reason, 'deadline')
            self.assertLessEqual(backend.limit, .04)
            self.assertEqual(backend.requests, [])

    def test_request_validation(self):
        for bad in (0, -1, 1.1, True, float('nan'), '1'):
            with self.assertRaises(ModelCallError):
                ModelRequest([], top_p=bad)

    def test_official_files_are_unchanged(self):
        for name in ('baseline.py', 'run_baseline.sh'):
            self.assertEqual((ROOT / name).read_bytes(), (ROOT.parent / 'example' / name).read_bytes())


if __name__ == '__main__':
    unittest.main()
