"""Review contract v2 and construction normalization host rules (R-00..R-12)."""
from dataclasses import replace
import hashlib
import json
import unittest

from agent.domain.rtl.adaptive_check import (
    CheckerError, FrozenChecker, _drop_redundant_register_clock, _drop_request_echo,
    analyze_model_expectation_shape, analyze_property_trigger_census,
    approve_review, build_review_evidence, parse_checker, parse_checker_revision,
    review_request, revision_request,
)
from agent.domain.rtl.task import TaskSpec


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _ready(payload, route, task):
    draft = parse_checker(json.dumps({"status": "ready", "checker": payload}),
                          task, route, finish_reason="stop")
    assert draft.status == "ready", (draft.status, draft.reason)
    return draft


# ---------------------------------------------------------------------------
# Self-contained checker fixtures: they mirror the frozen failure shapes without
# reading dev/runs, so the regression never depends on external evidence.
# ---------------------------------------------------------------------------

def _anyedge_fixture():
    task = TaskSpec.from_text(
        "anyedge",
        "Output anyedge must be 1 when the input changed since the previous clock edge.",
        "module TopModule(input clk, input in, output anyedge); endmodule")
    payload = {
        "schema_version": 1, "mode": "behavior",
        "ports": {"clk": {"direction": "input", "width": 1},
                  "in": {"direction": "input", "width": 1},
                  "anyedge": {"direction": "output", "width": 1}},
        "clock": {"port": "clk", "edge": "posedge"},
        "state": {"model_prev_in": {"width": 1, "next": {"ref": "in"}}},
        "outputs": {"anyedge": {"op": "xor", "args": [
            {"ref": "in"}, {"ref": "model_prev_in"}], "width": 1}},
        "requirements": [{"id": "anyedge",
                          "quote": "Output anyedge must be 1 when the input changed"}],
        "cases": [{"id": "changes", "requirements": ["anyedge"], "steps": [
            {"inputs": {"in": 0}, "edge": False, "sample": False},
            {"inputs": {"in": 0}, "edge": True, "sample": False},
            {"inputs": {"in": 1}, "edge": True, "sample": True},
            {"inputs": {"in": 0}, "edge": True, "sample": True}]}],
    }
    return task, payload


def _count_fixture():
    """089-shaped sequence fixture with a clearly known expected sequence."""
    prompt = ("The register is defined as reg [1:0] count and initialized to 0 using the "
              "initial statement. Output count equals the current register value. "
              "The count register increments by the current input on each clock edge.")
    task = TaskSpec.from_text(
        "count",
        prompt,
        "module TopModule(input clk, input in, output [1:0] count); endmodule")
    payload = {
        "schema_version": 1, "mode": "behavior",
        "ports": {"clk": {"direction": "input", "width": 1},
                  "in": {"direction": "input", "width": 1},
                  "count": {"direction": "output", "width": 2}},
        "clock": {"port": "clk", "edge": "posedge"},
        "state": {"model_count": {
            "width": 2,
            "initial": {"value": 0, "signal": "count",
                        "quote": "The register is defined as reg [1:0] count and "
                                 "initialized to 0 using the initial statement."},
            "next": {"op": "add", "args": [{"ref": "model_count"}, {"ref": "in"}],
                     "width": 2}}},
        "outputs": {"count": {"ref": "model_count"}},
        "requirements": [{"id": "count_sequence",
                          "quote": "Output count equals the current register value."}],
        "cases": [{"id": "increment", "requirements": ["count_sequence"], "steps": [
            {"inputs": {"in": 0}, "edge": True, "sample": True},
            {"inputs": {"in": 1}, "edge": True, "sample": True},
            {"inputs": {"in": 1}, "edge": True, "sample": True}]}],
    }
    return task, payload


def _concat_fixture():
    """082-shaped 32-argument concat in a register next expression."""
    task = TaskSpec.from_text(
        "concat32",
        "Output q is the 32-bit register value. The register updates from input d on "
        "each rising clock edge.",
        "module TopModule(input clk, input [31:0] d, output [31:0] q); endmodule")
    slices = [{"op": "slice", "args": [{"ref": "d"}], "lsb": index, "width": 1}
              for index in range(32)]
    payload = {
        "schema_version": 1, "mode": "behavior",
        "ports": {"clk": {"direction": "input", "width": 1},
                  "d": {"direction": "input", "width": 32},
                  "q": {"direction": "output", "width": 32}},
        "clock": {"port": "clk", "edge": "posedge"},
        "state": {"model_q": {
            "width": 32,
            "next": {"op": "concat", "args": slices, "width": 32}}},
        "outputs": {"q": {"ref": "model_q"}},
        "requirements": [{"id": "register_value",
                          "quote": "Output q is the 32-bit register value."}],
        "cases": [{"id": "loading", "requirements": ["register_value"], "steps": [
            {"inputs": {"d": 1}, "edge": True, "sample": True},
            {"inputs": {"d": 0xFFFFFFFF}, "edge": True, "sample": True},
            {"inputs": {"d": 0}, "edge": True, "sample": True}]}],
    }
    return task, payload


def _shift_fixture():
    """084-shaped checker: state is known by warm-up but has no initial or reset."""
    task = TaskSpec.from_text(
        "shift",
        "Output y follows the last input bit after two rising edges.",
        "module TopModule(input clk, input in, output y); endmodule")
    payload = {
        "schema_version": 1, "mode": "behavior",
        "ports": {"clk": {"direction": "input", "width": 1},
                  "in": {"direction": "input", "width": 1},
                  "y": {"direction": "output", "width": 1}},
        "clock": {"port": "clk", "edge": "posedge"},
        "state": {"model_q": {"width": 1, "next": {"ref": "in"}}},
        "outputs": {"y": {"ref": "model_q"}},
        "requirements": [{"id": "delayed", "quote": "Output y follows the last input bit"}],
        "cases": [{"id": "warmup", "requirements": ["delayed"], "steps": [
            {"inputs": {"in": 0}, "edge": True, "sample": False},
            {"inputs": {"in": 1}, "edge": True, "sample": True},
            {"inputs": {"in": 0}, "edge": True, "sample": True}]}],
    }
    return task, payload


def _slice_fixture():
    """085-shaped 3-bit slice inside a load expression."""
    task = TaskSpec.from_text(
        "slice4",
        "Output q loads the low four input bits on each rising clock edge. "
        "The low three bits come from data[3:1].",
        "module TopModule(input clk, input [3:0] data, output [3:0] q); endmodule")
    payload = {
        "schema_version": 1, "mode": "behavior",
        "ports": {"clk": {"direction": "input", "width": 1},
                  "data": {"direction": "input", "width": 4},
                  "q": {"direction": "output", "width": 4}},
        "clock": {"port": "clk", "edge": "posedge"},
        "state": {"model_q": {"width": 4, "next": {"op": "concat", "args": [
            {"op": "slice", "args": [{"ref": "data"}], "lsb": 1, "width": 3},
            {"op": "slice", "args": [{"ref": "data"}], "lsb": 0, "width": 1},
        ], "width": 4}}},
        "outputs": {"q": {"ref": "model_q"}},
        "requirements": [{"id": "load", "quote": "Output q loads the low four input bits"}],
        "cases": [{"id": "loading", "requirements": ["load"], "steps": [
            {"inputs": {"data": 4}, "edge": True, "sample": False},
            {"inputs": {"data": 2}, "edge": True, "sample": True},
            {"inputs": {"data": 9}, "edge": True, "sample": True}]}],
    }
    return task, payload


def _properties_fixture():
    """081-shaped properties: an eq(term, term) trigger that is always true."""
    task = TaskSpec.from_text(
        "and_gate",
        "Output y is the AND of inputs a and b.",
        "module TopModule(input a, input b, output y); endmodule")
    leaf = lambda name, phase="pre": {"signal": name, "phase": phase, "past": 0,
                                      "anchor": False}
    term = {"op": "and", "args": [leaf("a"), leaf("b")], "width": 1}
    payload = {
        "schema_version": 1,
        "sampling": {
            "schema_version": 1,
            "ports": {"a": {"direction": "input", "width": 1},
                      "b": {"direction": "input", "width": 1},
                      "y": {"direction": "output", "width": 1}},
            "cases": [
                {"id": "all_ones", "steps": [
                    {"inputs": {"a": 1, "b": 1}},
                    {"inputs": {"a": 1, "b": 1}}]},
                {"id": "mixed", "steps": [
                    {"inputs": {"a": 1, "b": 0}}]},
            ],
        },
        "requirements": [
            {"id": "r_and", "quote": "Output y is the AND of inputs a and b."},
            {"id": "r_eq", "quote": "Output y is the AND of inputs a and b."},
        ],
        "properties": [
            {"id": "p_and", "requirements": ["r_and"], "sample_phase": "post",
             "warmup_ticks": 0, "trigger": {"const": 1, "width": 1},
             "window": {"min": 0, "max": 0},
             "assertion": {"op": "eq", "args": [leaf("y", "post"), term], "width": 1},
             "abort": None, "abort_requirements": []},
            {"id": "p_eq", "requirements": ["r_eq"], "sample_phase": "post",
             "warmup_ticks": 0,
             "trigger": {"op": "eq", "args": [term, term], "width": 1},
             "window": {"min": 0, "max": 0},
             "assertion": {"op": "ne", "args": [leaf("y", "post"),
                                               {"const": 0, "width": 1}], "width": 1},
             "abort": None, "abort_requirements": []},
        ],
    }
    return task, payload


def _stateless_fixture():
    """092-shaped six-vector combinational checker."""
    task = TaskSpec.from_text(
        "gates",
        "Output y is 1 when a is 1 and b is 0; otherwise y is 0.",
        "module TopModule(input a, input b, output y); endmodule")
    payload = {
        "schema_version": 1, "mode": "behavior",
        "ports": {"a": {"direction": "input", "width": 1},
                  "b": {"direction": "input", "width": 1},
                  "y": {"direction": "output", "width": 1}},
        "clock": None, "state": {},
        "outputs": {"y": {"op": "and", "args": [
            {"ref": "a"}, {"op": "not", "args": [{"ref": "b"}], "width": 1}],
            "width": 1}},
        "requirements": [{"id": "gates",
                          "quote": "Output y is 1 when a is 1 and b is 0"}],
        "cases": [{"id": "vectors", "requirements": ["gates"], "steps": [
            {"inputs": {"a": 0, "b": 0}},
            {"inputs": {"a": 0, "b": 1}},
            {"inputs": {"a": 1, "b": 0}},
            {"inputs": {"a": 1, "b": 1}},
            {"inputs": {"a": 1, "b": 0}},
            {"inputs": {"a": 0, "b": 1}}]}],
    }
    return task, payload


# ---------------------------------------------------------------------------
# Review builders
# ---------------------------------------------------------------------------

def _witness_for(payload, evidence, requirement_id):
    if evidence["route"] == "model":
        for case in payload["cases"]:
            if requirement_id not in case.get("requirements", []):
                continue
            rows = [row for row in evidence["expected_table"]
                    if row["case_id"] == case["id"]]
            steps = [{"step": row["step"],
                      "outputs": {name: value for name, value in row["expected"].items()
                                  if isinstance(value, int)}}
                     for row in rows[:2]]
            steps = [step for step in steps if step["outputs"]]
            if steps:
                return {"case_id": case["id"], "steps": steps}
        raise AssertionError("no comparable table rows bind " + requirement_id)
    for prop in payload["properties"]:
        if requirement_id not in prop["requirements"]:
            continue
        rows = [row for row in evidence["predicted_triggers"]
                if row["property_id"] == prop["id"]]
        if not rows:
            continue
        case_id = rows[0]["case_id"]
        steps = [{"step": row["step"], "outputs": {"trigger": row["trigger"]}}
                 for row in rows if row["case_id"] == case_id][:2]
        return {"case_id": case_id, "property_id": prop["id"], "steps": steps}
    raise AssertionError("no trigger rows bind " + requirement_id)


def _review(draft, *, decision="accept", counterexamples=None):
    evidence = build_review_evidence(draft)
    payload = draft.payload
    requirements = [item["id"] for item in payload["requirements"]]
    reviews = []
    for requirement_id in requirements:
        if decision == "accept":
            reviews.append({"requirement_id": requirement_id, "verdict": "supported",
                            "witness": _witness_for(payload, evidence, requirement_id)})
        else:
            reviews.append({"requirement_id": requirement_id, "verdict": "contradicted"})
    return {
        "review_contract_version": 2,
        "checker_hash": draft.checker_hash,
        "expected_table_sha256": evidence["expected_table_sha256"],
        "decision": decision,
        "reason": "Synthetic contract fixture; the frozen payload is reviewed directly.",
        "checked_requirements": requirements,
        "requirement_reviews": reviews,
        "claims": evidence["required_claims"] + evidence["required_trigger_claims"],
        "state_phase_claims": evidence["required_phase_claims"],
        "init_claims": [{"register": item["register"],
                         "source": item["allowed_sources"][0]}
                        for item in evidence["required_init_claims"]],
        "degenerate_outputs": evidence["required_degenerate_outputs"],
        "counterexamples": list(counterexamples or []),
    }


def _approve(draft, review):
    return approve_review(json.dumps(review), draft, finish_reason="stop")


class ReviewContractTests(unittest.TestCase):
    def assert_violation(self, frozen, rule):
        self.assertEqual(frozen.status, "invalid", frozen.reason)
        self.assertTrue(frozen.violations, "missing violation detail")
        self.assertTrue(frozen.violations[0].startswith(rule),
                        (rule, frozen.violations))

    # -- the 16 report fixtures, in equivalent self-contained form -----------

    def test_045_honest_accept_and_degenerate_expectation(self):
        task, payload = _anyedge_fixture()
        draft = _ready(payload, "model", task)
        evidence = build_review_evidence(draft)
        # The XOR of in with the NEW state is constant zero: the host must expose it.
        self.assertEqual(evidence["required_degenerate_outputs"], [{"output": "anyedge"}])
        shape = analyze_model_expectation_shape(draft.payload)
        self.assertTrue(shape["zero_change"])
        self.assertTrue(shape["outputs"]["anyedge"]["bit_never_one"])
        self.assertEqual(shape["requirements"][0]["expected_ones"], 0)
        self.assertTrue(shape["requirements"][0]["quote_mentions_one"])
        frozen = _approve(draft, _review(draft))
        self.assertEqual(frozen.status, "approved", frozen.violations)

    def test_accept_with_insufficient_verdict_is_invalid(self):
        task, payload = _anyedge_fixture()
        draft = _ready(payload, "model", task)
        review = _review(draft)
        review["requirement_reviews"][0]["verdict"] = "insufficient"
        review["requirement_reviews"][0].pop("witness", None)
        self.assert_violation(_approve(draft, review), "R-05")

    def test_045_witness_claimed_nonzero(self):
        task, payload = _anyedge_fixture()
        draft = _ready(payload, "model", task)
        review = _review(draft)
        review["requirement_reviews"][0]["witness"]["steps"][0]["outputs"]["anyedge"] = 1
        frozen = _approve(draft, review)
        self.assert_violation(frozen, "R-06")
        self.assertTrue(frozen.retryable)

    def test_045_phase_declared_old(self):
        task, payload = _anyedge_fixture()
        draft = _ready(payload, "model", task)
        review = _review(draft)
        for claim in review["state_phase_claims"]:
            if claim["used_in"] == "outputs":
                claim["phase"] = "OLD"
        self.assert_violation(_approve(draft, review), "R-08")

    def test_045_degenerate_not_declared(self):
        task, payload = _anyedge_fixture()
        draft = _ready(payload, "model", task)
        review = _review(draft)
        review["degenerate_outputs"] = []
        self.assert_violation(_approve(draft, review), "R-10")

    def test_045_honest_reject_is_rejected(self):
        task, payload = _anyedge_fixture()
        draft = _ready(payload, "model", task)
        frozen = _approve(draft, _review(draft, decision="reject"))
        self.assertEqual(frozen.status, "rejected", frozen.violations)
        self.assertTrue(frozen.repair_authorized is False)
        self.assertFalse(frozen.retryable)

    def test_089_witness_sequence_misread(self):
        task, payload = _count_fixture()
        draft = _ready(payload, "model", task)
        rows = build_review_evidence(draft)["expected_table"]
        host = {(row["case_id"], row["step"]): row["expected"]["count"] for row in rows}
        self.assertEqual(host[("increment", 1)], 1)
        review = _review(draft)
        steps = review["requirement_reviews"][0]["witness"]["steps"]
        for step in steps:
            if step["step"] == 1:
                step["outputs"]["count"] = host[("increment", 1)] + 1
        self.assert_violation(_approve(draft, review), "R-06")

    def test_082_concat_arity_misread(self):
        task, payload = _concat_fixture()
        draft = _ready(payload, "model", task)
        evidence = build_review_evidence(draft)
        required = [(item["kind"], item["path"]) for item in evidence["required_claims"]]
        self.assertIn(("concat_arity", "/state/model_q/next"), required)
        self.assertEqual(len(required), 17)  # all concat nodes + first 16 slices
        review = _review(draft)
        claims = [claim for claim in review["claims"]
                  if claim["kind"] == "concat_arity"]
        self.assertEqual(len(claims), 1)
        claims[0]["value"] = 31
        self.assert_violation(_approve(draft, review), "R-07")

    def test_082_missing_required_claims(self):
        task, payload = _concat_fixture()
        draft = _ready(payload, "model", task)
        review = _review(draft)
        review["claims"] = []
        self.assert_violation(_approve(draft, review), "R-07b")

    def test_082_honest_reject(self):
        task, payload = _concat_fixture()
        draft = _ready(payload, "model", task)
        frozen = _approve(draft, _review(draft, decision="reject"))
        self.assertEqual(frozen.status, "rejected", frozen.violations)

    def test_084_initial_value_fabricated(self):
        task, payload = _shift_fixture()
        draft = _ready(payload, "model", task)
        review = _review(draft)
        self.assertEqual(review["init_claims"][0]["source"], "unconstrained")
        review["init_claims"][0]["source"] = "initial"
        self.assert_violation(_approve(draft, review), "R-09")

    def test_084_honest_accept(self):
        task, payload = _shift_fixture()
        draft = _ready(payload, "model", task)
        frozen = _approve(draft, _review(draft))
        self.assertEqual(frozen.status, "approved", frozen.violations)

    def test_085_slice_parameter_misread(self):
        task, payload = _slice_fixture()
        draft = _ready(payload, "model", task)
        review = _review(draft)
        claims = [claim for claim in review["claims"] if claim["kind"] == "slice"]
        self.assertTrue(claims)
        claims[0]["lsb"] = 0
        self.assert_violation(_approve(draft, review), "R-07")

    def test_085_honest_accept(self):
        task, payload = _slice_fixture()
        draft = _ready(payload, "model", task)
        frozen = _approve(draft, _review(draft))
        self.assertEqual(frozen.status, "approved", frozen.violations)

    def test_092_honest_accept(self):
        task, payload = _stateless_fixture()
        draft = _ready(payload, "model", task)
        shape = analyze_model_expectation_shape(draft.payload)
        self.assertFalse(shape["zero_change"])
        self.assertEqual(shape["expected_ones"], 2)
        frozen = _approve(draft, _review(draft))
        self.assertEqual(frozen.status, "approved", frozen.violations)

    def test_081_trigger_value_misread(self):
        task, payload = _properties_fixture()
        draft = _ready(payload, "properties", task)
        census = analyze_property_trigger_census(draft.payload)
        self.assertFalse(census["predicted_empty"])
        self.assertEqual(census["unknown"], 0)
        self.assertEqual(len(census["rows"]), 6)
        review = _review(draft)
        target = next(claim for claim in review["claims"]
                      if claim["property_id"] == "p_eq"
                      and claim["case_id"] == "all_ones" and claim["step"] == 0)
        self.assertTrue(target["value"])
        target["value"] = False
        self.assert_violation(_approve(draft, review), "R-12")

    def test_081_honest_accept(self):
        task, payload = _properties_fixture()
        draft = _ready(payload, "properties", task)
        frozen = _approve(draft, _review(draft))
        self.assertEqual(frozen.status, "approved", frozen.violations)

    def test_128_counterexample_forces_reject(self):
        task, payload = _anyedge_fixture()
        draft = _ready(payload, "model", task)
        review = _review(draft, counterexamples=[{"case_id": "changes", "step": 2,
                                                  "output": "anyedge", "expected": 1}])
        self.assert_violation(_approve(draft, review), "R-11")
        honest = _review(draft, decision="reject",
                         counterexamples=[{"case_id": "changes", "step": 2,
                                           "output": "anyedge", "expected": 1}])
        frozen = _approve(draft, honest)
        self.assertEqual(frozen.status, "rejected", frozen.violations)

    def test_128_contract_acceptable_limitation(self):
        # An honest-format accept of a semantically wrong checker is allowed by the
        # host contract; this records the known limitation instead of hiding it.
        task, payload = _anyedge_fixture()
        draft = _ready(payload, "model", task)
        self.assertEqual(_approve(draft, _review(draft)).status, "approved")

    # -- R-00..R-12 structural boundaries -----------------------------------

    def test_r00_envelope_is_strict(self):
        task, payload = _anyedge_fixture()
        draft = _ready(payload, "model", task)
        review = _review(draft)
        for text, finish in (
                ("Here is the review: " + json.dumps(review), "stop"),
                (json.dumps(review)[:-1], "stop"),
                ('{"checker_hash":"a","checker_hash":"b"}', "stop"),
                ('{"review_contract_version": NaN}', "stop"),
                (json.dumps(review), "length")):
            frozen = approve_review(text, draft, finish_reason=finish)
            self.assert_violation(frozen, "R-00")

    def test_r01_exact_fields_and_version(self):
        task, payload = _anyedge_fixture()
        draft = _ready(payload, "model", task)
        missing = _review(draft)
        missing.pop("claims")
        self.assert_violation(_approve(draft, missing), "R-01")
        extra = _review(draft)
        extra["advice"] = "also check this"
        self.assert_violation(_approve(draft, extra), "R-01")
        version = _review(draft)
        version["review_contract_version"] = 1
        self.assert_violation(_approve(draft, version), "R-01")

    def test_r02_decision_and_reason(self):
        task, payload = _anyedge_fixture()
        draft = _ready(payload, "model", task)
        decision = _review(draft)
        decision["decision"] = "maybe"
        self.assert_violation(_approve(draft, decision), "R-02")
        reason = _review(draft)
        reason["reason"] = "   "
        self.assert_violation(_approve(draft, reason), "R-02")

    def test_r03_echo_binding(self):
        task, payload = _anyedge_fixture()
        draft = _ready(payload, "model", task)
        checker = _review(draft)
        checker["checker_hash"] = "0" * 64
        self.assert_violation(_approve(draft, checker), "R-03")
        table = _review(draft)
        table["expected_table_sha256"] = "0" * 64
        self.assert_violation(_approve(draft, table), "R-03")

    def test_r04_checked_requirements(self):
        task, payload = _concat_fixture()
        widened = json.loads(json.dumps(payload))
        widened["cases"][0]["requirements"] = ["register_value", "second"]
        widened["requirements"].append({"id": "second",
                                        "quote": "The register updates from input d"})
        draft = _ready(widened, "model", task)
        approved = _review(draft)
        approved["checked_requirements"] = ["register_value"]
        self.assert_violation(_approve(draft, approved), "R-04")
        duplicate = _review(draft)
        duplicate["checked_requirements"] = ["register_value", "register_value", "second"]
        self.assert_violation(_approve(draft, duplicate), "R-04")

    def test_r05_decision_consistency(self):
        task, payload = _concat_fixture()
        draft = _ready(payload, "model", task)
        reject_without_contradiction = _review(draft, decision="reject")
        for item in reject_without_contradiction["requirement_reviews"]:
            item["verdict"] = "supported"
            item["witness"] = _witness_for(payload, build_review_evidence(draft),
                                           item["requirement_id"])
        self.assert_violation(_approve(draft, reject_without_contradiction), "R-05")

    def test_r05_unknown_remains_unknown(self):
        task, payload = _anyedge_fixture()
        draft = _ready(payload, "model", task)
        review = _review(draft)
        review["decision"] = "unknown"
        review["requirement_reviews"] = []
        frozen = _approve(draft, review)
        self.assertEqual(frozen.status, "unknown", frozen.violations)
        self.assertFalse(frozen.repair_authorized)
        self.assertFalse(frozen.retryable)

    def test_r06_witness_requires_sampled_event(self):
        task, payload = _anyedge_fixture()
        draft = _ready(payload, "model", task)
        review = _review(draft)
        review["requirement_reviews"][0]["witness"]["steps"] = [
            {"step": 1, "outputs": {"anyedge": 0}}]
        self.assert_violation(_approve(draft, review), "R-06")

    def test_r06_unknown_witness_value(self):
        task, payload = _anyedge_fixture()
        draft = _ready(payload, "model", task)
        review = _review(draft)
        review["requirement_reviews"][0]["witness"]["steps"][0]["outputs"]["anyedge"] = 0
        # Host predicts zero here, so a value is fine; unknown is accepted as unknown
        # only for rows the host also marks unknown.
        review["requirement_reviews"][0]["witness"]["steps"][0]["outputs"]["anyedge"] = "unknown"
        self.assert_violation(_approve(draft, review), "R-06")

    def test_r07_claim_paths_and_values(self):
        task, payload = _concat_fixture()
        draft = _ready(payload, "model", task)
        unknown_kind = _review(draft)
        unknown_kind["claims"] = unknown_kind["claims"] + [
            {"kind": "mystery", "path": "/outputs/q", "value": 1}]
        self.assert_violation(_approve(draft, unknown_kind), "R-07")
        bad_path = _review(draft)
        bad_path["claims"] = bad_path["claims"] + [
            {"kind": "ref", "path": "/outputs/nope", "value": "q"}]
        self.assert_violation(_approve(draft, bad_path), "R-07")
        bad_op = _review(draft)
        bad_op["claims"] = bad_op["claims"] + [
            {"kind": "op", "path": "/outputs/q", "value": "xor"}]
        self.assert_violation(_approve(draft, bad_op), "R-07")
        duplicate = _review(draft)
        duplicate["claims"] = duplicate["claims"] + [dict(duplicate["claims"][0])]
        self.assert_violation(_approve(draft, duplicate), "R-07")

    def test_r08_phase_set_is_exact(self):
        task, payload = _shift_fixture()
        draft = _ready(payload, "model", task)
        review = _review(draft)
        review["state_phase_claims"] = []
        self.assert_violation(_approve(draft, review), "R-08")
        extra = _review(draft)
        extra["state_phase_claims"] = extra["state_phase_claims"] + [
            {"used_in": "state.next", "register": "model_q", "phase": "OLD"}]
        self.assert_violation(_approve(draft, extra), "R-08")

    def test_r09_init_source_and_coverage(self):
        task, payload = _count_fixture()
        draft = _ready(payload, "model", task)
        review = _review(draft)
        self.assertEqual(review["init_claims"][0]["source"], "initial")
        wrong = _review(draft)
        wrong["init_claims"][0]["source"] = "reset"
        self.assert_violation(_approve(draft, wrong), "R-09")
        missing = _review(draft)
        missing["init_claims"] = []
        self.assert_violation(_approve(draft, missing), "R-09")

    def test_r10_degenerate_set_is_exact(self):
        task, payload = _anyedge_fixture()
        draft = _ready(payload, "model", task)
        extra = _review(draft)
        extra["degenerate_outputs"] = []
        self.assert_violation(_approve(draft, extra), "R-10")
        extras = _review(draft)
        extras["degenerate_outputs"] = extras["degenerate_outputs"] + [
            {"output": "in"}]
        self.assert_violation(_approve(draft, extras), "R-10")

    def test_r11_counterexample_requires_reject(self):
        task, payload = _anyedge_fixture()
        draft = _ready(payload, "model", task)
        review = _review(draft)
        review["counterexamples"] = [{"case_id": "changes", "step": 2}]
        self.assert_violation(_approve(draft, review), "R-11")

    def test_r12_required_trigger_claims(self):
        task, payload = _properties_fixture()
        draft = _ready(payload, "properties", task)
        review = _review(draft)
        review["claims"] = [claim for claim in review["claims"]
                            if not (claim["kind"] == "trigger"
                                    and claim["property_id"] == "p_and"
                                    and claim["case_id"] == "mixed")]
        self.assert_violation(_approve(draft, review), "R-12")

    # -- normalization ------------------------------------------------------

    def test_route_echo_is_dropped_but_hash_binds_normalized_payload(self):
        task, payload = _anyedge_fixture()
        echoed = {"route": "model", **payload}
        draft = _ready(echoed, "model", task)
        records = draft.preflight["normalization"]
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["method"], "drop_request_echo")
        self.assertEqual(record["model_calls"], 0)
        self.assertEqual(record["dropped"], [{
            "path": ["checker", "route"], "value": "model", "request_value": "model"}])
        clean = _ready(payload, "model", task)
        self.assertEqual(draft.checker_hash, clean.checker_hash)
        self.assertEqual(draft.payload, clean.payload)
        self.assertNotIn("route", draft.payload)
        # The recorded normalized hash is independently reproducible from the response.
        response = json.loads(json.dumps({"status": "ready", "checker": echoed}))
        del response["checker"]["route"]
        expected = hashlib.sha256(_canonical(response).encode()).hexdigest()
        self.assertEqual(record["normalized_response_sha256"], expected)
        self.assertEqual(record["original_response_sha256"],
                         hashlib.sha256(json.dumps(
                             {"status": "ready", "checker": echoed}).encode()).hexdigest())

    def test_bare_route_echo_is_dropped(self):
        task, payload = _anyedge_fixture()
        echoed = {"route": "model", **payload}
        draft = parse_checker(json.dumps(echoed), task, "model", finish_reason="stop")
        self.assertEqual(draft.status, "ready", draft.reason)
        self.assertEqual(draft.preflight["normalization"][0]["dropped"], [{
            "path": ["route"], "value": "model", "request_value": "model"}])

    def test_route_echo_never_relaxes_other_fields(self):
        task, payload = _anyedge_fixture()
        mismatched = {"route": "properties", **payload}
        draft = parse_checker(json.dumps({"status": "ready", "checker": mismatched}),
                              task, "model")
        self.assertEqual(draft.status, "invalid")
        self.assertIn("route", draft.reason)
        nested = _properties_fixture()
        nested_payload = json.loads(json.dumps(nested[1]))
        nested_payload["sampling"]["route"] = "properties"
        draft = parse_checker(json.dumps({"status": "ready", "checker": nested_payload}),
                              nested[0], "properties")
        self.assertEqual(draft.status, "invalid")

    def test_redundant_register_clock_is_dropped_only_when_equivalent(self):
        task, payload = _anyedge_fixture()
        echoed = json.loads(json.dumps(payload))
        echoed["state"]["model_prev_in"]["clock"] = "clk"
        draft = _ready(echoed, "model", task)
        records = draft.preflight["normalization"]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["method"], "drop_redundant_register_clock")
        self.assertEqual(records[0]["legacy_clock"],
                         {"port": "clk", "edge": "posedge"})
        self.assertEqual(records[0]["dropped"],
                         [{"path": ["checker", "state", "model_prev_in", "clock"],
                           "value": "clk"}])
        self.assertNotIn("clock", draft.payload["state"]["model_prev_in"])
        clean = _ready(payload, "model", task)
        self.assertEqual(draft.checker_hash, clean.checker_hash)
        self.assertIsInstance(draft.checker_hash, str)

    def test_register_clock_mismatch_and_missing_clock_stay_invalid(self):
        task, payload = _anyedge_fixture()
        mismatch = json.loads(json.dumps(payload))
        mismatch["state"]["model_prev_in"]["clock"] = "clk2"
        draft = parse_checker(json.dumps({"status": "ready", "checker": mismatch}),
                              task, "model")
        self.assertEqual(draft.status, "invalid")
        self.assertNotIn("normalization", draft.preflight)
        # 028 shape: state exists but there is no legacy clock to infer from.
        missing = json.loads(json.dumps(payload))
        missing.pop("clock")
        missing["state"]["model_prev_in"]["clock"] = None
        draft = parse_checker(json.dumps({"status": "ready", "checker": missing}),
                              task, "model")
        self.assertEqual(draft.status, "invalid")
        self.assertNotIn("normalization", draft.preflight)

    # -- request/evidence surface ------------------------------------------

    def test_review_request_carries_bounded_evidence_and_strips_normalization(self):
        task, payload = _anyedge_fixture()
        echoed = {"route": "model", **payload}
        draft = _ready(echoed, "model", task)
        self.assertIn("normalization", draft.preflight)
        messages = review_request(task, draft)
        user = json.loads(messages[1]["content"])
        self.assertEqual(user["review_contract_version"], 2)
        self.assertNotIn("normalization", user["preflight"])
        evidence = user["review_evidence"]
        self.assertEqual(evidence["sources"], {
            "checker_only": True, "candidate_rtl": False, "dut_observations": False})
        self.assertEqual(evidence["expected_table_sha256"], user["expected_table_sha256"])
        self.assertTrue(evidence["expected_table"])
        self.assertEqual(evidence["review_contract_version"], 2)
        retry = json.loads(review_request(
            task, draft, violations=["R-03: checker_hash expected abc"])[1]["content"])
        self.assertEqual(retry["contract_violations"],
                         ["R-03: checker_hash expected abc"])

    def test_review_evidence_is_deterministic_and_hash_bound(self):
        task, payload = _stateless_fixture()
        draft = _ready(payload, "model", task)
        first = build_review_evidence(draft)
        second = build_review_evidence(draft)
        self.assertEqual(first, second)
        table = first["expected_table"]
        self.assertFalse(first["expected_table_truncated"])
        digest = hashlib.sha256(_canonical(table).encode()).hexdigest()
        self.assertEqual(first["expected_table_sha256"], digest)
        self.assertEqual(first["evidence_sha256"],
                         hashlib.sha256(_canonical(
                             {key: value for key, value in first.items()
                              if key != "evidence_sha256"}).encode()).hexdigest())

    def test_frozen_checker_attributes(self):
        task, payload = _anyedge_fixture()
        draft = _ready(payload, "model", task)
        frozen = _approve(draft, _review(draft))
        self.assertIsInstance(frozen, FrozenChecker)
        self.assertTrue(frozen.repair_authorized)
        self.assertEqual(frozen.violations, [])
        self.assertFalse(frozen.retryable)
        self.assertEqual(frozen.review_record["review_contract_version"], 2)
        public = frozen.public_dict()
        for key in ("retryable", "violations", "review_record", "review"):
            self.assertIn(key, public)
        invalid = approve_review("not json", draft)
        self.assertFalse(invalid.repair_authorized)
        self.assertTrue(invalid.retryable)
        self.assertTrue(invalid.violations[0].startswith("R-00"))

    def test_legacy_v1_review_is_invalid_with_retry(self):
        task, payload = _anyedge_fixture()
        draft = _ready(payload, "model", task)
        legacy = {"checker_hash": draft.checker_hash, "decision": "accept",
                  "reason": "looks right", "checked_requirements": ["anyedge"]}
        frozen = _approve(draft, legacy)
        self.assert_violation(frozen, "R-01")
        self.assertTrue(frozen.retryable)

    # -- controlled retry and revision binding ------------------------------

    def test_revision_requires_intact_v2_rejection(self):
        task, payload = _anyedge_fixture()
        draft = _ready(payload, "model", task)
        rejected = _approve(draft, _review(draft, decision="reject"))
        self.assertEqual(rejected.status, "rejected", rejected.violations)
        messages = revision_request(task, draft, rejected)
        self.assertEqual(len(messages), 2)
        content = json.loads(messages[1]["content"])
        self.assertIn("rejected_review", content)
        self.assertEqual(content["checker_hash"], draft.checker_hash)
        # A rejection whose record is not a legal v2 rejection must not authorize it.
        tampered = replace(rejected, _review_json=_canonical({
            "review_contract_version": 2, "checker_hash": draft.checker_hash,
            "expected_table_sha256": rejected.review["expected_table_sha256"],
            "decision": "accept", "reason": "inconsistent record",
            "checked_requirements": ["anyedge"], "requirement_reviews": [],
            "claims": [], "state_phase_claims": [], "init_claims": [],
            "degenerate_outputs": [], "counterexamples": []}))
        with self.assertRaises(CheckerError):
            revision_request(task, draft, tampered)
        legacy = replace(rejected, _review_json=_canonical({
            "checker_hash": draft.checker_hash, "decision": "reject",
            "reason": "legacy record", "checked_requirements": ["anyedge"]}))
        with self.assertRaises(CheckerError):
            revision_request(task, draft, legacy)

    def test_revision_preflight_requires_a_real_change(self):
        task, payload = _anyedge_fixture()
        draft = _ready(payload, "model", task)
        rejected = _approve(draft, _review(draft, decision="reject"))
        unchanged = parse_checker_revision(
            json.dumps({"status": "ready", "checker": payload}), task, draft, rejected)
        self.assertEqual(unchanged.status, "invalid")
        self.assertIn("no substantive", unchanged.reason)
        revised_payload = json.loads(json.dumps(payload))
        revised_payload["outputs"]["anyedge"] = {"const": 0, "width": 1}
        revised = parse_checker_revision(
            json.dumps({"status": "ready", "checker": revised_payload}),
            task, draft, rejected)
        self.assertEqual(revised.status, "ready", revised.reason)
        self.assertEqual(revised.preflight["revision"]["parent_checker_hash"],
                         draft.checker_hash)

    def test_empty_trigger_census_flags_predicted_empty(self):
        task, payload = _properties_fixture()
        draft = _ready(payload, "properties", task)
        quiet = json.loads(json.dumps(draft.payload))
        for prop in quiet["properties"]:
            prop["trigger"] = {"const": 0, "width": 1}
        census = analyze_property_trigger_census(quiet)
        self.assertTrue(census["predicted_empty"])
        self.assertEqual(census["predicted_triggered"], 0)
        self.assertTrue(all(item["predicted_empty"] for item in census["properties"]))


if __name__ == "__main__":
    unittest.main()
