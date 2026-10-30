"""Public-only checker mechanics and clock interpretation regressions."""

import json
from types import SimpleNamespace

import pytest

from agent.domain.rtl.guided_adjudicate import adjudicate_request
from agent.domain.rtl.guided_checker import CheckerError, checker_contract, checker_request, parse_checker
from agent.domain.rtl.observation import build_observation_testbench
from agent.domain.rtl.task import TaskSpec


def task(semantics="On each positive clock edge, reset_n low clears q; otherwise q takes d."):
    return TaskSpec.from_text(
        "context",
        "Implement a module named TopModule with the following interface.\n"
        " - input clk\n - input reset_n\n - input d (8 bits)\n - output q (8 bits)\n"
        + semantics,
    )


TABLE = "case c\ninit reset_n=0 d=00 q=00\nstep reset_n=1 d=a5 q=a5"


@pytest.mark.parametrize("cycles", [1, 2, 3])
def test_contract_matches_init_expansion_and_prompt(cycles):
    public = task()
    contract = checker_contract(public, max_cases=2, max_steps=3, init_cycles=cycles)
    assert contract["supported"] is True
    assert contract["execution"]["init_repeats"] == cycles
    assert contract["limits"]["max_cases"] == 2
    assert contract["limits"]["max_table_lines_per_case"] == 3
    checker = parse_checker(TABLE, public, max_cases=2, max_steps=3, init_cycles=cycles)
    assert len(checker.plan["cases"][0]["steps"]) == cycles + 1
    assert sorted(checker.cases[0].expected) == [cycles - 1, cycles]
    messages = checker_request(public, "checker skill", max_cases=2, max_steps=3, init_cycles=cycles)
    assert json.dumps(contract, ensure_ascii=False, separators=(",", ":")) in messages[1]["content"]
    assert "zero-based" in contract["execution"]["failure_step_index"].lower()
    tb = build_observation_testbench(checker.plan, "TopModule", "a" * 16)
    assert tb.count("rtla_c0_clk <= 1'b1;") == cycles + 1
    assert "#1;\nrtla_c0_clk <= 1'b1;\n#1;" in tb


@pytest.mark.parametrize("semantics", [
    "always @(posedge clk or negedge reset_n) q follows the specified reset and data.",
    "On the rising edge of clk, q takes d; the falling edge of reset_n clears q asynchronously.",
    "On each positive clock edge, q takes d. On reset_n's negative edge, clear q.",
    "clk's rising edge captures d. reset_n falling edge clears q asynchronously.",
    "Use a positive-edge-triggered clock and an active-low asynchronous reset_n.",
])
def test_explicit_positive_clock_with_async_reset_supported(semantics):
    public = task(semantics)
    assert checker_contract(public)["supported"] is True
    assert parse_checker(TABLE, public).plan["clock"]["edge"] == "posedge"


@pytest.mark.parametrize("semantics", [
    "always @(negedge clk or negedge reset_n) q follows d.",
    "On the falling edge of clk, q takes d; reset_n clears q asynchronously.",
    "On the negative edge of the clock, q takes d.",
    "clk's falling edge captures d; reset_n falling edge clears q.",
    "The positive edge of reset_n releases reset; the falling edge of clk captures d.",
    "Use posedge clk or negedge reset_n for reset, and also update q on negedge clk.",
    "On each negative clock edge q takes d.",
    "Use posedge clk for q and falling edges of clk for another update.",
])
def test_actual_negative_clock_rejected_without_reset_clause_bypass(semantics):
    public = task(semantics)
    contract = checker_contract(public)
    assert contract["supported"] is False
    assert "falling-edge" in contract["reason"]
    with pytest.raises(CheckerError, match="falling-edge"):
        parse_checker(TABLE, public)


@pytest.mark.parametrize("semantics", [
    "q takes d when clocked; reset_n low clears q.",
    "The clock edge updates q, and negedge reset_n clears q.",
    "On the falling edge, reset q; on posedge clk, update q.",
    "On rising edge of an unspecified signal, q takes d.",
    "On posedge clk q takes d; an unspecified falling edge clears q.",
])
def test_ambiguous_edge_does_not_default_to_positive(semantics):
    public = task(semantics)
    assert checker_contract(public)["supported"] is False
    with pytest.raises(CheckerError):
        parse_checker(TABLE, public)


def test_effective_limits_and_parser_agree():
    public = task()
    limits = checker_contract(public, max_cases=99, max_steps=99)["limits"]
    assert limits["max_cases"] == 8
    assert limits["max_table_lines_per_case"] == 32
    assert limits["max_expanded_events_per_case"] == 32
    assert limits["max_total_expanded_events"] == 256
    with pytest.raises(CheckerError, match="step limit"):
        parse_checker(TABLE, public, max_steps=1)
    with pytest.raises(CheckerError, match="case count"):
        parse_checker(TABLE + "\n" + TABLE.replace("case c", "case d"), public, max_cases=1)
    for options in ({"init_cycles": 0}, {"init_cycles": 33}, {"max_cases": False}):
        assert checker_contract(public, **options)["supported"] is False
        with pytest.raises(CheckerError):
            parse_checker(TABLE, public, **options)


def test_public_only_request_and_adjudication_receive_distinct_contexts():
    public = task()
    contract = checker_contract(public, init_cycles=3)
    checker = parse_checker(TABLE, public, init_cycles=3)
    execution = {"contract": contract, "sampling_plan": checker.plan}
    candidate = SimpleNamespace(code="candidate_private_marker")
    failures = [{"step": 3, "actual": "observed_private_marker"}]
    before = checker_request(public, "skill")
    diagnostic = adjudicate_request(public, candidate, TABLE, failures, execution=execution)
    after = checker_request(public, "skill")
    assert before == after
    assert "candidate_private_marker" not in json.dumps(before)
    assert "observed_private_marker" not in json.dumps(before)
    assert "candidate_private_marker" not in json.dumps(contract)
    assert json.dumps(execution, ensure_ascii=False, separators=(",", ":")) in diagnostic[1]["content"]
    assert "candidate_private_marker" in diagnostic[1]["content"]
    assert "observed_private_marker" in diagnostic[1]["content"]


def test_combinational_contract_does_not_repeat_init():
    public = TaskSpec.from_text("comb", "Implement a module named TopModule with the following interface.\n - input d (8 bits)\n - output q (8 bits)\nq equals d.")
    contract = checker_contract(public, init_cycles=3)
    assert contract["supported"] is True
    assert contract["clock"] is None
    assert contract["execution"]["init_repeats"] == 1
    checker = parse_checker("case c\ninit d=a5 q=a5", public, init_cycles=3)
    assert len(checker.plan["cases"][0]["steps"]) == 1


def test_numeric_validation_remains_strict():
    public = task()
    for invalid in ("xx", "0xa5", "1ff", "-1"):
        with pytest.raises(CheckerError):
            parse_checker(TABLE.replace("q=a5", "q=" + invalid), public)


def test_nonclock_edge_does_not_become_a_combinational_checker():
    public = TaskSpec.from_text(
        "no-clock", "Implement a module named TopModule with the following interface.\n"
        " - input event\n - output q\nOn posedge event, toggle q.",
    )
    assert checker_contract(public)["supported"] is False
    with pytest.raises(CheckerError, match="no supported clock"):
        parse_checker("case c\nstep event=1 q=1", public)


@pytest.mark.parametrize("port_count", [64, 65])
def test_public_port_limit_matches_sampling_schema(port_count):
    public = TaskSpec.from_text(
        "many-ports", "Implement a module named TopModule with the following interface.\n"
        + "".join(f" - input d{index}\n" for index in range(port_count - 1))
        + " - output q\nq equals d0.",
    )
    assert public.expected_interface.complete
    assert len(public.expected_interface.ports) == port_count
    table = "case c\nstep " + " ".join(f"d{index}=0" for index in range(port_count - 1)) + " q=0"
    contract = checker_contract(public)
    if port_count == 64:
        assert contract["supported"] is True
        assert contract["limits"]["max_ports"] == 64
        assert len(parse_checker(table, public).plan["ports"]) == 64
    else:
        assert contract["supported"] is False
        assert "port count" in contract["reason"]
        with pytest.raises(CheckerError, match="port count"):
            parse_checker(table, public)
