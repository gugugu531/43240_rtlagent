"""Single-point checker review from synthetic public tasks, without a candidate."""

from types import SimpleNamespace

import pytest

from agent.domain.rtl.guided_checker import CheckerError, checker_request, evaluate_checker, parse_checker
from agent.domain.rtl.guided_revision import apply_checker_review, checker_review_request
from agent.domain.rtl.observation import parse_observations
from agent.domain.rtl.task import TaskSpec


TASK = TaskSpec.from_text("invert", "q is the two-bit complement of d.\n\nAll inputs are defined.",
                          "module TopModule(input [1:0] d, output [1:0] q); endmodule")
FIRST = "case zero # 输入全零时，逐位取反得到全一。\n  step   d=0  q=3"
MIDDLE = "case mixed # A mixed input exercises the low bit.\nstep d=1 q=1"
LAST = "case ones # Both bits clear for an all-ones input.\nstep d=3 q=0"
TABLE = "\n".join([FIRST, MIDDLE, LAST])
REPLACEMENT = "case mixed # Complement each bit for two mixed inputs.\nstep d=2 q=1\nstep d=1 q=2"
REVIEW = "review mixed correct # Complementing the public two-bit vector flips both bits.\n" + REPLACEMENT


def complement_samples(checker, *, invert=True):
    """A correct two-bit inverter or a broken wire, independent of the table's expected bits."""
    marker = "1" * 16
    lines = []
    for ci, plan in enumerate(checker.plan["cases"]):
        for si, step in enumerate(plan["steps"]):
            d = step["inputs"]["d"]
            q = d ^ 3 if invert else d
            for offset, phase in enumerate(("pre", "post")):
                lines.append(f"RTLA_OBS_{marker}|{ci}|{si}|{si + offset}|{phase}|b:{d:02b}|b:{q:02b}")
    lines.append(f"RTLA_OBS_DONE_{marker}")
    return parse_observations("\n".join(lines), checker.plan, marker,
                              candidate_hash="a" * 64, execution_id="synthetic")


def test_correct_replays_a_changed_timeline_without_touching_neighboring_cases():
    original = parse_checker(TABLE, TASK, require_explanations=True)
    old = evaluate_checker(original, complement_samples(original))
    assert [(r["case_id"], r["status"]) for r in old["case_results"]] == [
        ("zero", "passed"), ("mixed", "failed"), ("ones", "passed"),
    ]
    review = apply_checker_review(REVIEW, TASK, TABLE, "mixed")
    assert (review.action, review.case_id, review.reason) == (
        "correct", "mixed", "Complementing the public two-bit vector flips both bits.",
    )
    assert review.table_text == "\n".join([FIRST, REPLACEMENT, LAST])
    assert review.checker == parse_checker(review.table_text, TASK, require_explanations=True)
    for i in (0, 2):
        assert original.cases[i] == review.checker.cases[i]
        assert original.plan["cases"][i] == review.checker.plan["cases"][i]
    assert evaluate_checker(review.checker, complement_samples(original))["status"] == "invalid"
    good = evaluate_checker(review.checker, complement_samples(review.checker))
    assert good["status"] == "passed" and good["compared_bits"] == 8
    assert [r["compared_bits"] for r in good["case_results"]] == [2, 4, 2]
    assert good["case_results"][1]["explanation"] == review.checker.cases[1].explanation
    bad = evaluate_checker(review.checker, complement_samples(review.checker, invert=False))
    assert bad["status"] == "failed" and len(bad["failed"]) == 4
    assert [r["mismatches"] for r in bad["case_results"]] == [1, 2, 1]


def test_keep_and_withdraw_replay_through_the_last_point():
    keep = apply_checker_review("review ones keep # The specification defines this complement.",
                                TASK, TABLE, "ones")
    assert keep.table_text == TABLE
    assert keep.checker == parse_checker(TABLE, TASK, require_explanations=True)
    active = TABLE
    for target, expected in [("mixed", FIRST + "\n" + LAST), ("zero", LAST), ("ones", "")]:
        result = apply_checker_review(f"review {target} withdraw # Withdraw this point.", TASK, active, target)
        assert result.table_text == expected
        assert result.checker == (parse_checker(expected, TASK, require_explanations=True) if expected else None)
        active = result.table_text


def test_phase_only_correction_preserves_post_samples_and_other_case():
    task = TaskSpec.from_text(
        "register", "On posedge clk, synchronous reset clears q, otherwise q captures d.",
        "module TopModule(input clk, input reset, input d, output q); endmodule",
    )
    untouched = "case capture # Capture one after reset.\ninit reset=1 d=0 q=0\nstep reset=0 d=1 pre.q=0 q=1"
    reset = ("case clear # The reset edge clears a loaded one.\ninit reset=1 d=0 q=0\n"
             "step reset=0 d=1 q=1\ninit reset=1 d=1 pre.q=0 q=0")
    table = untouched + "\n" + reset
    original = parse_checker(table, task, require_explanations=True)
    review = apply_checker_review(
        "review clear correct # The loaded one remains visible before the synchronous reset edge.\n"
        + reset.replace("d=1 pre.q=0 q=0", "d=1 pre.q=1 q=0"), task, table, "clear",
    )
    assert review.checker.plan == original.plan
    assert review.checker.cases[0] == original.cases[0]
    assert review.checker.cases[1].expected == original.cases[1].expected
    assert review.checker.cases[1].pre_expected == {3: {"q": 1}}
    assert original.cases[1].pre_expected == {3: {"q": 0}}


@pytest.mark.parametrize("reply,message", [
    ("review ones keep # Valid.", "requested case"),
    ("review mixed guess # Maybe.", "unknown review action"),
    ("review mixed keep", "reason after #"),
    ("review mixed keep # ", "reason after #"),
    ("review mixed keep # " + "a" * 241, "reason after #"),
    ("review mixed keep # Valid.\nstep d=0 q=3", "single review line"),
    ("review mixed withdraw # Withdraw.\n" + FIRST, "single review line"),
    ("review mixed correct # Fix it.", "complete explained replacement"),
    ("review mixed correct # Fix it.\n" + REPLACEMENT + "\n" + FIRST, "only the requested case"),
    ("review mixed correct # Rename.\n" + REPLACEMENT.replace("case mixed", "case other"), "requested case ID"),
    ("review mixed correct # Fix it.\ncase mixed\nstep d=1 q=2", "case mixed: explanation"),
    ("review mixed correct # Fix it.\ncase mixed # Known.\nstep d=1 q=x", "case mixed: value for q"),
    ("review mixed correct # No change.\n" + MIDDLE, "no change"),
])
def test_malformed_or_cross_point_review_cannot_change_the_table(reply, message):
    with pytest.raises(CheckerError, match=message):
        apply_checker_review(reply, TASK, TABLE, "mixed")


def test_constructor_and_reviewer_accept_only_their_own_public_context():
    task = SimpleNamespace(id=TASK.id, top=TASK.top, prompt=TASK.prompt, interface=TASK.interface,
                           expected_interface=TASK.expected_interface, code="secret_rtl",
                           author_reason="secret_reason", trace="secret_measurement")
    messages = checker_review_request(task, "fixed skill", TABLE, "mixed", source_ids=("s0002",))
    assert [m["role"] for m in messages] == ["system", "user"]
    prompt = messages[1]["content"]
    assert TABLE in prompt and "Test point to review: mixed" in prompt
    assert "Public paragraphs to consult: s0002" in prompt
    assert "Host execution contract" in prompt and "All inputs are defined." in prompt
    for text in ("secret_rtl", "secret_reason", "secret_measurement"):
        assert text not in prompt
    with pytest.raises(CheckerError, match="source IDs"):
        checker_review_request(task, "skill", TABLE, "mixed", source_ids=("s0002 secret_reason",))
    with pytest.raises(CheckerError, match="absent"):
        checker_review_request(task, "skill", TABLE, "unknown", source_ids=("s0002",))
    with pytest.raises(CheckerError, match="focus"):
        checker_request(task, "skill", ("secret_reason",))
