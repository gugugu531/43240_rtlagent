"""Self-authored contracts for the RTL author's decision and private context."""

import json

import pytest

from agent.domain.rtl.candidate import CandidateFactory
from agent.domain.rtl.guided_author import (
    AuthorDecisionError, author_decision_request, author_history, parse_author_decision,
)
from agent.domain.rtl.task import TaskSpec
from agent.roles import profile_for_stage, role_for_stage


RTL = "module Mirror(input a, output y); assign y = a; endmodule"
REVISED = "module Mirror(input a, output y); assign y = ~a; endmodule"
CASE = "polarity"


def decide(text, ids=(CASE,)):
    return parse_author_decision(text, top="Mirror", case_ids=ids)


def test_submit_uses_current_draft_and_review_names_only_one_active_point():
    submitted = decide("action=submit\nreason=The public task does not specify this output during reset.", ids=())
    assert submitted.action == "submit" and submitted.extraction is None
    assert submitted.public_dict() == {"action": "submit", "reason": submitted.reason}
    review = decide("reason=y=0 is unspecified on this step.\ncase_id=polarity\naction=review")
    assert review.public_dict() == {"action": "review", "reason": review.reason, "case_id": CASE}
    assert review.extraction is None


@pytest.mark.parametrize("reason", [
    "The module declaration now closes with endmodule and Vivado passed.",
    "The module Mirror passes lint; its endmodule is present.",
    "The module Mirror (including its ports) now compiles, and the endmodule label matches.",
])
def test_reason_can_discuss_module_syntax_in_prose(reason):
    decision = decide(f"action=submit\nreason={reason}")
    assert decision.action == "submit" and decision.reason == reason


@pytest.mark.parametrize("code", [
    REVISED,
    "module Helper; endmodule",
    "module /* helper */ Helper (x, y); input x; output y; assign y=x; endmodule",
    "module automatic Helper #(parameter W=$clog2(4)) (input [W-1:0] a); endmodule",
    "module Helper import pkg::*; (input word_t a); endmodule",
    r"module \escaped.helper ; endmodule",
])
def test_reason_rejects_a_real_module_embedded_in_an_explanation(code):
    with pytest.raises(AuthorDecisionError, match="without an RTL draft"):
        decide(f"action=submit\nreason=The module passed; here is the result: {code}")


def test_revision_extracts_full_rtl_in_one_reply_without_adding_rtl_to_decision_memory():
    helper = "module Invert(input a, output y); assign y=~a; endmodule"
    rtl = "`timescale 1ns/1ps\n"+helper+"\n"+REVISED
    parsed = decide(f"action=revise\nreason=Invert the input.\n```systemverilog\n{rtl}\n```")
    assert parsed.extraction.code == rtl+"\n"
    assert parsed.extraction.module_names == ("Invert", "Mirror")
    assert parsed.public_dict() == {"action":"revise","reason":"Invert the input."}


@pytest.mark.parametrize("text", [
    "", "action=submit", "reason=done", "action=done\nreason=done",
    "action=submit\nreason=", "action=submit\nreason="+"a"*401,
    "action=submit\nreason=ok\naction=revise",
    "action=submit\nreason=ok\ncase_id=polarity",
    "action=submit\nreason=ok\n" + REVISED,
    "action=submit\nreason=" + REVISED,
    "action=submit\nreason=ok\n```verilog\n"+REVISED+"\n```",
    "action=submit\nreason=ok\nunrequested=field",
    "action=review\nreason=question",
    "action=review\nreason=question\ncase_id=unknown",
    "action=review\nreason=question\ncase_id=polarity,other",
    "action=review\nreason=question\ncase_id=polarity\n```verilog\n"+REVISED+"\n```",
    "action=revise\nreason=fix\n"+REVISED,
    "action=revise\nreason=fix\n```python\n"+REVISED+"\n```",
    "action=revise\nreason=fix\n```verilog\n"+REVISED,
    "action=revise\nreason=fix\n```verilog\nmodule Mirror(input a);\n```",
    "action=revise\nreason=fix\n```verilog\nmodule Other; endmodule\n```",
    "action=revise\nreason=fix\n```verilog\n"+REVISED+"\n```\nextra prose",
    "action=revise\nreason=fix\n```verilog\n"+REVISED+"\n```\n```verilog\n"+RTL+"\n```",
])
def test_malformed_or_ambiguous_reply_has_no_executable_action(text):
    with pytest.raises(AuthorDecisionError):
        decide(text)


def request(case_ids=(CASE,)):
    task = TaskSpec.from_text("self-authored", "The output is the bitwise complement of a.",
                              "module Mirror(input a, output y);", top="Mirror")
    candidate = CandidateFactory().create(RTL, source_stage="guided_solve", round=1)
    history = [
        {"round": n, "role":"author", "action":"review", "reason":f"note {n}",
         "source_call_id":f"call-{n}", "case_id":CASE, "candidate_id":candidate.id,
         "code":"SECRET_OLD_DRAFT", "reasoning":"SECRET_THINKING"}
        for n in range(16)
    ]
    history.append({"role":"builder", "review_action":"keep", "review_reason":"Polarity is explicit.",
                    "reviewed_checker_hash":"before", "changed":False, "checked":True,
                    "source_call_id":"check-17", "request_messages":["SECRET_OLD_MESSAGES"]})
    args = dict(
        structure={"candidate_id":candidate.id, "candidate_hash":candidate.code_hash, "lint":"passed"},
        behavior={"status":"failed", "compared_bits":1, "unknown_bits":1,
                  "failed":[{"case_id":CASE,"phase":"post","actual_bits":0,"expected_bits":1}]},
        checker_text="case polarity # Invert the low bit.\nstep a=0 y=1" if case_ids else "",
        checker_status="valid" if case_ids else "unavailable", case_ids=case_ids,
        history=history, budget={"calls_remaining":1, "known_output_tokens":42},
        execution={"phase":"post"},
    )
    return task, candidate, args


def test_request_rebuilds_an_author_context_with_all_decisions_and_only_this_candidate_rtl():
    task, candidate, args = request()
    messages = author_decision_request(task, candidate, **args)
    assert [m["role"] for m in messages] == ["system","user"]
    body = messages[1]["content"]
    assert task.prompt in body and task.interface in body and candidate.code in body
    assert args["checker_text"] in body and candidate.code_hash in body
    assert "SECRET_" not in body
    assert body.index("note 0") < body.index("note 15") < body.index("Polarity is explicit.")
    report = json.loads(body.split("Host report and decision history:\n",1)[1].split("\n\n",1)[0])
    assert report["active_case_ids"] == [CASE] and report["behavior"] == args["behavior"]
    assert report["structure"] == args["structure"] and report["shared_budget"] == args["budget"]
    assert report["decision_history"] == author_history(args["history"])
    assert report["decision_history"][-1]["reviewed_checker_hash"] == "before"


def test_no_checker_remains_unverified_and_cannot_be_reviewed():
    task, candidate, args = request(case_ids=())
    args["behavior"] = {"status":"not_run","reason":"simulation unavailable","compared_bits":0}
    body = author_decision_request(task,candidate,**args)[-1]["content"]
    assert '"active_case_ids":[]' in body and '"status":"not_run"' in body and "action=review" not in body
    with pytest.raises(AuthorDecisionError):
        decide("action=review\nreason=please review\ncase_id=polarity", ids=())


@pytest.mark.parametrize("report,field", [("structure","candidate_id"),("behavior","candidate_hash")])
def test_a_prompt_cannot_attribute_another_candidates_evidence_to_current_rtl(report,field):
    task, candidate, args = request()
    args[report][field] = "stale"
    with pytest.raises(ValueError, match="different candidate"):
        author_decision_request(task,candidate,**args)


@pytest.mark.parametrize(("stage","role"), [("author_decision","author"),("checker_review","builder"),
                                            ("checker_format_repair","builder")])
def test_request_role_survives_numbered_attempts(stage,role):
    for label in (stage, f"guided_{stage}_12", f"{stage}_2_tool_1"):
        assert role_for_stage(label) == role
        assert profile_for_stage(label) == "large"
