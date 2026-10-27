"""Conservative syntax recovery, schema limits and independence regressions."""
from copy import deepcopy
import hashlib
import json
import unittest
from types import SimpleNamespace

from agent.rtl.adaptive_analysis import choose_route
from agent.rtl.adaptive_check import (
    CheckerError, _recover_json_punctuation, approve_review, build_review_evidence,
    checker_request, parse_checker, parse_format_correction, recover_checker_format,
)
from agent.rtl.suite.evaluate import expected_traces
from agent.rtl.suite.testbench import compare_trace_rows
from agent.rtl.task import TaskSpec


def _honest_review(draft):
    """A minimal v2 review that copies the host evidence for this simple model."""
    evidence = build_review_evidence(draft)
    rows = evidence["expected_table"]
    steps = [{"step": row["step"], "outputs": row["expected"]} for row in rows[:2]]
    return {
        "review_contract_version": 2,
        "checker_hash": draft.checker_hash,
        "expected_table_sha256": evidence["expected_table_sha256"],
        "decision": "accept",
        "reason": "Both binary input values are compared to the same public input.",
        "checked_requirements": ["identity"],
        "requirement_reviews": [{
            "requirement_id": "identity", "verdict": "supported",
            "witness": {"case_id": rows[0]["case_id"], "steps": steps}}],
        "claims": evidence["required_claims"],
        "state_phase_claims": evidence["required_phase_claims"],
        "init_claims": [{"register": item["register"],
                         "source": item["allowed_sources"][0]}
                        for item in evidence["required_init_claims"]],
        "degenerate_outputs": evidence["required_degenerate_outputs"],
        "counterexamples": [],
    }


class CheckerRecovery(unittest.TestCase):
    def setUp(self):
        self.task = TaskSpec.from_text(
            "synthetic", "The output y equals the one-bit input a.",
            "module TopModule(input a, output y); endmodule")
        self.checker = {
            "schema_version": 1, "mode": "behavior",
            "ports": {"a": {"direction": "input", "width": 1},
                      "y": {"direction": "output", "width": 1}},
            "clock": None, "state": {}, "outputs": {"y": {"ref": "a"}},
            "requirements": [{"id": "identity", "quote": self.task.prompt}],
            "cases": [{"id": "both", "requirements": ["identity"], "exhaustive": True}],
        }
        self.text = json.dumps({"status": "ready", "checker": self.checker})

    def recover(self, text, finish_reason="stop"):
        draft = parse_checker(text, self.task, "model", finish_reason=finish_reason)
        return recover_checker_format(self.task, draft, text, finish_reason=finish_reason)

    def test_local_completion_still_requires_bound_review(self):
        broken = self.text[:-2]
        restored = self.recover(broken)
        original = parse_checker(self.text, self.task, "model", finish_reason="stop")
        self.assertEqual(restored.status, "ready", restored.reason)
        self.assertEqual(restored.payload, original.payload)
        self.assertEqual(restored.checker_hash, original.checker_hash)
        self.assertFalse(restored.public_dict()["repair_authorized"])
        binding = restored.preflight["format_correction"]
        self.assertEqual(binding["model_calls"], 0)
        self.assertEqual(binding["original_response_sha256"], hashlib.sha256(broken.encode()).hexdigest())
        self.assertEqual(binding["edits"], [
            {"offset": len(broken), "old": "", "new": "}"},
            {"offset": len(broken), "old": "", "new": "}"}])
        review = _honest_review(restored)
        frozen = approve_review(json.dumps(review), restored)
        self.assertEqual(frozen.status, "approved", frozen.violations)
        self.assertFalse(frozen.retryable)
        self.assertEqual(frozen.violations, [])
        self.assertEqual(frozen.review_record["status"], "approved")
        review["checker_hash"] = "wrong"
        rejected = approve_review(json.dumps(review), restored)
        self.assertEqual(rejected.status, "invalid")
        self.assertTrue(rejected.retryable)

    def test_complete_and_corrupted_checkers_keep_same_known_expectations(self):
        # This exercises the recovered model. It is a local model fixture, not RTL or Vivado evidence.
        valid = self.recover(self.text + "}")
        self.assertEqual(valid.status, "ready", valid.reason)
        traces = expected_traces(valid.payload)
        self.assertEqual([r["expected"]["y"] for r in traces], [0, 1])
        wrong = deepcopy(self.checker)
        wrong["outputs"]["y"] = {"const": 0, "width": 1}
        wrong_draft = self.recover(json.dumps({"status": "ready", "checker": wrong}) + "}")
        # Syntax recovery cannot detect semantics; differing predictions stay different for review.
        self.assertEqual(wrong_draft.status, "ready")
        self.assertNotEqual(wrong_draft.checker_hash, valid.checker_hash)
        self.assertEqual([r["expected"]["y"] for r in expected_traces(wrong_draft.payload)], [0, 0])

    def test_escaped_strings_and_delimiters_are_untouched(self):
        obj = {"text": 'quote " slash \\ braces }],:[ and snow 雪', "nested": [1, 2]}
        text = json.dumps(obj, ensure_ascii=False)
        repaired, edits = _recover_json_punctuation(text[:-1] + ",}")
        self.assertEqual(json.loads(repaired), obj)
        self.assertEqual(edits, [{"offset": len(text) - 1, "old": ",", "new": ""}])

    def test_recovered_checker_detects_wrong_and_unknown_observations(self):
        suite = self.recover(self.text[:-1]).payload
        correct = compare_trace_rows({(0, 0): {"y": (0, 1)}, (0, 1): {"y": (1, 1)}}, suite)
        self.assertEqual(correct["passed_cases"], ["both"])
        self.assertEqual(correct["compared_bits"], 2)
        wrong = compare_trace_rows({(0, 0): {"y": (0, 1)}, (0, 1): {"y": (0, 1)}}, suite)
        self.assertEqual(wrong["failed_cases"], ["both"])
        self.assertEqual(wrong["first_mismatch"]["expected_value"], 1)
        self.assertEqual(wrong["first_mismatch"]["actual_value"], 0)
        unknown = compare_trace_rows({(0, 0): {"y": (0, 0)}, (0, 1): {"y": (0, 0)}}, suite)
        self.assertEqual(unknown["unknown_cases"], ["both"])
        self.assertEqual(unknown["passed_cases"], [])
        self.assertEqual(unknown["compared_bits"], 0)
        self.assertEqual(unknown["unknown_actual"], 2)

    def test_refuses_ambiguous_or_semantically_invalid_changes(self):
        for text in ('{"a":}', '{"a":', '{"a" 1}', '{"a":1 "b":2}',
                     '{"a":[1}', '{"a":[1,', '{"a":1} {"b":2}',
                     '{"a":1,"a":2,}', '{"a":NaN}', '{"a":"unterminated',
                     '{"a":01}', '{"a":[truefalse]}', '{"a":[]}'+'}'*9):
            with self.subTest(text=text), self.assertRaises(ValueError):
                _recover_json_punctuation(text)
        for finish in ("length", None):
            self.assertEqual(self.recover(self.text[:-1], finish).status, "invalid")
        # A route member that does not echo the requested route is never normalized.
        altered = deepcopy(self.checker)
        altered["route"] = "properties"
        result = self.recover(json.dumps({"status": "ready", "checker": altered})[:-1])
        self.assertEqual(result.status, "invalid")
        self.assertIn("route", result.reason)
        self.assertFalse(result.preflight["format_correction_eligible"])

    def test_replay_cannot_reparent_same_scalars(self):
        broken = self.text[:-1]
        draft = parse_checker(broken, self.task, "model", finish_reason="stop")
        altered = self.text.replace('"clock": null, "state": {}', '"clock": {"state": null}')
        result = parse_format_correction(altered, self.task, draft, broken,
                                         original_finish_reason="stop", finish_reason="stop")
        self.assertEqual(result.status, "invalid")
        result = parse_format_correction(self.text, self.task, draft, broken,
                                         original_finish_reason="stop", finish_reason="stop")
        self.assertEqual(result.status, "ready")

    def test_public_width_route_boundary_and_independent_prompt(self):
        analysis = SimpleNamespace(kind="combinational", risks=[], ambiguities=[], clocks=[],
                                   requirements=["public"], route="model", model_cost="small")
        for width, route in ((256, "model"), (257, "structural"), (512, "structural")):
            task = TaskSpec.from_text("wide", "Copy all bits.",
                                     f"module TopModule(input [{width-1}:0] a, output [{width-1}:0] y); endmodule")
            self.assertEqual(choose_route(task, analysis).route, route)
        messages = checker_request(self.task, "model")
        self.assertNotIn("candidate", json.dumps(json.loads(messages[1]["content"])))
        self.assertIn("omit state.clock", messages[0]["content"])
        properties = checker_request(self.task, "properties")
        self.assertIn("route is NOT a field", properties[0]["content"])
        self.assertIn("never inside it", properties[0]["content"])


if __name__ == "__main__":
    unittest.main()
