"""Workflow decisions, cache and real process lifecycle acceptance tests."""
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
from agent.core.budget import Budget
from agent.core.model import ModelCallError
from agent.core.state import CheckResult
from agent.core.task import TaskSpec
from agent.core.state import RunStateView
from agent.workflows.repair_loop import AttemptState, RepairLoop, classify_model_error
from agent.services.processes import ProcessExecutor, ProcessRequest
from agent.services.tools import ToolService
from agent.core.supervision import RunSpec, Supervisor, recover_selection, record_supervision
from agent.core.runner import RunOptions
from agent.recording.recorder import RecordingConfig
from agent.recording.artifacts import ArtifactStore, atomic_write_json
from agent.services.vivado import ToolResult, classify_tool_failure
from test_candidate_flow import FakeBackend, FakeToolchain, reply, run_repair, events

TASK = TaskSpec.from_text('stage3', 'Implement TopModule.')


class RepairDecisionTests(unittest.TestCase):
    def setUp(self):
        factory = CandidateFactory()
        self.first = factory.create('module TopModule; endmodule\n', source_stage='generate', round=1)
        self.second = factory.create('module TopModule; wire x; endmodule\n', source_stage='repair', round=2)
        self.candidates = {c.id: c for c in (self.first, self.second)}
        self.workflow = RepairLoop(use_skills=False)

    def choose(self, checks, current_id):
        return self.workflow.choose(RunStateView(self.candidates, tuple(checks), (), current_id, None))

    def test_better_candidate_survives_timeout_unknown_and_defect(self):
        evidence = [CheckResult('k1', 'c001', 'lint', 'passed', 'ok')]
        for state, cause in [('timeout', 'unknown'), ('failed', 'unknown'), ('failed', 'code')]:
            checks = evidence + [CheckResult('k2', 'c002', 'lint', state, '', details={'failure_kind': cause})]
            self.assertEqual(self.choose(checks, 'c001').candidate_id, 'c001')

    def test_tie_keeps_earlier_and_invalid_is_excluded(self):
        self.assertEqual(self.choose([], 'c001').candidate_id, 'c001')
        checks = [CheckResult('k1', 'c001', 'interface', 'failed', 'wrong port', blocking=True)]
        self.assertEqual(self.choose(checks, 'c001').candidate_id, 'c002')
        checks.append(CheckResult('k2', 'c002', 'lint', 'failed', 'syntax', details={'failure_kind': 'code'}))
        self.assertIsNone(self.choose(checks, 'c002').candidate_id)

    def test_failure_routes_and_limits(self):
        workflow = RepairLoop(max_rounds=3, max_request_retries=1, max_model_calls=3, use_skills=False)
        budget = Budget(10, 0)
        retry = classify_model_error(ModelCallError('timeout', kind='timeout', retryable=True))
        self.assertEqual(workflow.decide(retry, 'm1', AttemptState(1), budget).action, 'retry_request')
        self.assertEqual(workflow.decide(retry, 'm1', AttemptState(2, 1), budget).action, 'stop')
        auth = classify_model_error(ModelCallError('auth', kind='http', retryable=False))
        self.assertEqual(workflow.decide(auth, 'm1', AttemptState(1), budget).action, 'stop')
        for status in ('timeout', 'unavailable', 'error', 'failed'):
            kind = CheckResult('k1', 'c001', 'lint', status, 'unknown').classify()
            self.assertEqual(workflow.decide(kind, 'k1', AttemptState(1), budget).action, 'stop')
        kind = CheckResult('k1', 'c001', 'lint', 'failed', 'syntax', details={'failure_kind': 'code'}).classify()
        self.assertEqual(workflow.decide(kind, 'k1', AttemptState(1), budget).action, 'repair')
        self.assertEqual(workflow.decide(kind, 'k1', AttemptState(3), budget).reason, 'model_call_limit')
        self.assertEqual(workflow.decide(kind, 'k1', AttemptState(1, 0, 2), budget).action, 'stop')

    def test_check_classification(self):
        cases = [(CheckResult('k1', 'c001', 'lint', 'passed', ''), 'passed'),
                 (CheckResult('k1', 'c001', 'interface', 'failed', '', blocking=True), 'code'),
                 (CheckResult('k1', 'c001', 'interface', 'failed', ''), 'unknown'),
                 (CheckResult('k1', 'c001', 'lint', 'timeout', ''), 'timeout'),
                 (CheckResult('k1', 'c001', 'lint', 'unavailable', ''), 'environment'),
                 (CheckResult('k1', 'c001', 'lint', 'failed', '', details={'failure_kind': 'environment'}), 'environment'),
                 (CheckResult('k1', 'c001', 'lint', 'failed', '', details={'failure_kind': 'code'}), 'code'),
                 (CheckResult('k1', 'c001', 'lint', 'skipped', ''), 'unknown')]
        for check, kind in cases:
            self.assertEqual(check.classify(), kind, check)

    def test_narrow_tool_attribution(self):
        self.assertEqual(classify_tool_failure('ERROR: [VRFC 10-1] syntax error near x'), 'code')
        self.assertEqual(classify_tool_failure('ERROR: [VRFC 10-1] syntax error; license expired'), 'environment')
        self.assertEqual(classify_tool_failure('exit 1'), 'unknown')
        self.assertEqual(classify_tool_failure('License checked out\nERROR: [VRFC 10-1] syntax error near x'), 'code')

    def test_retry_same_request_then_success(self):
        backend = FakeBackend([ModelCallError('transient', kind='timeout', retryable=True), reply(self.first.code)])
        tools = FakeToolchain([ToolResult('lint', (), -1, 'unavailable', 0, 'missing')])
        with tempfile.TemporaryDirectory() as temp:
            result = run_repair(temp, backend, tools)
            self.assertEqual(result.selected_candidate.id, 'c001')
            self.assertEqual(len(backend.requests), 2)
            self.assertEqual(backend.requests[0].messages, backend.requests[1].messages)
            self.assertEqual(result.stop_reason, 'verification_unavailable')
            self.assertEqual(len([e for e in events(temp) if e['tool'] == 'llm' and e['event'] == 'started']), 2)

    def test_unknown_check_keeps_fallback_without_repair(self):
        backend = FakeBackend([reply(self.first.code)])
        tools = FakeToolchain([ToolResult('lint', (), 1, 'failed', 0, 'unknown')])
        with tempfile.TemporaryDirectory() as temp:
            result = run_repair(temp, backend, tools)
            self.assertEqual(result.selected_candidate.id, 'c001')
            self.assertEqual(result.stop_reason, 'unknown')
            self.assertEqual(len(backend.requests), 1)


class CacheTests(unittest.TestCase):
    def test_identical_source_reuses_evidence_not_candidate_identity(self):
        factory = CandidateFactory()
        a = factory.create('module TopModule; endmodule', source_stage='generate', round=1)
        b = factory.create(a.code, source_stage='repair', round=2, parent_id=a.id)
        checks = []
        tools = FakeToolchain([ToolResult('lint', (), 0, 'ok', 0.1, 'ok')])
        tools.fingerprint = 'test-tool-v1'
        counter = iter(['k1', 'k2', 'k3'])
        service = ToolService(Budget(10, 0), lambda: next(counter), checks.append,
                              task=TASK, toolchain_factory=lambda: tools)
        original, reused = service.lint(a, TASK.top), service.lint(b, TASK.top)
        self.assertEqual(reused.candidate_id, b.id)
        self.assertEqual(reused.details['reused_from_check_id'], original.id)
        self.assertFalse(reused.details['executed'])
        tools.fingerprint = 'test-tool-v2'
        tools.lint_results = iter([ToolResult('lint', (), 0, 'ok', 0.1, 'changed')])
        self.assertTrue(service.lint(b, TASK.top).details['executed'])

    def test_unknown_identity_and_timeouts_are_not_reused(self):
        factory = CandidateFactory()
        a = factory.create('module TopModule; endmodule', source_stage='generate', round=1)
        for fingerprint, status in [(None, 'ok'), ('known', 'timeout'), ('known', 'failed')]:
            tools = FakeToolchain([ToolResult('lint', (), 1, status, 0, 'unknown')] * 2)
            tools.fingerprint = fingerprint
            counter = iter(['k1', 'k2'])
            service = ToolService(Budget(10, 0), lambda: next(counter), lambda r: None,
                                  task=TASK, toolchain_factory=lambda: tools)
            self.assertTrue(service.lint(a, TASK.top).details['executed'])
            self.assertTrue(service.lint(a, TASK.top).details['executed'])


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


class RepairTargetTests(unittest.TestCase):
    def test_repair_target_can_change_without_overwriting_stronger_answer(self):
        from agent.core.config import ModelConfig
        from agent.core.runner import Runner
        from agent.workflows.repair_loop import FailureDecision
        class ExploreUnknown(RepairLoop):
            def decide(self, kind, source_id, attempts, budget):
                if attempts.repairs == 0 and kind == 'unknown':
                    return FailureDecision('repair', 'explicit_experiment', source_id)
                return super().decide(kind, source_id, attempts, budget)
        first = 'module TopModule(input a, output q); assign q=a; endmodule\n'
        second = 'module TopModule(input b, output q); assign q=b; endmodule\n'
        backend = FakeBackend([reply(first), reply(second), ModelCallError('stop', kind='timeout')])
        tools = FakeToolchain([ToolResult('lint', (), 0, 'ok', 0, 'ok')],
                              [ToolResult('synth', (), 1, 'failed', 0, 'unknown')])
        task = TaskSpec.from_text('target', 'Implement TopModule.', 'module TopModule(input a, output q); endmodule')
        with tempfile.TemporaryDirectory() as temp:
            result = Runner(ModelConfig(), backend_factory=lambda cfg: backend, toolchain_factory=lambda: tools).run(
                task, lambda: ExploreUnknown(use_skills=False),
                options=RunOptions(Path(temp)))
            self.assertEqual(result.selected_candidate.id, 'c001')
            self.assertEqual(Path(temp, 'solution.v').read_text(), first)
            self.assertEqual(len(backend.requests), 3)
            self.assertIn(second.strip(), backend.requests[2].messages[-1]['content'])
            targets = [e['candidate_id'] for e in events(temp) if e.get('event') == 'repair_target']
            self.assertEqual(targets, ['c001', 'c002'])




class EvidenceStatisticsTests(unittest.TestCase):
    def test_reuse_and_started_checks_are_counted_once(self):
        sys.path.insert(0, str(ROOT / 'dev/tools/analysis'))
        try:
            from analyze import trace_stats
            evidence = [dict(tool='workflow', event='check_started', check_id='k1', kind='lint'),
                        dict(tool='lint', event='result', check_id='k1', kind='lint', details={'executed': True}),
                        dict(tool='lint', event='result', check_id='k2', kind='lint', details={'executed': False}),
                        dict(tool='workflow', event='check_started', check_id='k3', kind='synth')]
            stats = trace_stats(evidence)
            self.assertEqual(stats['tool_calls'], {'lint': 1, 'synth': 1})
            self.assertEqual(stats['reused_checks'], 1)
        finally:
            sys.path.remove(str(ROOT / 'dev/tools/analysis'))

    def test_partial_trace_is_preserved_without_fake_call_completion(self):
        with tempfile.TemporaryDirectory() as temp:
            Path(temp, 'trace.jsonl').write_bytes(b'{"tool":"llm","event":"started","call_id":"m001","seq":1}\n{"broken":')
            record_supervision(temp, {'stop_reason': 'deadline'}, 'r1')
            evidence = events(temp)
            self.assertEqual([e['tool'] for e in evidence], ['llm', 'supervisor'])
            self.assertEqual(evidence[-1]['seq'], 2)
            self.assertEqual(Path(temp, 'trace_partial.txt').read_text(), '{"broken":')

    def test_exhausted_supervisor_budget_creates_failure_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            result = Supervisor().run(RunSpec(TASK, 'single_generate',
                RunOptions(Path(temp), deadline_s=.1, reserve_s=.2)))
            self.assertEqual(result.stop_reason, 'deadline')
            self.assertTrue(result.run_id)
            self.assertEqual(Path(temp, 'solution.v').read_text(), '')
            trace = events(temp)
            self.assertEqual(trace[-1]['status'], 'interrupted')
            self.assertFalse(any(e['tool'] == 'llm' for e in trace))




class FullToolLogsTests(unittest.TestCase):
    def test_full_log_survives_work_cleanup_and_is_redacted(self):
        from agent.services.vivado import RtlToolchain
        with tempfile.TemporaryDirectory() as temp:
            tool = Path(temp, 'fake_tool')
            tool.write_text('#!' + sys.executable + '\nimport os\nprint("details " * 800)\nprint(os.environ["LLM_API_KEY"])\n')
            tool.chmod(0o755)
            tools = RtlToolchain(executor=ProcessExecutor(), log_dir=Path(temp, 'logs'))
            tools.xvlog = tools.xelab = tools.vivado = str(tool)
            tools.reason = ''
            with patch.dict(os.environ, AGENT_TMP=temp, AGENT_KEEP_WORK='0', LLM_API_KEY='tool-secret-xyz'):
                result = tools.lint('module TopModule; endmodule', 'TopModule', timeout_s=2)
            self.assertEqual(result.status, 'ok')
            self.assertIsNone(result.work_dir)
            self.assertFalse(list(Path(temp).glob('agent_lint_*')))
            log = Path(result.log_paths[0]).read_text()
            self.assertGreater(len(log), len(result.summary))
            self.assertNotIn('tool-secret-xyz', log)
            self.assertIn('[redacted]', log)


if __name__ == '__main__': unittest.main()
