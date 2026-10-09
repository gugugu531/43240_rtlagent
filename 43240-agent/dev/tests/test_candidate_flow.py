"""Repair workflow regressions use recorded model calls and fixed check results."""
from __future__ import annotations
import json
from pathlib import Path
import sys
import tempfile
import unittest

AGENT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(AGENT_ROOT))
from agent.core.model import ModelReply, ModelCallError


from support import FakeBackend, FakeToolchain, reply, tool_result, events, record_file, run_repair


class CandidateFlowTests(unittest.TestCase):
    def test_incomplete_extraction_is_explicitly_traced(self):
        backend = FakeBackend([ModelReply('unused', '```verilog\nmodule TopModule;\n```', finish_reason='length')])
        with tempfile.TemporaryDirectory() as temp:
            result = run_repair(temp, backend, FakeToolchain(), max_rounds=1)
            extracted = [e for e in events(temp) if e['tool']=='extract']
            self.assertIsNone(result.selected_candidate)
            self.assertEqual(extracted[0]['status'], 'incomplete')
            self.assertTrue(extracted[0]['suspected_truncation'])
            self.assertEqual(extracted[0]['call_id'], 'm001')
            self.assertEqual(len(backend.requests), 1)

    def test_second_model_failure_does_not_restore_confirmed_invalid_candidate(self):
        code = 'module TopModule; endmodule\n'
        backend = FakeBackend([reply(code), ModelCallError('request timed out', kind='timeout')])
        tools = FakeToolchain([tool_result('lint', 'failed', 'lint failed')])
        with tempfile.TemporaryDirectory() as temp:
            result = run_repair(temp, backend, tools)
            self.assertIsNone(result.selected_candidate)
            self.assertEqual(result.stop_reason, 'model_timeout')
            self.assertEqual(Path(temp, 'solution.v').read_text(), '')
            self.assertEqual(record_file(temp, 'candidates/c001.v').read_text(), code)
            self.assertEqual(len(backend.requests), 2)
            self.assertIn('lint failed', backend.requests[1].messages[-1]['content'])
            self.assertIn(code.strip(), backend.requests[1].messages[-1]['content'])

    def test_candidate_history_reconstructs_repairs_and_final_selection(self):
        first_code = 'module TopModule; endmodule\n'
        second_code = 'module TopModule; wire fixed; endmodule\n'
        backend = FakeBackend([reply(first_code), reply(second_code)])
        tools = FakeToolchain([tool_result('lint', 'failed', 'lint failed'), tool_result('lint', 'ok', 'lint ok')],
                              [tool_result('synth', 'ok', 'Synthesis finished')])
        with tempfile.TemporaryDirectory() as temp:
            result = run_repair(temp, backend, tools)
            created = {e['candidate_id']: e for e in events(temp)
                       if e['tool'] == 'candidate' and e['event'] == 'create'}
            first, second = created['c001'], created['c002']
            self.assertEqual(record_file(temp, 'candidates/c002.v').read_text(), second_code)
            selection = json.loads(Path(temp, 'selection.json').read_text())
            self.assertEqual(first['source_call_id'], 'm001')
            self.assertEqual(second['source_call_id'], 'm002')
            self.assertEqual(second['parent_id'], 'c001')
            self.assertEqual(second['source_stage'], 'repair')
            self.assertEqual(result.selected_candidate.id, 'c002')
            self.assertEqual(selection['reason'], 'synth_passed')
            self.assertEqual(Path(temp, 'solution.v').read_text(), second_code)
            checks = [e for e in events(temp) if e['tool'] in ('lint', 'synth')]
            self.assertEqual([(e['tool'], e['status']) for e in checks],
                             [('lint', 'failed'), ('lint', 'passed'), ('synth', 'passed')])
            self.assertEqual([e['candidate_id'] for e in checks], ['c001', 'c002', 'c002'])
            self.assertEqual(len({e['check_id'] for e in checks}), 3)
            self.assertTrue(all(e['execution_id'] for e in checks))


if __name__ == '__main__':
    unittest.main()
