"""Offline discrimination for the independent checkers: correct case vs wrong behavior.

Each model scenario defines a correct expectation model and a mutant expectation model
(standing in for the observable post-edge values a wrong RTL would produce) and drives
the real comparison APIs with synthetic, complete TraceRuns. No RTL is compiled, no
simulator is invoked and no model is called: this proves the comparator and its case
design catch the specified case/step/signal/bit, while real-RTL replay lives in
tests/test_checker_sim_acceptance.py behind the Vivado guard.

The properties off-edge reset case documents a capability boundary: the frozen
properties evaluator keeps only clock-edge steps, so an asynchronous reset effect on a
non-edge step is invisible on that route. That assertion must be upgraded if off-edge
evaluation is ever implemented.
"""

import unittest

from agent.rtl.adaptive_check import (
    analyze_model_expectation_shape,
    analyze_property_trigger_census,
)
from agent.rtl.adaptive_execute import evaluate_model
from agent.rtl.observation import (
    TraceRun,
    _expected_events,
    sampling_hash,
    sampling_plan_from_suite,
    validate_trace,
)
from agent.rtl.properties import evaluate_properties, validate_properties
from agent.rtl.suite.evaluate import expected_traces
from agent.rtl.suite.schema import validate_suite
from agent.rtl.suite.testbench import compare_trace_rows


def requirement(identity, quote):
    return {"id": identity, "quote": quote}


def model_suite(ports, cases, requirements, *, clock=None, state=None, outputs=None,
                async_reset=None):
    value = {
        "schema_version": 1, "mode": "behavior", "ports": ports, "cases": cases,
        "requirements": requirements, "state": state or {}, "outputs": outputs or {},
    }
    if clock is not None:
        value["clock"] = clock
    if async_reset is not None:
        value["async_reset"] = async_reset
    return validate_suite(value)


def expected_outputs(suite):
    """{(case_id, step): {output: (bits, known)}} from the suite's own model."""
    table = {}
    for row in expected_traces(suite):
        table[(row["case_id"], row["step"])] = {
            name: (bits, row["expected_known"][name])
            for name, bits in row["expected_bits"].items()
        }
    return table


def observation_trace(plan, table):
    """Complete synthetic TraceRun: outputs from table, inputs exactly as planned."""
    ordered = sorted(
        _expected_events(plan).items(),
        key=lambda item: (item[0][0], item[0][1], item[0][2] != "pre"),
    )
    rows = []
    for (case_index, step, phase), metadata in ordered:
        case = plan["cases"][case_index]
        values = {}
        for name, port in plan["ports"].items():
            full = (1 << port["width"]) - 1
            if port["direction"] == "output":
                bits, known = (None, 0)
                if phase == "post":
                    bits, known = table.get((case["id"], step), {}).get(name, (None, 0))
                values[name] = {
                    "bits": (bits or 0) & full, "known": known & full, "width": port["width"],
                }
            elif plan["clock"] and name == plan["clock"]["port"]:
                edge = plan["clock"]["edge"]
                active = phase == "post" and (case["steps"][step]["edge"])
                bit = int(edge == "posedge") if active else int(edge != "posedge")
                values[name] = {"bits": bit, "known": 1, "width": 1}
            else:
                number = case["steps"][step]["inputs"][name] & full
                values[name] = {"bits": number, "known": full, "width": port["width"]}
        rows.append({**metadata, "values": values})
    trace = TraceRun(
        "complete", sampling_hash(plan), "0" * 64, "synthetic-observation",
        rows=rows, summary="synthetic observation from a described wrong behavior",
    )
    validate_trace(trace, plan)
    return trace


def comparison_rows(suite, table):
    """Legacy comparator input {(case_index, step): {output: (bits, known)}}."""
    outputs = [name for name, port in suite["ports"].items() if port["direction"] == "output"]
    rows = {}
    for case_index, case in enumerate(suite["cases"]):
        for step in range(len(case["steps"])):
            values = table[(case["id"], step)]
            rows[(case_index, step)] = {
                name: values.get(name, (0, 0)) for name in outputs
            }
    return rows


def assert_mismatch(testcase, run, scenario):
    first = run["first_mismatch"]
    testcase.assertIsNotNone(first, scenario["name"])
    testcase.assertEqual(
        (first["case_id"], first["step"], first["signal"]),
        (scenario["case_id"], scenario["step"], scenario["signal"]),
    )
    testcase.assertEqual(
        (first["expected_bits_value"], first["actual_bits_value"]),
        (scenario["expected"], scenario["actual"]),
    )
    differing = (first["expected_bits_value"] ^ first["actual_bits_value"]) & first["comparison_mask"]
    testcase.assertTrue(differing, "the reported comparison mask must contain a difference")
    testcase.assertEqual((differing >> scenario["bit"]) & 1, 1)


# --------------------------------------------------------------------- model fixtures
def sync_reset_scenario():
    # A synchronous reset changes q only at a clock edge; the mutant resets asynchronously.
    ports = {"clk": {"direction": "input", "width": 1},
             "reset": {"direction": "input", "width": 1},
             "q": {"direction": "output", "width": 4}}
    cases = [{"id": "reset_off_edge_must_hold", "requirements": ["R1", "R2"], "steps": [
        {"inputs": {"reset": 0}, "sample": False, "edge": True},
        {"inputs": {"reset": 1}, "sample": True, "edge": False},
        {"inputs": {"reset": 1}, "sample": True, "edge": True},
        {"inputs": {"reset": 1}, "sample": True, "edge": False},
    ]}]
    requirements = [requirement("R1", "synchronous reset clears q only at a clock edge"),
                    requirement("R2", "q holds when reset is asserted without a clock edge")]
    initial = {"value": 0, "signal": "q", "quote": "initial q = 0;"}
    state = {"model_q": {"width": 4, "initial": initial, "next": {"op": "ite", "width": 4, "args": [
        {"ref": "reset"}, {"const": 0, "width": 4},
        {"op": "add", "width": 4, "args": [{"ref": "model_q"}, {"const": 1, "width": 4}]}]}}}
    correct = model_suite(ports, cases, requirements,
                          clock={"port": "clk", "edge": "posedge"},
                          state=state, outputs={"q": {"ref": "model_q"}})
    mutant = model_suite(ports, cases, requirements,
                         clock={"port": "clk", "edge": "posedge"},
                         state=state, outputs={"q": {"ref": "model_q"}},
                         async_reset={"port": "reset", "active": 1,
                                      "values": {"model_q": {"const": 0, "width": 4}}})
    return {"name": "sync_reset", "correct": correct, "mutant": mutant,
            "case_id": "reset_off_edge_must_hold", "step": 1,
            "signal": "q", "bit": 0, "expected": 1, "actual": 0}


def async_reset_scenario():
    # An asynchronous reset clears q on the assertion step itself; the mutant waits for an edge.
    ports = {"clk": {"direction": "input", "width": 1},
             "reset": {"direction": "input", "width": 1},
             "q": {"direction": "output", "width": 4}}
    cases = [{"id": "async_clear_off_edge", "requirements": ["R1"], "steps": [
        {"inputs": {"reset": 0}, "sample": False, "edge": True},
        {"inputs": {"reset": 1}, "sample": True, "edge": False},
        {"inputs": {"reset": 0}, "sample": True, "edge": True},
    ]}]
    requirements = [requirement("R1", "asynchronous reset clears q immediately without a clock edge")]
    initial = {"value": 0, "signal": "q", "quote": "initial q = 0;"}
    state = {"model_q": {"width": 4, "initial": initial, "next": {"op": "add", "width": 4, "args": [
        {"ref": "model_q"}, {"const": 1, "width": 4}]}}}
    correct = model_suite(ports, cases, requirements,
                          clock={"port": "clk", "edge": "posedge"},
                          state=state, outputs={"q": {"ref": "model_q"}},
                          async_reset={"port": "reset", "active": 1,
                                       "values": {"model_q": {"const": 0, "width": 4}}})
    mutant = model_suite(ports, cases, requirements,
                         clock={"port": "clk", "edge": "posedge"},
                         state=state, outputs={"q": {"ref": "model_q"}})
    return {"name": "async_reset", "correct": correct, "mutant": mutant,
            "case_id": "async_clear_off_edge", "step": 1,
            "signal": "q", "bit": 0, "expected": 0, "actual": 1}


def shift_direction_scenario():
    ports = {"clk": {"direction": "input", "width": 1},
             "d": {"direction": "input", "width": 1},
             "q": {"direction": "output", "width": 4}}
    cases = [{"id": "shift_in_bit", "requirements": ["R1"], "steps": [
        {"inputs": {"d": 0}, "sample": False, "edge": True},
        {"inputs": {"d": 0}, "sample": False, "edge": True},
        {"inputs": {"d": 1}, "sample": False, "edge": True},
        {"inputs": {"d": 0}, "sample": True, "edge": True},
        {"inputs": {"d": 1}, "sample": True, "edge": True},
    ]}]
    requirements = [requirement("R1", "shift register shifts new bit d into the low end q[0]")]
    initial = {"value": 0, "signal": "q", "quote": "initial q = 0;"}
    correct_state = {"model_q": {"width": 4, "initial": initial, "next": {
        "op": "concat", "width": 4, "args": [
            {"op": "slice", "width": 3, "lsb": 0, "args": [{"ref": "model_q"}]},
            {"op": "slice", "width": 1, "lsb": 0, "args": [{"ref": "d"}]}]}}}
    mutant_state = {"model_q": {"width": 4, "initial": initial, "next": {
        "op": "concat", "width": 4, "args": [
            {"op": "slice", "width": 1, "lsb": 0, "args": [{"ref": "d"}]},
            {"op": "slice", "width": 3, "lsb": 1, "args": [{"ref": "model_q"}]}]}}}
    correct = model_suite(ports, cases, requirements,
                          clock={"port": "clk", "edge": "posedge"},
                          state=correct_state, outputs={"q": {"ref": "model_q"}})
    mutant = model_suite(ports, cases, requirements,
                         clock={"port": "clk", "edge": "posedge"},
                         state=mutant_state, outputs={"q": {"ref": "model_q"}})
    return {"name": "shift_direction", "correct": correct, "mutant": mutant,
            "case_id": "shift_in_bit", "step": 3,
            "signal": "q", "bit": 1, "expected": 2, "actual": 4}


def sign_fill_scenario():
    # Arithmetic right shift repeats the sign bit; the mutant shifts in zero.
    ports = {"clk": {"direction": "input", "width": 1},
             "q": {"direction": "output", "width": 4}}
    cases = [{"id": "sign_fill_boundary", "requirements": ["R1"], "steps": [
        {"inputs": {}, "sample": False, "edge": True},
        {"inputs": {}, "sample": False, "edge": True},
        {"inputs": {}, "sample": False, "edge": True},
        {"inputs": {}, "sample": True, "edge": True},
    ]}]
    requirements = [requirement("R1", "arithmetic right shift repeats the old sign bit")]
    initial = {"value": 8, "signal": "q", "quote": "initial q = 8;"}
    correct_state = {"model_q": {"width": 4, "initial": initial, "next": {
        "op": "concat", "width": 4, "args": [
            {"op": "slice", "width": 1, "lsb": 3, "args": [{"ref": "model_q"}]},
            {"op": "slice", "width": 3, "lsb": 1, "args": [{"ref": "model_q"}]}]}}}
    mutant_state = {"model_q": {"width": 4, "initial": initial, "next": {
        "op": "concat", "width": 4, "args": [
            {"const": 0, "width": 1},
            {"op": "slice", "width": 3, "lsb": 1, "args": [{"ref": "model_q"}]}]}}}
    correct = model_suite(ports, cases, requirements,
                          clock={"port": "clk", "edge": "posedge"},
                          state=correct_state, outputs={"q": {"ref": "model_q"}})
    mutant = model_suite(ports, cases, requirements,
                         clock={"port": "clk", "edge": "posedge"},
                         state=mutant_state, outputs={"q": {"ref": "model_q"}})
    return {"name": "boundary_fill", "correct": correct, "mutant": mutant,
            "case_id": "sign_fill_boundary", "step": 3,
            "signal": "q", "bit": 3, "expected": 15, "actual": 0}


def self_loop_scenario():
    ports = {"clk": {"direction": "input", "width": 1},
             "en": {"direction": "input", "width": 1},
             "q": {"direction": "output", "width": 4}}
    cases = [{"id": "hold_when_disabled", "requirements": ["R1"], "steps": [
        {"inputs": {"en": 1}, "sample": False, "edge": True},
        {"inputs": {"en": 0}, "sample": True, "edge": True},
        {"inputs": {"en": 0}, "sample": True, "edge": True},
        {"inputs": {"en": 1}, "sample": True, "edge": True},
    ]}]
    requirements = [requirement("R1", "counter holds its value while enable is low")]
    initial = {"value": 0, "signal": "q", "quote": "initial q = 0;"}
    correct_state = {"model_q": {"width": 4, "initial": initial, "next": {"op": "ite", "width": 4, "args": [
        {"ref": "en"},
        {"op": "add", "width": 4, "args": [{"ref": "model_q"}, {"const": 1, "width": 4}]},
        {"ref": "model_q"}]}}}
    mutant_state = {"model_q": {"width": 4, "initial": initial, "next": {"op": "add", "width": 4, "args": [
        {"ref": "model_q"}, {"const": 1, "width": 4}]}}}
    correct = model_suite(ports, cases, requirements,
                          clock={"port": "clk", "edge": "posedge"},
                          state=correct_state, outputs={"q": {"ref": "model_q"}})
    mutant = model_suite(ports, cases, requirements,
                         clock={"port": "clk", "edge": "posedge"},
                         state=mutant_state, outputs={"q": {"ref": "model_q"}})
    return {"name": "self_loop_hold", "correct": correct, "mutant": mutant,
            "case_id": "hold_when_disabled", "step": 1,
            "signal": "q", "bit": 0, "expected": 1, "actual": 2}


def unrelated_output_scenario():
    ports = {"a": {"direction": "input", "width": 1},
             "b": {"direction": "input", "width": 1},
             "c": {"direction": "input", "width": 1},
             "d": {"direction": "input", "width": 1},
             "o1": {"direction": "output", "width": 1},
             "o2": {"direction": "output", "width": 1}}
    cases = [
        {"id": "o2_case", "requirements": ["R2"], "steps": [
            {"inputs": {"a": 1, "b": 0, "c": 1, "d": 0}, "sample": True, "edge": False},
            {"inputs": {"a": 0, "b": 1, "c": 0, "d": 1}, "sample": True, "edge": False}]},
        {"id": "o1_case", "requirements": ["R1"], "steps": [
            {"inputs": {"a": 1, "b": 1, "c": 0, "d": 1}, "sample": True, "edge": False},
            {"inputs": {"a": 0, "b": 1, "c": 1, "d": 0}, "sample": True, "edge": False}]},
    ]
    requirements = [requirement("R1", "o1 is a AND b"), requirement("R2", "o2 is c XOR d")]
    outputs = {
        "o1": {"op": "and", "width": 1, "args": [{"ref": "a"}, {"ref": "b"}]},
        "o2": {"op": "xor", "width": 1, "args": [{"ref": "c"}, {"ref": "d"}]},
    }
    mutant_outputs = {
        "o1": {"op": "and", "width": 1, "args": [{"ref": "a"}, {"ref": "b"}]},
        "o2": {"op": "and", "width": 1, "args": [{"ref": "a"}, {"ref": "c"}]},
    }
    correct = model_suite(ports, cases, requirements, outputs=outputs)
    mutant = model_suite(ports, cases, requirements, outputs=mutant_outputs)
    return {"name": "unrelated_output", "correct": correct, "mutant": mutant,
            "case_id": "o2_case", "step": 1,
            "signal": "o2", "bit": 0, "expected": 1, "actual": 0}


def model_scenarios():
    return [
        sync_reset_scenario(), async_reset_scenario(), shift_direction_scenario(),
        sign_fill_scenario(), self_loop_scenario(), unrelated_output_scenario(),
    ]


# --------------------------------------------------------------------- properties fixtures
def property_payload(ports, clock, cases, requirements, properties):
    return {
        "schema_version": 1,
        "sampling": {"schema_version": 1, "ports": ports, "clock": clock, "cases": cases},
        "requirements": requirements,
        "properties": properties,
    }


def property_trace(plan, output_values):
    """Complete synthetic TraceRun for a single-output properties plan."""
    ordered = sorted(
        _expected_events(plan).items(),
        key=lambda item: (item[0][0], item[0][1], item[0][2] != "pre"),
    )
    rows = []
    for (case_index, step, phase), metadata in ordered:
        case = plan["cases"][case_index]
        values = {}
        for name, port in plan["ports"].items():
            full = (1 << port["width"]) - 1
            if port["direction"] == "output":
                if phase == "post":
                    bits, known = output_values[step], full
                elif step > 0:
                    bits, known = output_values[step - 1], full
                else:
                    bits, known = 0, 0
                values[name] = {"bits": bits & full, "known": known & full,
                                "width": port["width"]}
            elif plan["clock"] and name == plan["clock"]["port"]:
                edge = plan["clock"]["edge"]
                active = phase == "post" and case["steps"][step]["edge"]
                bit = int(edge == "posedge") if active else int(edge != "posedge")
                values[name] = {"bits": bit, "known": 1, "width": 1}
            else:
                number = case["steps"][step]["inputs"][name] & full
                values[name] = {"bits": number, "known": full, "width": port["width"]}
        rows.append({**metadata, "values": values})
    trace = TraceRun(
        "complete", sampling_hash(plan), "0" * 64, "synthetic-properties",
        rows=rows, summary="synthetic observation from a described wrong behavior",
    )
    validate_trace(trace, plan)
    return trace


def shift_properties_suite():
    ports = {"clk": {"direction": "input", "width": 1},
             "load": {"direction": "input", "width": 1},
             "d": {"direction": "input", "width": 1},
             "q": {"direction": "output", "width": 4}}
    cases = [{"id": "shift_in_path", "requirements": ["R1"], "steps": [
        {"inputs": {"load": 1, "d": 0}, "sample": False, "edge": True},
        {"inputs": {"load": 1, "d": 1}, "sample": False, "edge": True},
        {"inputs": {"load": 0, "d": 1}, "sample": True, "edge": True},
        {"inputs": {"load": 0, "d": 0}, "sample": True, "edge": True},
    ]}]
    requirements = [requirement("R1", "when load is low, d shifts into the low end of q")]
    properties = [{
        "id": "p_shift_left", "requirements": ["R1"], "sample_phase": "post",
        "warmup_ticks": 0, "window": {"min": 0, "max": 0},
        "trigger": {"op": "eq", "width": 1, "args": [
            {"signal": "load", "phase": "pre", "past": 0, "anchor": False},
            {"const": 0, "width": 1}]},
        "assertion": {"op": "eq", "width": 1, "args": [
            {"op": "concat", "width": 4, "args": [
                {"op": "slice", "width": 3, "lsb": 0, "args": [
                    {"signal": "q", "phase": "pre", "past": 0, "anchor": False}]},
                {"signal": "d", "phase": "pre", "past": 0, "anchor": False}]},
            {"signal": "q", "phase": "post", "past": 0, "anchor": False}]},
        "abort": None, "abort_requirements": [],
    }]
    return validate_properties(property_payload(
        ports, {"port": "clk", "edge": "posedge"}, cases, requirements, properties))


def off_edge_properties_suite():
    ports = {"clk": {"direction": "input", "width": 1},
             "reset": {"direction": "input", "width": 1},
             "q": {"direction": "output", "width": 4}}
    cases = [{"id": "async_clear", "requirements": ["R1"], "steps": [
        {"inputs": {"reset": 0}, "sample": False, "edge": True},
        {"inputs": {"reset": 1}, "sample": True, "edge": False},
        {"inputs": {"reset": 1}, "sample": True, "edge": True},
        {"inputs": {"reset": 0}, "sample": True, "edge": True},
    ]}]
    requirements = [requirement("R1", "asynchronous reset clears q without a clock edge")]
    properties = [{
        "id": "p_async_clear", "requirements": ["R1"], "sample_phase": "post",
        "warmup_ticks": 0, "window": {"min": 0, "max": 0},
        "trigger": {"op": "eq", "width": 1, "args": [
            {"signal": "reset", "phase": "post", "past": 0, "anchor": False},
            {"const": 1, "width": 1}]},
        "assertion": {"op": "eq", "width": 1, "args": [
            {"signal": "q", "phase": "post", "past": 0, "anchor": False},
            {"const": 0, "width": 4}]},
        "abort": None, "abort_requirements": [],
    }]
    return validate_properties(property_payload(
        ports, {"port": "clk", "edge": "posedge"}, cases, requirements, properties))


# --------------------------------------------------------------------- empty-check fixtures
def vacuous_model_suite():
    """Every sampled expectation is 0 although the requirement text asks for 1."""
    ports = {"clk": {"direction": "input", "width": 1},
             "in": {"direction": "input", "width": 1},
             "pulse": {"direction": "output", "width": 1}}
    cases = [{"id": "vacuous", "requirements": ["R1"], "steps": [
        {"inputs": {"in": 0}, "sample": False, "edge": True},
        {"inputs": {"in": 1}, "sample": True, "edge": True},
        {"inputs": {"in": 0}, "sample": True, "edge": True},
    ]}]
    requirements = [requirement("R1", "output pulse must be set to 1 after a rising input edge")]
    return model_suite(
        ports, cases, requirements, clock={"port": "clk", "edge": "posedge"},
        state={"model_prev": {"width": 1, "next": {"ref": "in"}}},
        outputs={"pulse": {"op": "xor", "width": 1, "args": [
            {"ref": "in"}, {"ref": "model_prev"}]}})


def never_trigger_properties_suite():
    ports = {"a": {"direction": "input", "width": 1},
             "y": {"direction": "output", "width": 1}}
    sampling = {"schema_version": 1, "ports": ports, "clock": None, "cases": [
        {"id": "all", "requirements": ["r1"], "steps": [
            {"inputs": {"a": 0}, "sample": True, "edge": False},
            {"inputs": {"a": 1}, "sample": True, "edge": False}]}]}
    properties = [{
        "id": "never",
        "requirements": ["r1"],
        "sample_phase": "post",
        "warmup_ticks": 0,
        "window": {"min": 0, "max": 0},
        "trigger": {"const": 0, "width": 1},
        "assertion": {"op": "eq", "width": 1, "args": [
            {"signal": "y", "phase": "post", "past": 0, "anchor": False},
            {"op": "bitnot", "width": 1, "signed": False, "args": [
                {"signal": "a", "phase": "post", "past": 0, "anchor": False}]}]},
        "abort": None,
        "abort_requirements": [],
    }]
    return validate_properties({
        "schema_version": 1, "sampling": sampling,
        "requirements": [requirement("r1", "y is the bitwise complement of a.")],
        "properties": properties,
    })


class ModelRouteDiscriminationTests(unittest.TestCase):
    def assert_discriminates(self, scenario):
        correct, mutant = scenario["correct"], scenario["mutant"]
        plan = sampling_plan_from_suite(correct)
        correct_trace = observation_trace(plan, expected_outputs(correct))
        mutant_trace = observation_trace(plan, expected_outputs(mutant))

        passed = evaluate_model(correct, correct_trace)
        self.assertEqual(passed["failed_cases"], [], scenario["name"])
        self.assertGreater(passed["compared_bits"], 0, scenario["name"])

        failed = evaluate_model(correct, mutant_trace)
        self.assertIn(scenario["case_id"], failed["failed_cases"], scenario["name"])
        assert_mismatch(self, failed, scenario)

        rows_passed = compare_trace_rows(comparison_rows(correct, expected_outputs(correct)), correct)
        self.assertEqual(rows_passed["failed_cases"], [], scenario["name"])
        self.assertGreater(rows_passed["compared_bits"], 0, scenario["name"])
        rows_failed = compare_trace_rows(comparison_rows(correct, expected_outputs(mutant)), correct)
        self.assertIn(scenario["case_id"], rows_failed["failed_cases"], scenario["name"])
        assert_mismatch(self, rows_failed, scenario)

    def test_sync_reset_must_hold_off_edge(self):
        self.assert_discriminates(sync_reset_scenario())

    def test_async_reset_clears_at_assertion_without_edge(self):
        self.assert_discriminates(async_reset_scenario())

    def test_shift_direction_catches_high_end_insertion(self):
        self.assert_discriminates(shift_direction_scenario())

    def test_sign_fill_boundary_catches_logical_shift(self):
        self.assert_discriminates(sign_fill_scenario())

    def test_self_loop_catches_missing_hold(self):
        self.assert_discriminates(self_loop_scenario())

    def test_unrelated_output_is_still_compared(self):
        self.assert_discriminates(unrelated_output_scenario())


class PropertiesRouteDiscriminationTests(unittest.TestCase):
    def test_shift_direction_is_caught_by_local_relation(self):
        suite = shift_properties_suite()
        plan = suite["sampling"]
        correct_q = [0, 1, 3, 6]      # load 0,1 then left shifts: 0011 -> 0110
        mutant_q = [0, 1, 8, 4]       # right shifts: 1000 -> 0100
        passed = evaluate_properties(suite, property_trace(plan, correct_q))
        self.assertEqual(passed["status"], "passed")
        self.assertEqual(passed["failed_properties"], [])
        self.assertGreater(passed["counts"]["satisfied"], 0)
        failed = evaluate_properties(suite, property_trace(plan, mutant_q))
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["failed_properties"], ["p_shift_left"])
        self.assertGreater(failed["counts"]["violated"], 0)
        counterexample = failed["first_counterexample"]
        self.assertEqual(counterexample["property_id"], "p_shift_left")
        self.assertEqual(counterexample["case_id"], "shift_in_path")
        self.assertEqual(counterexample["trigger_step"], 2)

    def test_off_edge_reset_is_an_explicit_capability_boundary(self):
        # Documented boundary: the properties evaluator keeps only clock-edge steps,
        # so an asynchronous reset effect on the non-edge step is never observed.
        # If off-edge evaluation is implemented, the mutant below must start failing.
        suite = off_edge_properties_suite()
        plan = suite["sampling"]
        correct_q = [1, 0, 0, 1]   # async: q cleared at the off-edge reset step
        mutant_q = [1, 1, 0, 1]    # sync: q keeps its value until the next edge
        self.assertNotEqual(correct_q[1], mutant_q[1])
        passed = evaluate_properties(suite, property_trace(plan, correct_q))
        failed = evaluate_properties(suite, property_trace(plan, mutant_q))
        self.assertEqual(passed["status"], "passed")
        self.assertEqual(failed["status"], "passed")
        self.assertEqual(failed["failed_properties"], [])
        # The off-edge reset assertion produces no trigger/response for either trace.
        self.assertEqual(passed["counts"], failed["counts"])
        self.assertEqual(passed["counts"]["triggered"], 1)
        self.assertEqual(passed["counts"]["violated"], 0)
        self.assertEqual(passed["counts"]["satisfied"], 1)


class EmptyCheckWarningTests(unittest.TestCase):
    def test_all_zero_expectations_are_flagged_as_zero_change(self):
        shape = analyze_model_expectation_shape(vacuous_model_suite())
        self.assertEqual(shape["kind"], "model_expectation_shape")
        self.assertTrue(shape["zero_change"])
        self.assertEqual(shape["expected_ones"], 0)
        self.assertGreater(shape["comparable_bits"], 0)
        rows = {row["requirement_id"]: row for row in shape["requirements"]}
        self.assertTrue(rows["R1"]["zero_change"])
        self.assertGreater(rows["R1"]["comparable_bits"], 0)
        self.assertTrue(rows["R1"]["quote_mentions_one"])
        self.assertTrue(shape["outputs"]["pulse"]["bit_never_one"])

    def test_unreachable_trigger_is_flagged_as_empty(self):
        census = analyze_property_trigger_census(never_trigger_properties_suite())
        self.assertEqual(census["kind"], "property_trigger_census")
        self.assertTrue(census["predicted_empty"])
        self.assertEqual(census["predicted_triggered"], 0)
        self.assertEqual(census["unknown"], 0)
        row = census["properties"][0]
        self.assertEqual(row["property_id"], "never")
        self.assertTrue(row["predicted_empty"])
        self.assertEqual(row["predicted_triggered"], 0)


if __name__ == "__main__":
    unittest.main()
