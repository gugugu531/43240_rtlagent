"""Public interface and observed delivery failures must reach generation."""
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from burr.core import State

from agent.nodes.adaptive import _generation_messages, _delivery_failure, _candidate
from agent.prompts import TemplateRenderer
from agent.rtl.candidate import CandidateStore
from agent.rtl.extract import extract_result
from agent.rtl.task import TaskSpec


class DeliveryTests(unittest.TestCase):
    def context(self, prompt):
        self.artifacts = {}
        record = SimpleNamespace(
            write_json=lambda name, value: self.artifacts.update({name: value}),
            write_text=lambda *args: None,
            emit=lambda *args, **kwargs: None,
        )
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return SimpleNamespace(task=TaskSpec.from_text('public', prompt),
            prompts=TemplateRenderer(), store={'adaptive': {'analysis': None}},
            candidates=CandidateStore(record, temporary.name), record=record)

    def test_public_ports_and_top_reach_actual_template(self):
        ctx = self.context('Implement a module named TopModule.\n- input x\n- input y\n- output z')
        text = _generation_messages(ctx)[1]['content']
        self.assertIn('Required top module name: `TopModule`', text)
        self.assertIn('"name": "x"', text)
        self.assertIn('"source": "prompt_list"', text)
        self.assertIn('"complete": true', text)

    def test_buggy_embedded_code_is_not_an_authoritative_interface(self):
        ctx = self.context('Fix the bug:\n```verilog\nmodule wrong(input x, output [9:0] z); endmodule\n```')
        text = _generation_messages(ctx)[1]['content']
        self.assertIn('"complete": false', text)
        self.assertIn('"ports": []', text)
        self.assertNotIn('"source": "generated_code"', text)

    def test_rejected_top_records_failure_and_changes_rescue_request(self):
        ctx = self.context('Implement a module named TopModule.\n- input x\n- output z')
        reply = SimpleNamespace(call_id='m1', content='module top(input x, output z); assign z=x; endmodule', finish_reason='stop')
        first = _generation_messages(ctx)
        self.assertIsNone(_candidate(ctx, reply))
        failure = ctx.store['adaptive']['draft_failure']
        self.assertEqual(failure['extraction']['status'], 'target_missing')
        self.assertEqual(failure['extraction']['module_names'], ['top'])
        rescue = _generation_messages(ctx, failure=failure)
        self.assertNotEqual(first, rescue)
        self.assertIn('target_missing', rescue[1]['content'])
        self.assertEqual(self.artifacts['adaptive/draft-failure.json'], failure)

    def test_missing_body_is_not_inferred_to_be_length_truncation(self):
        for finish, kind in [('stop', 'no_final_content'), ('length', 'length_truncated')]:
            reply = SimpleNamespace(call_id='m2', content='', finish_reason=finish)
            failure = _delivery_failure(reply, extract_result('', 'TopModule'), 'TopModule')
            self.assertEqual(failure['kind'], kind)
            self.assertFalse(failure['final_content_present'])

    def test_complete_candidate_is_still_delivered(self):
        ctx = self.context('Implement a module named TopModule.\n- input x\n- output z')
        reply = SimpleNamespace(call_id='m3', content='module TopModule(input x, output z); assign z=x; endmodule', finish_reason='stop')
        candidate = _candidate(ctx, reply)
        self.assertEqual(ctx.candidates.selected_id, candidate.id)
        self.assertNotIn('draft_failure', ctx.store['adaptive'])

    def test_format_recovery_node_makes_no_model_request(self):
        from agent.nodes.adaptive import correct_checker_format
        from agent.rtl.adaptive_check import parse_checker
        ctx = self.context('Implement a module named TopModule.\n- input x\n- output z')
        text = '{"status":"unsupported","reason":"No grounded behavioral check"'
        data = ctx.store['adaptive']
        data.update(checker_revision_used=False,
                    checker_draft=parse_checker(text, ctx.task, 'model', finish_reason='stop'),
                    checker_syntax_reply=SimpleNamespace(content=text, finish_reason='stop', call_id='m4'))
        with patch('agent.nodes.adaptive._request', side_effect=AssertionError('model call')):
            state = correct_checker_format(ctx, State())
        self.assertEqual(state['checker_status'], 'unsupported')
        self.assertEqual(data['checker_format_correction']['model_calls'], 0)
        self.assertTrue(data['checker_revision_used'])
        with self.assertRaises(ValueError):
            correct_checker_format(ctx, State())


if __name__ == '__main__':
    unittest.main()
