"""Acceptance tests for the minimal evidence-gated workflow."""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from agent.core.config import ModelConfig
from agent.core.model import ModelCallError
from agent.core.registry import build_workflow
from agent.core.runner import Runner, RunOptions
from agent.core.task import TaskSpec
from agent.services.vivado import ToolResult
from support import FakeBackend, FakeToolchain, events, reply


TASK = TaskSpec.from_text('test', 'Implement a module named TopModule.')
FIRST = 'module TopModule; wire broken; endmodule\n'
SECOND = 'module TopModule; endmodule\n'


def run_evidence(temp, backend, tools):
    return Runner(ModelConfig(), backend_factory=lambda config: backend,
                  toolchain_factory=lambda: tools).run(
        TASK, lambda: build_workflow('evidence_repair'),
        options=RunOptions(Path(temp)))


class EvidenceRepairTests(unittest.TestCase):
    def test_sampling_preserves_explicit_experiment_budgets(self):
        import baseline
        workflow = build_workflow('evidence_repair')
        self.assertEqual(workflow.generate.max_tokens, 8192)
        self.assertEqual(workflow.generate.temperature, baseline.TEMPERATURE)
        self.assertEqual(workflow.generate.top_p, baseline.TOP_P)
        self.assertEqual(workflow.generate.timeout_s, 300)

    def test_failed_repair_retains_complete_parent_and_failed_evidence(self):
        for second in (reply('not rtl'),
                       ModelCallError('timeout', kind='timeout', retryable=False)):
            with self.subTest(second=type(second).__name__), tempfile.TemporaryDirectory() as temp:
                backend = FakeBackend([reply(FIRST), second])
                tools = FakeToolchain(lint_results=(ToolResult(
                    'lint', (), 1, 'failed', 0.01,
                    'ERROR: [VRFC 10-1280] procedural assignment to a non-register',
                    failure_kind='code'),))
                result = run_evidence(temp, backend, tools)
                self.assertEqual(result.selected_candidate.id, 'c001')
                self.assertEqual(Path(temp, 'solution.v').read_text(), FIRST)
                self.assertTrue(any(event.get('reason') == 'failed_check_fallback'
                                    for event in events(temp)))
                self.assertTrue(any(event.get('tool') == 'lint' and event.get('status') == 'failed'
                                    for event in events(temp)))
                self.assertEqual(len(backend.requests), 2)

    def test_two_failed_candidates_keep_earlier_parent(self):
        backend = FakeBackend([reply(FIRST), reply(SECOND)])
        tools = FakeToolchain(lint_results=tuple(
            ToolResult('lint', (), 1, 'failed', 0.01, 'syntax error', failure_kind='code')
            for _ in range(2)))
        with tempfile.TemporaryDirectory() as temp:
            result = run_evidence(temp, backend, tools)
            self.assertEqual(result.selected_candidate.id, 'c001')
            self.assertEqual(Path(temp, 'solution.v').read_text(), FIRST)

    def test_code_failure_gets_structured_feedback_and_one_repair(self):
        backend = FakeBackend([reply(FIRST), reply(SECOND)])
        tools = FakeToolchain(
            lint_results=(
                ToolResult('lint', (), 1, 'failed', 0.01,
                           'ERROR: [VRFC 10-4982] syntax error near broken',
                           failure_kind='code'),
                ToolResult('lint', (), 0, 'ok', 0.01, 'lint passed'),
            ),
            synth_results=(ToolResult('synth', (), 0, 'ok', 0.01,
                                      'Synthesis finished'),),
        )
        with tempfile.TemporaryDirectory() as temp:
            result = run_evidence(temp, backend, tools)
            self.assertEqual(result.stop_reason, 'synth_passed')
            self.assertEqual(result.selected_candidate.id, 'c002')
            self.assertEqual(Path(temp, 'solution.v').read_text(), SECOND)
            self.assertEqual(len(backend.requests), 2)
            repair_prompt = backend.requests[1].messages[-1]['content']
            self.assertIn('结构化诊断', repair_prompt)
            self.assertIn('VRFC 10-4982', repair_prompt)
            self.assertIn('不要猜测隐藏 testbench', repair_prompt)
            nodes = [event['component']['name'] for event in events(temp)
                     if event['tool'] == 'node' and event['event'] == 'started']
            self.assertIn('structured_feedback', nodes)

    def test_environment_failure_keeps_fallback_without_repair(self):
        backend = FakeBackend([reply(FIRST)])
        tools = FakeToolchain(lint_results=(
            ToolResult('lint', (), -1, 'unavailable', 0.01, 'vivado unavailable'),
        ))
        with tempfile.TemporaryDirectory() as temp:
            result = run_evidence(temp, backend, tools)
            self.assertEqual(result.stop_reason, 'verification_unavailable')
            self.assertEqual(result.selected_candidate.id, 'c001')
            self.assertEqual(len(backend.requests), 1)
            self.assertFalse(any(event.get('component', {}).get('name') == 'structured_feedback'
                                 for event in events(temp)))

    def test_second_code_failure_stops_after_exactly_one_repair(self):
        backend = FakeBackend([reply(FIRST), reply(SECOND)])
        def failure(message):
            return ToolResult('lint', (), 1, 'failed', 0.01, message,
                              failure_kind='code')
        tools = FakeToolchain(lint_results=(failure('first syntax error'),
                                             failure('second syntax error')))
        with tempfile.TemporaryDirectory() as temp:
            result = run_evidence(temp, backend, tools)
            self.assertEqual(result.stop_reason, 'code')
            self.assertEqual(len(backend.requests), 2)

    def test_extraction_failure_uses_the_same_bounded_feedback_path(self):
        backend = FakeBackend([reply('not rtl'), reply(SECOND)])
        tools = FakeToolchain(
            lint_results=(ToolResult('lint', (), 0, 'ok', 0.01, 'lint passed'),),
            synth_results=(ToolResult('synth', (), 0, 'ok', 0.01,
                                      'Synthesis finished'),),
        )
        with tempfile.TemporaryDirectory() as temp:
            result = run_evidence(temp, backend, tools)
            self.assertEqual(result.stop_reason, 'synth_passed')
            self.assertEqual(len(backend.requests), 2)
            self.assertIn('- 阶段：extraction', backend.requests[1].messages[-1]['content'])


if __name__ == '__main__':
    unittest.main()
