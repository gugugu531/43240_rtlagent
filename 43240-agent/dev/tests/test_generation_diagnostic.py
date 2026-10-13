import unittest
from dev.tools.generation_diagnostic import classify_response, digest


def response(content, finish='stop', reasoning=None):
    return {'choices': [{'message': {'content': content, 'reasoning_content': reasoning},
                         'finish_reason': finish}], 'usage': {'completion_tokens': 8192}}


class DiagnosticTests(unittest.TestCase):
    def test_frozen_manifest_survives_json_tuple_to_list(self):
        import json
        original = {'tasks': ({'name': 'test'},), 'excluded': ()}
        self.assertEqual(digest(original), digest(json.loads(json.dumps(original))))

    def test_unfinished_thinking_is_not_a_final_candidate(self):
        r = classify_response(response('<think>draft module TopModule; endmodule', 'length'))
        self.assertEqual(r['category'], 'thinking_truncated')

    def test_separated_reasoning_without_answer(self):
        self.assertEqual(classify_response(response(None, 'length', 'still thinking'))['category'],
                         'thinking_truncated')

    def test_complete_answer_after_thinking(self):
        r = classify_response(response('<think>analysis</think>module TopModule; endmodule'))
        self.assertEqual(r['category'], 'complete_rtl')

    def test_length_does_not_always_mean_no_code(self):
        r = classify_response(response('module TopModule; endmodule', 'length'))
        self.assertEqual(r['category'], 'complete_rtl')

    def test_incomplete_rtl_is_not_thinking_truncation(self):
        self.assertEqual(classify_response(response('module TopModule;', 'length'))['category'], 'rtl_truncated')

    def test_wrong_module(self):
        self.assertEqual(classify_response(response('module Other; endmodule'))['category'], 'target_module_missing')
