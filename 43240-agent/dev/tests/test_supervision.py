"""Worker supervision and transport cancellation."""
from __future__ import annotations
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from agent.core.candidate import CandidateFactory
from agent.core.task import TaskSpec
from agent.services.processes import ProcessExecutor, ProcessRequest
from agent.core.supervision import RunSpec, Supervisor, recover_selection
from agent.core.runner import RunOptions
from agent.recording.recorder import RecordingConfig
from agent.recording.artifacts import ArtifactStore, atomic_write_json
from support import events


class SupervisionTests(unittest.TestCase):
    def extension(self, directory, body):
        name = 'stage3_extension_' + str(time.time_ns())
        Path(directory, name + '.py').write_text('''
from agent.core.registry import WORKFLOW_REGISTRY, build_node
from agent.core.components import Component
from agent.nodes.generate import GenerateInput
from agent.nodes.extract import ExtractInput
from agent.services.processes import ProcessRequest
import os, sys, time
@WORKFLOW_REGISTRY.register('stage3_test')
class Flow(Component):
    def run(self, ctx):
''' + body)
        return name

    def run_spec(self, directory, module, deadline=1.2):
        task = TaskSpec.from_text('supervision-test', 'I would like you to implement a module named TopModule with the following interface.\n - input a\n - output q\n')
        return RunSpec(task, 'stage3_test', RunOptions(Path(directory)/'out', deadline, 0.3,
                       RecordingConfig(root=Path(directory)/'records')), import_modules=(module,))

    def test_blocking_workflow_is_stopped_and_selected_answer_survives(self):
        with tempfile.TemporaryDirectory() as temp:
            module = self.extension(temp, '''        reply = ctx.execute(build_node('rtl_generate'), GenerateInput(ctx.task))
        extracted = ctx.execute(build_node('rtl_extract'), ExtractInput(reply))
        ctx.select_candidate(extracted.candidate.id, reason='before_block')
        while True: time.sleep(1)
''')
            sys.path.insert(0, temp)
            try:
                with patch.dict(os.environ, LLM_BACKEND='mock'):
                    started = time.monotonic()
                    result = Supervisor().run(self.run_spec(temp, module))
                self.assertLess(time.monotonic() - started, 1.5)
                self.assertEqual(result.stop_reason, 'deadline')
                self.assertIsNotNone(result.selected_candidate)
                self.assertIn('module TopModule', Path(temp, 'out/solution.v').read_text())
                trace = events(Path(temp, 'out'))
                self.assertTrue(any(e['tool'] == 'llm' and e['event'] == 'succeeded' for e in trace))
                self.assertEqual(trace[-1]['status'], 'interrupted')
                self.assertEqual(trace[-1]['unreaped_pids'], [])
            finally:
                sys.path.remove(temp)

    def test_supervisor_recovers_ignored_term_tool_and_descendant(self):
        with tempfile.TemporaryDirectory() as temp:
            pidfile = Path(temp, 'pids')
            childcode = ('import os,signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); '
                         f'open({str(pidfile)!r},"a").write(str(os.getpid())+"\\n"); '
                         'time.sleep(60)')
            parentcode = ('import subprocess,sys,os,signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); '
                          f'open({str(pidfile)!r},"a").write(str(os.getpid())+"\\n"); '
                          f'subprocess.Popen([sys.executable,"-c",{childcode!r}]); time.sleep(60)')
            module = self.extension(temp, f'''        ctx.processes.run(ProcessRequest((sys.executable, '-c', {parentcode!r}), {temp!r}, 60))
        return ctx.finish(reason='unexpected')
''')
            sys.path.insert(0, temp)
            try:
                with patch.dict(os.environ, LLM_BACKEND='mock'):
                    result = Supervisor().run(self.run_spec(temp, module))
                self.assertEqual(result.stop_reason, 'deadline')
                pids = [int(p) for p in pidfile.read_text().splitlines()]
                self.assertEqual(len(pids), 2)
                for pid in pids:
                    with self.assertRaises(ProcessLookupError): os.kill(pid, 0)
                trace = events(Path(temp, 'out'))
                self.assertEqual(trace[-1]['unreaped_pids'], [])
                self.assertTrue(any(e['tool'] == 'process' and e['event'] == 'started' for e in trace))
                self.assertFalse(any(e['tool'] == 'process' and e['event'] == 'result' for e in trace))
                self.assertTrue(list(Path(temp, 'records').glob('*/process_logs/*.log')))
            finally:
                sys.path.remove(temp)

    def test_checkpoint_committed_before_solution_is_restored(self):
        with tempfile.TemporaryDirectory() as temp:
            store = ArtifactStore(temp)
            candidate = CandidateFactory().create('module TopModule; endmodule\n', source_stage='generate', round=1)
            store.select(candidate, reason='test')
            Path(temp, 'solution.v').write_text('interrupted old answer')
            restored, state = recover_selection(temp)
            self.assertEqual(restored.id, candidate.id)
            self.assertEqual(state, 'restored')
            self.assertEqual(Path(temp, 'solution.v').read_text(), candidate.code)
            saved = json.loads(Path(temp, 'selection.json').read_text())
            saved['code'] += 'tampered'
            atomic_write_json(Path(temp, 'selection.json'), saved)
            self.assertIsNone(recover_selection(temp)[0])
            self.assertEqual(Path(temp, 'solution.v').read_text(), '')

    def test_direct_command_timeout_kills_term_ignoring_child(self):
        with tempfile.TemporaryDirectory() as temp:
            executor = ProcessExecutor()
            started = time.monotonic()
            result = executor.run(ProcessRequest((sys.executable, '-c',
                'import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(60)'), temp, .35))
            self.assertEqual(result.status, 'timeout')
            self.assertLess(time.monotonic() - started, .6)


class TransportCancellationTests(unittest.TestCase):
    def server(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from threading import Event, Thread
        arrived, release = Event(), Event()
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers.get('Content-Length', 0)))
                arrived.set()
                release.wait(8)
                # Do not fabricate a completion after the client is cancelled.
            def log_message(self, *args): pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        server.daemon_threads = True
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.addCleanup(release.set)
        return server.server_address[1], arrived

    def test_shell_sigterm_exits_and_model_call_remains_unfinished(self):
        port, arrived = self.server()
        with tempfile.TemporaryDirectory() as temp:
            task, out = Path(temp, 'task'), Path(temp, 'out')
            task.mkdir()
            (task / 'prompt.txt').write_text('Implement TopModule.')
            env = dict(os.environ, LLM_BACKEND='openai', LLM_BASE_URL=f'http://127.0.0.1:{port}/v1',
                       AGENT_RECORD_ROOT=str(Path(temp, 'records')), AGENT_DEADLINE_S='30', AGENT_RESERVE_S='2')
            proc = subprocess.Popen([str(ROOT / 'run.sh'), str(task), str(out)], env=env,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                self.assertTrue(arrived.wait(5))
                started = time.monotonic()
                proc.send_signal(signal.SIGTERM)
                proc.wait(timeout=3)
                self.assertLess(time.monotonic() - started, 3)
                self.assertEqual(proc.returncode, 0)
                evidence = events(out)
                self.assertEqual(len([e for e in evidence if e['tool'] == 'llm' and e['event'] == 'started']), 1)
                self.assertFalse(any(e['tool'] == 'llm' and e['event'] in ('succeeded', 'failed') for e in evidence))
                supervision = evidence[-1]
                self.assertEqual(supervision['stop_reason'], 'sigterm')
                self.assertEqual(supervision['backend_inference_cancelled'], 'unknown')
                self.assertEqual(supervision['unreaped_pids'], [])
                self.assertEqual(supervision['status'], 'interrupted')
            finally:
                if proc.poll() is None:
                    proc.terminate()
                    proc.wait(timeout=3)

    @unittest.skipUnless(importlib.util.find_spec('fastapi'), 'fastapi is not installed')
    def test_http_small_deadline_bounds_blocking_model_without_five_second_floor(self):
        from serve import serve_api
        port, arrived = self.server()
        with tempfile.TemporaryDirectory() as temp:
            with patch.dict(os.environ, LLM_BACKEND='openai', LLM_BASE_URL=f'http://127.0.0.1:{port}/v1',
                            AGENT_RESERVE_S='0.05', AGENT_RECORD_ROOT=str(Path(temp, 'records'))), \
                 patch.object(serve_api, 'TOKEN', 'test-token'), patch.object(serve_api, 'SCRATCH', temp):
                started = time.monotonic()
                result = serve_api.solve(serve_api.SolveRequest(task_id='blocked', prompt='Implement TopModule.',
                                          deadline_s=1), authorization='Bearer test-token')
                self.assertLess(time.monotonic() - started, 1.3)
                self.assertTrue(arrived.is_set())
                trace = [json.loads(line) for line in result['trace'].splitlines()]
                self.assertTrue(any(e['tool'] == 'supervisor' for e in trace))
                self.assertFalse(any(e['tool'] == 'llm' and e['event'] == 'succeeded' for e in trace))
                self.assertEqual(set(result), {'task_id', 'solution', 'trace', 'elapsed_s'})



if __name__ == '__main__':
    unittest.main()
