"""Interrupted evidence statistics and complete tool logs."""
from __future__ import annotations
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from agent.core.task import TaskSpec
from agent.services.processes import ProcessExecutor
from agent.core.supervision import RunSpec, Supervisor, record_supervision
from agent.core.runner import RunOptions
from support import events

TASK = TaskSpec.from_text('stage3', 'Implement TopModule.')


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



if __name__ == '__main__':
    unittest.main()
