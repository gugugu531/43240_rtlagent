"""Public key-case timing, four-state comparisons and document boundaries."""

import pytest

from agent.domain.rtl.guided_checker import (
    CheckerError, checker_contract, checker_request, evaluate_checker, parse_checker,
)
from agent.domain.rtl.observation import parse_observations, sampling_hash
from agent.domain.rtl.task import TaskSpec
from agent.orchestration.nodes.guided import _checker_fingerprint


CLOCKED = "module TopModule(input clk, input reset, input d, output q); endmodule"
COMB = "module TopModule(input d, output [1:0] q); endmodule"
CAPTURE = "Capture d on posedge clk. "
RESET_TABLE = """case reset_again
init reset=1 d=0 q=0
step reset=0 d=1 pre.q=0 q=1
init reset=1 d=1 q=0"""
TOP_DOC = "<!-- Public specification: top.md -->\n"
DEP_DOC = "<!-- Public specification: dependency.md -->\n"
ADAPT = "## Single-file Vivado evaluation adaptation\n"


def trace_for(checker, output_pairs):
    """Encode one case's independently supplied (pre, post) q samples."""
    plan = checker.plan
    marker = "a" * 16
    clock = plan["clock"]["port"] if plan["clock"] else None
    lines = []
    steps = plan["cases"][0]["steps"]
    assert len(steps) == len(output_pairs)
    for index, (step, pair) in enumerate(zip(steps, output_pairs)):
        for post, (phase, q) in enumerate(zip(("pre", "post"), pair)):
            fields = [f"RTLA_OBS_{marker}", "0", str(index), str(index + post), phase]
            for name, port in sorted(plan["ports"].items()):
                if name == "q":
                    bits = q
                else:
                    value = post if name == clock else step["inputs"][name]
                    bits = format(value, f"0{port['width']}b")
                fields.append("b:" + bits)
            lines.append("|".join(fields))
    lines.append(f"RTLA_OBS_DONE_{marker}")
    return parse_observations("\n".join(lines), plan, marker,
                              candidate_hash="b" * 64, execution_id="synthetic")


@pytest.mark.parametrize("mode,pre", [("asynchronous", 0), ("synchronous", 1)])
def test_repeated_reset_discriminates_only_when_pre_is_selected(mode, pre):
    task = TaskSpec.from_text("register", CAPTURE + f"Active high reset is {mode}.", CLOCKED)
    checker = parse_checker(RESET_TABLE + f" pre.q={pre}", task, init_cycles=2)
    async_samples = [("0", "0"), ("0", "0"), ("0", "1"), ("0", "0"), ("0", "0")]
    sync_samples = [("x", "0"), ("0", "0"), ("0", "1"), ("1", "0"), ("0", "0")]
    good, bad = (async_samples, sync_samples) if pre == 0 else (sync_samples, async_samples)
    assert list(checker.cases[0].expectations()) == [
        (1, "post", {"q": 0}), (2, "pre", {"q": 0}), (2, "post", {"q": 1}),
        (3, "pre", {"q": pre}), (4, "post", {"q": 0}),
    ]
    passed = evaluate_checker(checker, trace_for(checker, good))
    assert passed["status"] == "passed"
    assert passed["compared_bits_by_phase"] == {"pre": 2, "post": 3}
    failed = evaluate_checker(checker, trace_for(checker, bad))
    assert failed["status"] == "failed"
    assert [(f["step"], f["phase"], f["signal"]) for f in failed["failed"]] == [(3, "pre", "q")]

    old = parse_checker(RESET_TABLE.replace(" pre.q=0", ""), task, init_cycles=2)
    assert old.plan == checker.plan
    assert _checker_fingerprint(old) != _checker_fingerprint(checker)
    for samples in (good, bad):
        result = evaluate_checker(old, trace_for(old, samples))
        assert result["status"] == "passed"
        assert result["compared_bits_by_phase"] == {"pre": 0, "post": 3}
        assert result["unknown_bits"] == 0


def test_phase_and_expected_value_both_change_checker_identity():
    task = TaskSpec.from_text("register", CAPTURE, CLOCKED)
    table = "case first\ninit reset=1 d=0 "
    pre = parse_checker(table + "pre.q=0", task, init_cycles=3)
    assert pre.cases[0].expected == {}
    assert pre.cases[0].public_dict()["pre_expected"] == {"0": {"q": 0}}
    post = parse_checker(table + "q=0", task, init_cycles=3)
    other = parse_checker(table + "pre.q=1", task, init_cycles=3)
    assert pre.plan == post.plan == other.plan
    assert len({_checker_fingerprint(c) for c in (pre, other, post)}) == 3
    result = evaluate_checker(pre, trace_for(pre, [("0", "x"), ("x", "x"), ("x", "x")]))
    assert result["status"] == "passed"
    assert result["compared_bits_by_phase"] == {"pre": 1, "post": 0}


@pytest.mark.parametrize("sample,status,known,unknown,mismatch", [
    ("00", "passed", 2, 0, 0), ("10", "failed", 2, 0, 2),
    ("1x", "failed", 1, 1, 2), ("0z", "unknown", 1, 1, 0),
    ("xx", "unknown", 0, 3, 0),
])
def test_known_and_unknown_bits_are_accounted_independently(sample, status, known, unknown, mismatch):
    task = TaskSpec.from_text("bits", "q is zero.", COMB)
    checker = parse_checker("case bits\nstep d=0 q=0", task)
    result = evaluate_checker(checker, trace_for(checker, [("xx", sample)]))
    assert result["status"] == status
    assert result["compared_bits_by_phase"] == {"pre": 0, "post": known}
    assert result["unknown_bits_by_phase"] == {"pre": 0, "post": unknown.bit_count()}
    assert result["compared_bits"] + result["unknown_bits"] == 2
    assert [entry["unknown_mask"] for entry in result["unknown"]] == ([unknown] if unknown else [])
    assert [entry["mismatch_mask"] for entry in result["failed"]] == ([mismatch] if mismatch else [])
    assert all(item["phase"] == "post" for item in result["failed"] + result["unknown"])


def test_pre_with_mixed_bits_keeps_its_phase_and_post_is_unchecked():
    interface = "module TopModule(input clk,input d,output [1:0] q); endmodule"
    task = TaskSpec.from_text("sample", CAPTURE, interface)
    checker = parse_checker("case one\ninit d=1 pre.q=0", task, init_cycles=1)
    result = evaluate_checker(checker, trace_for(checker, [("1x", "zz")]))
    assert result["status"] == "failed"
    assert result["compared_bits_by_phase"] == result["unknown_bits_by_phase"] == {"pre": 1, "post": 0}
    assert [(f["phase"], f["mismatch_mask"]) for f in result["failed"]] == [("pre", 2)]
    assert [(f["phase"], f["unknown_mask"]) for f in result["unknown"]] == [("pre", 1)]


@pytest.mark.parametrize("extra", ["pre.d=0", "pre.clk=0", "pre.unknown=0", "pre.q=0 pre.q=1",
                                    "pre.q=x", "pre.q=2", "pre.q=0 pre.pre.q=0"])
def test_pre_tokens_are_validated_at_the_public_port_width(extra):
    task = TaskSpec.from_text("register", CAPTURE, CLOCKED)
    with pytest.raises(CheckerError):
        parse_checker("case bad\ninit reset=1 d=0 q=0 " + extra, task)
    comb = TaskSpec.from_text("bits", "q is zero.", COMB)
    with pytest.raises(CheckerError, match="clocked public output"):
        parse_checker("case bad\nstep d=0 q=0 pre.q=0", comb)


@pytest.mark.parametrize("prompt,interface,supported", [
    (TOP_DOC + "posedge clk\n" + DEP_DOC + "negedge clk", CLOCKED, True),
    (TOP_DOC + "unspecified\n" + DEP_DOC + "posedge clk", CLOCKED, False),
    ("posedge clk\n" + TOP_DOC + "unspecified\n" + DEP_DOC + "negedge clk", CLOCKED, True),
    (TOP_DOC + "unspecified\n" + DEP_DOC + "negedge clk\n" + ADAPT + "posedge clk", CLOCKED, True),
    (TOP_DOC + "posedge clk\n" + DEP_DOC + "unused\n" + ADAPT + "negedge clk", CLOCKED, False),
    (TOP_DOC + "q is zero.\n" + DEP_DOC + "negedge clk", COMB, True),
    ("posedge clk\n## Dependencies\nnegedge clk", CLOCKED, False),
    (TOP_DOC + "posedge clk\n```text\n" + DEP_DOC + "```\nnegedge clk", CLOCKED, False),
    (TOP_DOC + "posedge clk\n    " + DEP_DOC + "negedge clk", CLOCKED, False),
])
def test_clock_inference_uses_only_explicit_document_boundaries(prompt, interface, supported):
    task = TaskSpec.from_text("sections", prompt, interface)
    assert checker_contract(task)["supported"] is supported


def test_full_public_text_reaches_checker_request_after_clock_scoping():
    prompt = TOP_DOC + "posedge clk\n" + DEP_DOC + "Dependency uses negedge clk.\n" + ADAPT + "Tail."
    task = TaskSpec.from_text("sections", prompt, CLOCKED)
    assert checker_contract(task)["supported"]
    assert "Dependency uses negedge clk" in checker_request(task, "key case skill")[1]["content"]
    assert task.prompt == prompt


def test_explanation_changes_checker_identity_while_preserving_sampling_and_archived_tables():
    task = TaskSpec.from_text("bits", "q is zero.", COMB)
    bare = "case zero\nstep d=1 q=0"
    annotated = bare.replace("case zero", "case zero # A high input still gives zero.")
    legacy = parse_checker(bare, task, require_explanations=False)
    current = parse_checker(annotated, task, require_explanations=True)
    edited = parse_checker(annotated.replace("A high input", "Driving one"), task, require_explanations=True)
    assert legacy.public_dict()["schema_version"] == 2
    assert "explanation" not in legacy.public_dict()["cases"][0]
    assert current.public_dict()["schema_version"] == 3
    assert current.cases[0].public_dict()["explanation"] == "A high input still gives zero."
    assert len({_checker_fingerprint(c) for c in (legacy, current, edited)}) == 3
    assert len({sampling_hash(c.plan) for c in (legacy, current, edited)}) == 1
    result = evaluate_checker(current, trace_for(current, [("xx", "0x")]))
    assert result["case_results"][0]["status"] == "unknown"
    assert result["case_results"][0]["compared_bits"] == result["case_results"][0]["unknown_bits"] == 1


@pytest.mark.parametrize("header", ["case two", "case two #", "case two # " + "x" * 241])
def test_every_new_case_requires_a_locatable_short_explanation(header):
    task = TaskSpec.from_text("bits", "q is zero.", COMB)
    with pytest.raises(CheckerError, match="line 3, case two: explanation"):
        parse_checker(f"case one # q is zero.\nstep d=1 q=0\n{header}\nstep d=0 q=0", task,
                      require_explanations=True)
