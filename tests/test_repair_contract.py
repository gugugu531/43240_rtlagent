"""Attribution contract v2 (A-00..A-08) and bounded evidence indexes.

The fixtures mirror the eleven hand-authored attribution replays recorded in
dev/runs/20261027-remaining-fix-plan/scripts/review-attribution/replay_fixtures.py
without reading dev/runs: synthetic evidence and checker payloads reproduce the
same acceptance boundaries (canonical echo, misread step, overclaim, public
expectation consistency, fabricated diagnostic code, properties holds).
"""

import json
import unittest

from agent.domain.rtl.adaptive_repair import diagnostic_codes, parse_repair, repair_request
from agent.domain.rtl.task import TaskSpec

TOP = "TopModule"
MODULE = ("module TopModule(input reset, input s, output dfr);"
          " assign dfr = s; endmodule")


def make_task():
    return TaskSpec.from_text(
        "synthetic",
        "Implement a level detector. Set dfr below the lowest sensor and clear it otherwise.",
        "module TopModule(input reset, input s, output dfr); endmodule",
    )


def json_block(value):
    return "```json\n" + json.dumps(value, ensure_ascii=False) + "\n```"


def with_rtl(value, code=MODULE):
    return json_block(value) + "\n\n```verilog\n" + code + "\n```\n"


def model_payload():
    return {
        "requirements": [{"id": "R1"}, {"id": "R2"}, {"id": "R3"}],
        "outputs": {"dfr": {"op": "ref", "ref": "s"}},
    }


def properties_payload():
    return {
        "requirements": [{"id": "R1"}],
        "properties": [
            {"id": "p0", "trigger": {"op": "ref", "ref": "s"}},
            {"id": "p1", "trigger": {"op": "ref", "ref": "s"}},
            {"id": "p2", "trigger": {"op": "ref", "ref": "s"}},
        ],
    }


def model_evidence(case="level_decrease_2_to_0", step=1, signal="dfr",
                   expected=0, actual=1, extra=None):
    counterexample = {"case_id": case, "step": step, "signal": signal,
                      "expected_bits_value": expected, "actual_bits_value": actual}
    failed = [
        {"case_id": case, "step": step, "signal": signal, "bit": 0,
         "expected_value": expected, "actual_value": actual},
        {"case_id": case, "step": step + 3, "signal": signal, "bit": 0,
         "expected_value": expected, "actual_value": actual},
    ]
    evidence = {"kind": "behavior", "route": "model", "counterexample": counterexample,
                "failed_mismatches": failed, "failed": 21, "passed": 99, "unknown": 0}
    if extra:
        evidence.update(extra)
    return evidence


def properties_evidence():
    counterexample = {
        "case_id": "all_ones_both_outputs", "property_id": "prop_p1y_zero_when_no_and",
        "trigger_step": 0, "trigger_tick": 0, "phase": "post", "status": "violated",
        "observations": [{"step": 0, "age": 0, "value": False, "abort": False}],
        "end_step": 0, "response_evaluations": 1, "unknown_seen": False,
    }
    failed = [{"property_id": "prop_p1y_zero_when_no_and", "case_id": "all_ones_both_outputs",
               "trigger_step": 0, "expected_holds": True, "observed_holds": False}]
    return {"kind": "behavior", "route": "properties", "counterexample": counterexample,
            "failed_mismatches": failed, "failed": 1, "passed": 20, "unknown": 0}


def structure_evidence(codes=("VRFC 10-9336",)):
    return {"kind": "structure", "check": "lint",
            "failure": {"details": {"repair_diagnostics":
                                    {"items": [{"code": code} for code in codes]}}},
            "diagnostic_codes": list(codes)}


def checker_suspect(*, binding=None, decision="checker_suspect", conclusion="unverified",
                    requirement="R1", quote="Set dfr below the lowest sensor",
                    defect=None):
    value = {
        "attribution_contract_version": 2,
        "decision": decision,
        "reason": "The checker omits the public clear case.",
        "candidate_conclusion": conclusion,
        "failure_binding": binding,
        "checker_defect": defect,
        "rtl_defect": None,
        "requirement_id": requirement,
        "public_quote": quote,
    }
    return value


def model_binding(**overrides):
    binding = {"case_id": "level_decrease_2_to_0", "step": 1, "signal": "dfr",
               "expected_value": 0, "actual_value": 1, "public_expectation": 1}
    binding.update(overrides)
    return binding


def properties_binding(**overrides):
    binding = {"property_id": "prop_p1y_zero_when_no_and",
               "case_id": "all_ones_both_outputs", "trigger_step": 0,
               "expected_holds": True, "observed_holds": False,
               "public_expectation": False}
    binding.update(overrides)
    return binding


def rtl_error_model(*, binding=None, defect=None):
    return {
        "attribution_contract_version": 2,
        "decision": "rtl_error",
        "reason": "The candidate does not implement the level detector.",
        "candidate_conclusion": "unverified",
        "failure_binding": binding,
        "checker_defect": None,
        "rtl_defect": defect,
        "requirement_id": "R1",
        "public_quote": "Set dfr below the lowest sensor",
    }


class AttributionFixtures(unittest.TestCase):
    """Eleven replay fixtures plus contract boundaries; never reads dev/runs."""

    def setUp(self):
        self.task = make_task()
        self.model = model_evidence()
        self.properties = properties_evidence()
        self.model_checker = model_payload()
        self.properties_checker = properties_payload()

    def parse(self, value, *, evidence=None, checker=None, text=None, finish_reason=None):
        return parse_repair(
            text if text is not None else json_block(value), TOP, task=self.task,
            evidence=evidence if evidence is not None else self.model,
            checker_payload=checker if checker is not None else self.model_checker,
            finish_reason=finish_reason,
        )

    def assert_rejected(self, value, message, *, evidence=None, checker=None,
                        text=None, finish_reason=None):
        with self.assertRaises(ValueError) as raised:
            self.parse(value, evidence=evidence, checker=checker, text=text,
                       finish_reason=finish_reason)
        self.assertIn(message, str(raised.exception))
        self.assertIn(message, str(raised.exception))

    # -- replay fixture 19: 149 checker_suspect canonical echo -----------------
    def test_149_checker_suspect_canonical(self):
        decision, extraction = self.parse(checker_suspect(
            binding=model_binding(),
            defect={"path": "/outputs/dfr", "claim": "dfr misses the s==0 clear case"}))
        self.assertEqual(decision["decision"], "checker_suspect")
        self.assertIsNone(extraction)
        self.assertEqual(decision["candidate_conclusion"], "unverified")

    # -- replay fixture 23: 128 checker_suspect canonical echo -----------------
    def test_128_checker_suspect_canonical(self):
        evidence = model_evidence(case="back_to_back", step=6, signal="done",
                                  expected=1, actual=0)
        decision, _ = self.parse(
            checker_suspect(binding=model_binding(
                case_id="back_to_back", step=6, signal="done",
                expected_value=1, actual_value=0, public_expectation=0),
                defect={"path": "/outputs/dfr", "claim": "done dead state"}),
            evidence=evidence)
        self.assertEqual(decision["decision"], "checker_suspect")

    # -- replay fixture 24: 081 properties checker_suspect ---------------------
    def test_081_properties_checker_suspect(self):
        decision, extraction = self.parse(
            checker_suspect(binding=properties_binding(),
                            defect={"path": "/properties/2/trigger",
                                    "claim": "eq(term, term) is not both terms zero"}),
            evidence=self.properties, checker=self.properties_checker)
        self.assertEqual(decision["decision"], "checker_suspect")
        self.assertIsNone(extraction)

    # -- replay fixture 25: 118 behavior rtl_error positive --------------------
    def test_118_rtl_error_canonical(self):
        evidence = model_evidence(case="shift_history", step=2, signal="predict_history",
                                  expected=1, actual=0)
        value = rtl_error_model(
            binding=model_binding(case_id="shift_history", step=2,
                                  signal="predict_history",
                                  expected_value=1, actual_value=0,
                                  public_expectation=1),
            defect={"locations": ["solution.sv"]})
        decision, extraction = self.parse(None, evidence=evidence, text=with_rtl(value))
        self.assertEqual(decision["decision"], "rtl_error")
        self.assertIsNotNone(extraction)
        self.assertEqual(extraction.status, "ok")
        self.assertTrue(extraction.complete)

    # -- replay fixture 29: 082 structural rtl_error with a real code ----------
    def test_082_structural_rtl_error(self):
        value = rtl_error_model(defect={"locations": ["module header"],
                                        "diagnostics": [{"code": "VRFC 10-9336"}]})
        value.pop("requirement_id")
        value["public_quote"] = "Implement a level detector."
        decision, extraction = self.parse(None, evidence=structure_evidence(),
                                          text=with_rtl(value))
        self.assertEqual(decision["decision"], "rtl_error")
        self.assertIsNotNone(extraction)

    # -- replay fixture 20: 149 additional recorded mismatch -------------------
    def test_149_additional_recorded_mismatch(self):
        value = checker_suspect(
            binding=model_binding(),
            defect={"path": "/outputs/dfr", "claim": "clear case missing"})
        value["additional_recorded_mismatches"] = [
            {"case_id": "level_decrease_2_to_0", "step": 4, "signal": "dfr",
             "expected_value": 0, "actual_value": 1}]
        decision, _ = self.parse(value)
        self.assertEqual(decision["decision"], "checker_suspect")

    # -- replay fixture 21: 149 failure step misread ---------------------------
    def test_149_failure_step_misread(self):
        self.assert_rejected(
            checker_suspect(binding=model_binding(step=4),
                            defect={"path": "/outputs/dfr", "claim": "step four"}),
            "A-03")

    # -- replay fixture 22: 149 overclaims the candidate is correct ------------
    def test_149_overclaim_candidate_correct(self):
        self.assert_rejected(
            checker_suspect(binding=model_binding(), conclusion="correct",
                            defect={"path": "/outputs/dfr", "claim": "clear case"}),
            "A-02")

    # -- replay fixture 26: 113 public expectation forces checker_suspect ------
    def test_113_public_expectation_forces_checker_suspect(self):
        value = rtl_error_model(binding=model_binding(public_expectation=1),
                                defect={"locations": ["solution.sv"]})
        self.assert_rejected(None, "A-04", text=with_rtl(value))

    # -- replay fixture 27: 118 decision inconsistent with public expectation --
    def test_118_decision_inconsistent(self):
        self.assert_rejected(
            checker_suspect(binding=model_binding(public_expectation=0),
                            defect={"path": "/outputs/dfr", "claim": "clear case"}),
            "A-04")

    # -- replay fixture 28: 082 fabricated diagnostic code --------------------
    def test_082_diagnostic_code_fabricated(self):
        value = rtl_error_model(defect={"locations": ["module header"],
                                        "diagnostics": [{"code": "VRFC 10-9999"}]})
        self.assert_rejected(None, "A-08", evidence=structure_evidence(),
                             text=with_rtl(value))

    # -- A-00 envelope compatibility boundary ---------------------------------
    def test_legacy_two_field_decision_is_invalid(self):
        self.assert_rejected(
            {"decision": "checker_suspect", "reason": "legacy response"},
            "A-01")

    def test_prose_before_json_is_rejected(self):
        text = "Looking at the K-map.\n" + json_block(checker_suspect(
            binding=model_binding(),
            defect={"path": "/outputs/dfr", "claim": "clear case"}))
        self.assert_rejected(None, "Expecting value", text=text)

    def test_attribution_version_one_is_invalid(self):
        value = checker_suspect(binding=model_binding(),
                                defect={"path": "/outputs/dfr", "claim": "clear case"})
        value["attribution_contract_version"] = 1
        self.assert_rejected(value, "A-01")

    def test_rtl_block_on_non_rtl_error_is_rejected(self):
        value = checker_suspect(binding=model_binding(),
                                defect={"path": "/outputs/dfr", "claim": "clear case"})
        self.assert_rejected(None, "only attributed RTL errors",
                             text=with_rtl(value))

    def test_rtl_error_without_replacement_is_rejected(self):
        value = rtl_error_model(binding=model_binding(public_expectation=0),
                                defect={"locations": ["solution.sv"]})
        self.assert_rejected(value, "only attributed RTL errors")

    def test_truncated_response_is_rejected(self):
        self.assert_rejected(checker_suspect(
            binding=model_binding(), defect={"path": "/outputs/dfr", "claim": "x"}),
            "truncated", finish_reason="length")

    # -- A-02..A-08 boundary rules -------------------------------------------
    def test_quote_must_be_verbatim_public_text(self):
        self.assert_rejected(checker_suspect(
            binding=model_binding(),
            defect={"path": "/outputs/dfr", "claim": "clear case"},
            quote="A sentence that is not in the public task"), "A-05")

    def test_quote_whitespace_is_normalized(self):
        value = checker_suspect(
            binding=model_binding(),
            defect={"path": "/outputs/dfr", "claim": "clear case"},
            quote="Set   dfr\nbelow the lowest sensor")
        decision, _ = self.parse(value)
        self.assertEqual(decision["decision"], "checker_suspect")

    def test_unknown_requirement_is_rejected(self):
        self.assert_rejected(checker_suspect(
            binding=model_binding(), requirement="R9",
            defect={"path": "/outputs/dfr", "claim": "clear case"}), "A-05")

    def test_checker_defect_pointer_must_exist(self):
        self.assert_rejected(checker_suspect(
            binding=model_binding(),
            defect={"path": "/outputs/missing", "claim": "clear case"}), "A-06")

    def test_checker_defect_claim_is_required(self):
        self.assert_rejected(checker_suspect(
            binding=model_binding(), defect={"path": "/outputs/dfr"}), "A-06")

    def test_rtl_error_requires_rtl_defect(self):
        value = rtl_error_model(binding=model_binding(public_expectation=0))
        self.assert_rejected(None, "A-07", text=with_rtl(value))

    def test_structural_checker_suspect_is_rejected(self):
        self.assert_rejected(
            checker_suspect(binding=model_binding(),
                            defect={"path": "/outputs/dfr", "claim": "clear case"}),
            "A-08", evidence=structure_evidence())

    def test_structural_diagnostics_are_optional(self):
        value = rtl_error_model(defect={"locations": ["module header"]})
        decision, _ = self.parse(None, evidence=structure_evidence(), text=with_rtl(value))
        self.assertEqual(decision["decision"], "rtl_error")

    def test_additional_mismatch_must_be_recorded(self):
        value = checker_suspect(
            binding=model_binding(),
            defect={"path": "/outputs/dfr", "claim": "clear case"})
        value["additional_recorded_mismatches"] = [
            {"case_id": "level_decrease_2_to_0", "step": 99, "signal": "dfr",
             "expected_value": 0, "actual_value": 1}]
        self.assert_rejected(value, "A-03b")

    def test_behavior_requires_failure_binding(self):
        self.assert_rejected(
            checker_suspect(binding=None,
                            defect={"path": "/outputs/dfr", "claim": "clear case"}),
            "A-03")

    def test_properties_binding_uses_holds_fields(self):
        binding = {"case_id": "all_ones_both_outputs",
                   "property_id": "prop_p1y_zero_when_no_and", "trigger_step": 0,
                   "expected_value": True, "actual_value": False,
                   "public_expectation": False}
        self.assert_rejected(
            checker_suspect(binding=binding,
                            defect={"path": "/properties/2/trigger", "claim": "trigger"}),
            "A-03", evidence=self.properties, checker=self.properties_checker)


def make_checker(payload, task, route="model"):
    from agent.domain.rtl.adaptive_check import FrozenChecker, parse_checker
    text = json.dumps({"status": "ready", "checker": payload})
    draft = parse_checker(text, task, route, finish_reason="stop")
    if draft.status != "ready":
        raise AssertionError(draft.reason)
    return FrozenChecker("approved", draft.route, "", draft.checker_hash,
                         draft.task_hash, draft._payload_json, draft._preflight_json, "{}")


def identity_assessment(checker, *, width, row_count, flip_bits=0):
    """Build a completed model assessment whose actual trace flips known bits."""
    from agent.domain.rtl.adaptive_selection import check_plan_hash
    from agent.domain.rtl.identity import suite_hash
    from agent.domain.rtl.suite.evaluate import expected_traces
    suite = checker.payload
    plan_hash = check_plan_hash(checker)
    implementation = "b" * 64
    traces, compared = [], 0
    for index, row in enumerate(expected_traces(suite)):
        actual = dict(row["expected_bits"])
        known = dict(row["expected_known"])
        if index == 0 and flip_bits:
            actual["y"] = (1 << width) - 1
        traces.append({**row, "actual_bits": actual, "actual_known": known})
        compared += sum(known[name].bit_count() for name in known
                        if row["expected_known"][name] is not None)
    details = {
        "candidate_hash": "c" * 64, "execution_id": "exec-1",
        "checker_hash": implementation, "plan_hash": plan_hash,
        "suite_hash": suite_hash(suite), "traces": traces, "compared_bits": compared,
    }
    return {
        "candidate_id": "c001", "candidate_hash": "c" * 64,
        "parent_id": None, "parent_hash": None, "execution_id": "e1",
        "checker_hash": checker.checker_hash, "check_plan_hash": plan_hash,
        "checker_implementation_hash": implementation, "structure": {},
        "behavior": {"route": "model", "status": "failed", "details": details},
    }


def identity_payload(task, width=8, steps=2):
    return {
        "schema_version": 1, "mode": "behavior",
        "ports": {"a": {"direction": "input", "width": width},
                  "y": {"direction": "output", "width": width}},
        "clock": None, "state": {}, "outputs": {"y": {"ref": "a"}},
        "requirements": [{"id": "R1", "quote": task.prompt}],
        "cases": [{"id": "c1", "requirements": ["R1"],
                   "steps": [{"inputs": {"a": 0}, "sample": True, "edge": False},
                             {"inputs": {"a": 1}, "sample": True, "edge": False}][:steps]}],
    }


class EvidenceIndex(unittest.TestCase):
    """Bounded failed_mismatches delivered to the repair prompt."""

    def task(self):
        return TaskSpec.from_text(
            "synthetic", "Output y equals input a.",
            "module TopModule(input [7:0] a, output [7:0] y); endmodule")

    def test_model_failed_mismatches_are_bound_and_traceable(self):
        from agent.domain.rtl.adaptive_selection import repair_opportunity
        task = self.task()
        checker = make_checker(identity_payload(task), task)
        assessment = identity_assessment(checker, width=8, row_count=2, flip_bits=8)
        opportunity = repair_opportunity(assessment, checker)
        self.assertEqual(opportunity["kind"], "behavior")
        self.assertEqual(opportunity["counterexample"]["expected_bits_value"], 0)
        self.assertEqual(opportunity["counterexample"]["actual_bits_value"], 255)
        rows = opportunity["failed_mismatches"]
        self.assertEqual(len(rows), 8)
        self.assertEqual(rows[0], {"case_id": "c1", "step": 0, "signal": "y", "bit": 0,
                                   "expected_value": 0, "actual_value": 1})
        self.assertEqual(opportunity["failed"], 8)
        self.assertEqual(opportunity["passed"], 8)

    def test_model_failed_mismatches_are_capped_at_32(self):
        from agent.domain.rtl.adaptive_selection import repair_opportunity
        task = TaskSpec.from_text(
            "synthetic", "Output y equals input a.",
            "module TopModule(input [63:0] a, output [63:0] y); endmodule")
        checker = make_checker(identity_payload(task, width=64, steps=1), task)
        assessment = identity_assessment(checker, width=64, row_count=1, flip_bits=64)
        opportunity = repair_opportunity(assessment, checker)
        self.assertEqual(len(opportunity["failed_mismatches"]), 32)
        self.assertEqual(opportunity["failed"], 64)

    def test_property_failed_mismatches_use_boolean_holds(self):
        from agent.domain.rtl.adaptive_selection import _property_mismatches
        failed = {("p1", "c1", 0, 0)}
        context = {("p1", "c1", 0, 0): {
            "observations": [{"step": 0, "age": 0, "value": False, "abort": False}]}}
        self.assertEqual(_property_mismatches(failed, context), [
            {"property_id": "p1", "case_id": "c1", "trigger_step": 0,
             "expected_holds": True, "observed_holds": False}])
        many = {(f"p{index}", "c1", 0, 0): context[("p1", "c1", 0, 0)]
                for index in range(40)}
        self.assertEqual(len(_property_mismatches(set(many), many)), 32)

    def properties_assessment(self):
        from agent.domain.rtl.adaptive_selection import check_plan_hash
        from agent.domain.rtl.identity import suite_hash
        from agent.domain.rtl.observation import sampling_hash
        from agent.domain.rtl.properties import property_hash
        task = TaskSpec.from_text(
            "synthetic", "The output y equals the one-bit input a.",
            "module TopModule(input a, output y); endmodule")
        payload = {
            "schema_version": 1,
            "sampling": {
                "schema_version": 1,
                "ports": {"a": {"direction": "input", "width": 1},
                          "y": {"direction": "output", "width": 1}},
                "clock": None,
                "cases": [{"id": "c1", "steps": [
                    {"inputs": {"a": 0}, "sample": True},
                    {"inputs": {"a": 1}, "sample": True}]}],
            },
            "requirements": [{"id": "R1", "quote": task.prompt}],
            "properties": [{
                "id": "p1", "requirements": ["R1"], "sample_phase": "post",
                "warmup_ticks": 0,
                "trigger": {"signal": "a", "phase": "post", "past": 0},
                "window": {"min": 0, "max": 0},
                "assertion": {"op": "eq", "width": 1, "args": [
                    {"signal": "y", "phase": "post", "past": 0},
                    {"signal": "a", "phase": "post", "past": 0}]},
            }],
        }
        checker = make_checker(payload, task, "properties")
        suite = checker.payload
        obligation = {
            "property_id": "p1", "case_id": "c1", "trigger_step": 1, "trigger_tick": 1,
            "phase": "post", "status": "violated",
            "observations": [{"step": 1, "age": 0, "value": False, "abort": False}],
            "end_step": 1, "response_evaluations": 1, "unknown_seen": False,
        }
        details = {
            "candidate_hash": "c" * 64, "execution_id": "exec-1",
            "checker_hash": "b" * 64, "plan_hash": sampling_hash(suite["sampling"]),
            "suite_hash": suite_hash(suite), "property_hash": property_hash(suite),
            "per_property": [{
                "property_id": "p1", "triggered": 1, "satisfied": 0, "violated": 1,
                "incomplete": 0, "aborted": 0, "unknown": 0,
                "obligations": [obligation]}],
            "unknown_triggers": [],
        }
        assessment = {
            "candidate_id": "c001", "candidate_hash": "c" * 64,
            "parent_id": None, "parent_hash": None, "execution_id": "e1",
            "checker_hash": checker.checker_hash,
            "check_plan_hash": check_plan_hash(checker),
            "checker_implementation_hash": "b" * 64, "structure": {},
            "behavior": {"route": "properties", "status": "failed", "details": details},
        }
        return task, checker, assessment

    def test_properties_failed_mismatches_use_validated_obligations(self):
        from agent.domain.rtl.adaptive_selection import repair_opportunity
        _, checker, assessment = self.properties_assessment()
        opportunity = repair_opportunity(assessment, checker)
        self.assertEqual(opportunity["kind"], "behavior")
        self.assertEqual(opportunity["counterexample"]["trigger_step"], 1)
        self.assertEqual(opportunity["failed_mismatches"], [
            {"property_id": "p1", "case_id": "c1", "trigger_step": 1,
             "expected_holds": True, "observed_holds": False}])
        self.assertEqual(opportunity["failed"], 1)

    def test_diagnostic_codes_are_read_from_saved_check_details(self):
        details = {
            "repair_diagnostics": {"items": [{"code": "VRFC 10-9336"},
                                             {"code": "VRFC 10-9999"}]},
            "knowledge_diagnostics": {"items": [{"code": "VRFC 10-9336"},
                                                {"code": None}]},
        }
        self.assertEqual(diagnostic_codes(details),
                         ["VRFC 10-9336", "VRFC 10-9999"])
        self.assertEqual(diagnostic_codes({}), [])


class RepairRequestContract(unittest.TestCase):
    def task(self):
        return make_task()

    def messages(self):
        task = self.task()
        parent = type("Parent", (), {
            "id": "c001", "code_hash": "synthetic",
            "code": "module TopModule(input reset, input s, output dfr); endmodule",
        })()
        return task, repair_request(task, parent, {"kind": "syntax"})

    def test_public_task_carries_expected_interface_and_raw_interface(self):
        task, messages = self.messages()
        user = json.loads(messages[1]["content"])
        public = user["public_task"]
        self.assertEqual(public["expected_interface"], task.expected_interface.public_dict())
        self.assertEqual(public["interface"], task.interface)
        self.assertEqual(public["interface_note"],
                         "Missing interface declarations remain unresolved; "
                         "the original public task takes precedence.")

    def test_system_prompt_states_attribution_v2_rules(self):
        _, messages = self.messages()
        system = messages[0]["content"]
        self.assertIn("approved checker is not ground truth", system)
        self.assertIn("candidate_conclusion", system)
        self.assertIn("unverified", system)
        self.assertIn("public_quote", system)
        self.assertIn("checker_suspect", system)
        self.assertIn("attribution_contract_version", system)


if __name__ == "__main__":
    unittest.main()
