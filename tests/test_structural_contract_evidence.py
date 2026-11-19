"""Public interface authority and source-bound Vivado diagnostics."""

from types import SimpleNamespace

from agent.domain.rtl.interface import check_interface, check_interface_result
from agent.domain.rtl.task import TaskSpec
from agent.domain.rtl.vivado import classify_tool_failure, synthesis_hints


HEADER = "module Latch(input a, input b, output y);"
PROMPT = "Implement a module named Latch.\nDesign signature:\n" + HEADER


def compare(header, prompt=PROMPT, interface=""):
    return check_interface_result(header + "\nendmodule", interface, prompt, top="Latch")


def test_header_order_and_width_are_checked_for_both_explicit_sources():
    swapped = "module Latch(input b, input a, output y);"
    wide = "module Latch(input [1:0] a, input b, output y);"
    for prompt, interface, source in ((PROMPT, "", "prompt_signature"), ("", HEADER, "interface_file")):
        assert compare(HEADER, prompt, interface).status == "ok"
        for header, kind in ((swapped, "port_order"), (wide, "width")):
            result = compare(header, prompt, interface)
            assert result.expected.source == source
            assert result.status == "mismatch" and result.blocking
            assert [item.kind for item in result.differences] == [kind]
    task = TaskSpec.from_text("mux", PROMPT)
    check = check_interface(SimpleNamespace(task=task), SimpleNamespace(code=wide + " endmodule"))
    assert (check.status, check.failure_kind, check.blocking) == ("failed", "code", True)


def test_prose_order_is_advisory_and_does_not_override_a_named_header():
    prose = "Implement a module named Latch.\n- input b\n- output y\n- input a"
    assert compare(HEADER, prose).status == "ok"
    wider = "module Latch(input [1:0] a, input b, output y);"
    assert compare(wider, prose).status == "advisory"
    both = prose + "\nModule signature:\n" + HEADER
    assert compare(HEADER, both).status == "ok"
    assert compare("module Latch(input b, output y, input a);", both).blocking
    conflict = both.replace("- input a", "- input [2:0] a")
    result = compare(HEADER, conflict)
    assert result.status == "advisory" and not result.expected.authoritative


def test_parameters_use_their_default_values_and_unknown_widths_are_unverified():
    prompt = "Module signature:\nmodule Latch #(parameter W=3)(input [W-1:0] a, output y);"
    candidate = "module Latch #(parameter N=2+1)(input [N-1:0] a, output y);"
    assert compare(candidate, prompt).status == "ok"
    assert compare(candidate.replace("2+1", "2+2"), prompt).blocking
    for declaration in ("input [OTHER-1:0] a", "input bus_t a", "input [1:0][1:0] a"):
        result = compare(f"module Latch({declaration}, output y);", prompt)
        assert result.status == "advisory" and not result.blocking
    incomplete = "Module signature:\nmodule Latch(input [UNDEFINED:0] a, output y);"
    result = compare(candidate, incomplete)
    assert result.status == "advisory" and not result.expected.authoritative
    unknown_width = "module Latch(input [OTHER-1:0] a, output y);"
    result = compare(candidate, "", unknown_width)
    assert result.status == "advisory" and not result.blocking


def test_explicitly_empty_header_has_no_ports():
    prompt = "Module signature:\nmodule Latch();"
    assert compare("module Latch();", prompt).status == "ok"
    assert compare(HEADER, prompt).blocking


def test_non_ansi_header_uses_header_positions_and_default_parameter_widths():
    prompt = "Module signature:\nmodule Latch(input [2:0] a, input b, output y);"
    original = "module Latch #(parameter N=3)(a,b,y); output y; input b; input [N-1:0] a;"
    assert compare(original, prompt).status == "ok"
    assert [d.kind for d in compare(original.replace("(a,b,y)", "(b,a,y)"), prompt).differences] == ["port_order"]


def test_conflicting_signatures_and_labelled_examples_cannot_create_required_ports():
    result = compare(HEADER, PROMPT + "\nModule signature:\n" + HEADER)
    assert not result.expected.authoritative and not result.blocking
    example = "## Example\n### Design signature:\n" + HEADER
    result = compare("module Latch(input z, output q);", example)
    assert not result.expected.authoritative and not result.blocking
    required = example + "\n## Design signature:\nmodule Latch(input z, output q);"
    assert compare("module Latch(input z, output q);", required).expected.authoritative


def test_only_primary_declaration_order_errors_at_the_actual_file_are_code(tmp_path):
    candidate = tmp_path / "solution.sv"
    def diagnostic(path, severity="ERROR"):
        return f"{severity}: [VRFC 10-3380] identifier 'stage' is used before its declaration [{path}:12]"

    assert classify_tool_failure(diagnostic(candidate), candidate_path=candidate) == "code"
    assert classify_tool_failure(diagnostic("solution.sv"), candidate_path=candidate) == "code"
    for log in (
        diagnostic(tmp_path.parent / "another" / "solution.sv"), diagnostic("driver.sv"),
        diagnostic(candidate, "WARNING"), diagnostic(candidate).replace("used before its declaration", "ignored"),
        "ERROR: [VRFC 10-8530] module 'Latch' is ignored due to previous errors [solution.sv:1]",
    ):
        assert classify_tool_failure(log, candidate_path=candidate) == "unknown"
    assert classify_tool_failure(diagnostic(candidate)) == "unknown"
    assert classify_tool_failure("no space left\n" + diagnostic(candidate), candidate_path=candidate) == "environment"


def test_synthesis_hints_keep_only_bounded_source_warnings(tmp_path):
    candidate = tmp_path / "solution.sv"
    truncation = f"WARNING: [Synth 8-10929] literal value 'd4 truncated to fit in 2 bits [{candidate}:4]"
    unreachable = "WARNING: [Synth 8-151] case item 2'b00 is unreachable [solution.sv:8:1]"
    noise = "\n".join(f"WARNING: [Synth 8-7129] unused port p{i} [solution.sv:1]" for i in range(80))
    log = "\n".join((noise, truncation, truncation, unreachable, unreachable.replace("solution.sv", "driver.sv"),
                     truncation.replace("WARNING", "INFO"), unreachable.replace("is unreachable", "optimized")))
    hints = synthesis_hints(log, candidate)
    assert [(h["code"], h["source_line"]) for h in hints] == [("SYNTH 8-10929", 4), ("SYNTH 8-151", 8)]
    assert classify_tool_failure(log, candidate_path=candidate) == "unknown"
    repeated = "\n".join(unreachable.replace(":8:", f":{i}:") for i in range(1, 21))
    assert len(synthesis_hints(repeated, candidate)) == 8


def test_explicit_interface_intro_sentence_is_authoritative_outside_examples():
    counter_prompt = (
        "Design a 3-bit saturating up-counter with parallel load. "
        "Implement exactly this interface.\n\n"
        "module TopModule(input wire clk, input wire reset, input wire load, "
        "input wire step, input wire [2:0] d, output reg [2:0] q);"
    )
    xor_prompt = (
        "Design a two-input XOR gate. Implement this Verilog interface.\n\n"
        "module TopModule(input wire a, input wire b, output wire q);"
    )
    for prompt, expected_names in (
        (counter_prompt, ["clk", "reset", "load", "step", "d", "q"]),
        (xor_prompt, ["a", "b", "q"]),
    ):
        task = TaskSpec.from_text("t", prompt)
        assert task.expected_interface.complete
        assert task.expected_interface.authoritative
        assert task.expected_interface.source == "prompt_signature"
        assert [p.name for p in task.expected_interface.ports] == expected_names

    # Negative case: example / buggy section must still be rejected.
    buggy = (
        "Fix the counter.\n\nBuggy example:\nImplement exactly this interface.\n\n"
        "module TopModule(input clk, output q);"
    )
    assert not TaskSpec.from_text("buggy", buggy).expected_interface.authoritative

    # Negative case: embedded module without explicit interface intro remains non-authoritative.
    unintroduced = "Consider the helper below.\n\nmodule TopModule(input a, output y);"
    assert not TaskSpec.from_text("plain", unintroduced).expected_interface.authoritative
