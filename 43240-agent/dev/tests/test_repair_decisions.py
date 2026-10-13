"""Candidate selection and repair decisions."""
from __future__ import annotations
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from agent.core.candidate import CandidateFactory
from agent.core.budget import Budget
from agent.core.model import ModelCallError
from agent.core.state import CheckResult
from agent.core.task import TaskSpec
from agent.core.state import RunStateView
from agent.workflows.repair_loop import AttemptState, RepairLoop, classify_model_error
from agent.core.runner import RunOptions
from agent.services.vivado import ToolResult, classify_tool_failure
from support import FakeBackend, FakeToolchain, reply, run_repair, events


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

    def test_observed_vivado_source_diagnostics_and_environment_precedence(self):
        for text in (
            "ERROR: [VRFC 10-1280] procedural assignment to a non-register out is not permitted",
            "ERROR: [VRFC 10-9336] redeclaration of ANSI port 'q' is not allowed",
            "ERROR: [VRFC 10-9999] procedural assignment to a non-register q",
        ):
            with self.subTest(text=text):
                self.assertEqual(classify_tool_failure(text), 'code')
                self.assertEqual(classify_tool_failure(text + '\nNo space left on device'), 'environment')
        self.assertEqual(classify_tool_failure(
            "ERROR: [VRFC 10-8530] module ignored due to previous errors"), 'unknown')

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



if __name__ == '__main__':
    unittest.main()
