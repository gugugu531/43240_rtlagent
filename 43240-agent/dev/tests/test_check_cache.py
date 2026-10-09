"""Per-task check cache identity and reuse."""
from __future__ import annotations
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from agent.core.candidate import CandidateFactory
from agent.core.budget import Budget
from agent.core.task import TaskSpec
from agent.services.tools import ToolService
from agent.services.vivado import ToolResult
from support import FakeToolchain

TASK = TaskSpec.from_text('stage3', 'Implement TopModule.')


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



if __name__ == '__main__':
    unittest.main()
