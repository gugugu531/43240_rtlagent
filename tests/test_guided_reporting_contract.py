"""Synthetic regression coverage for guided delivery, stop reasons and routing."""

import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from agent.domain.knowledge.outcome import summarize
from agent.llm.client import Client
from agent.main import main
from agent.roles import profile_for_stage, role_for_stage
from agent.runtime.budget import Budget, Deadline
from agent.submission.gateway import SubmissionGateway


def event(tool, event, **fields):
    return {"tool": tool, "event": event, **fields}


def report(directory, rows, code=b""):
    trace = directory / "trace.jsonl"
    trace.write_text("".join(json.dumps(row) + "\n" for row in rows))
    solution = directory / "solution.v"
    solution.write_bytes(code)
    return summarize(trace, solution)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def test_run_end_binds_final_file_after_cancelled_last_write(tmp_path):
    prompt = tmp_path / "input"
    prompt.mkdir()
    (prompt / "prompt.txt").write_text("Implement a synthetic one-bit output.")
    output = tmp_path / "output"
    parent = "module TopModule(output q); assign q=0; endmodule\n"
    child = parent.replace("q=0", "q=1")

    def interrupted(ctx):
        gateway = ctx.store["submission"] = SubmissionGateway(ctx)
        first = ctx.candidates.create(parent)
        ctx.candidates.select(first.id, "first")
        gateway.register(first, reason="draft")
        second = ctx.candidates.create(child, parent_id=first.id)
        gateway.register(second, reason="repair")
        raise Deadline("cancelled")

    config = Path(__file__).resolve().parents[1] / "config/guided_verify.yaml"
    with patch.dict("os.environ", {"LLM_BACKEND": "mock"}), patch(
        "agent.orchestration.graph.run_graph", side_effect=interrupted
    ):
        main(["--input", str(prompt), "--output", str(output), "--config", str(config)])
    end = json.loads((output / "trace.jsonl").read_text().splitlines()[-1])
    assert (end["tool"], end["event"], end["stop_reason"]) == ("run", "end", "cancelled")
    assert end["candidate_id"] == end["published_id"] == "c002"
    assert end["published_sha256"] == digest((output / "solution.v").read_bytes()) == digest(child.encode())
    assert end["selected_id"] == "c001" and end["selected_sha256"] == digest(parent.encode())


def test_legacy_selection_is_a_write_but_creation_and_mismatched_bytes_are_not(tmp_path):
    code = b"module T(); endmodule\n"
    created = event("candidate", "create", candidate_id="c001", code_hash=digest(code))
    selected = event("select", "result", candidate_id="c001", code_hash=digest(code))
    assert report(tmp_path, [created], code)["published_candidate_id"] is None
    assert report(tmp_path, [created, selected], code)["published_candidate_id"] == "c001"
    mismatch = report(tmp_path, [created, selected], b"different")
    assert mismatch["published_candidate_id"] is None and mismatch["published_candidate_sha256"] is None
    assert mismatch["selected_candidate_sha256"] == digest(code)
    assert report(tmp_path, [], b"")["published_candidate_id"] is None


def test_legacy_guided_extraction_requires_matching_status_stage_and_source_call(tmp_path):
    first = [
        event("llm", "finished", purpose="guided_solve", call_id="m1"),
        event("guided", "artifact", name="solve-extraction", status="ok"),
        event("candidate", "create", source_stage="guided_solve", source_call_id="m1",
              candidate_id="c001", extraction_status="ok", code_hash="h1"),
        event("select", "result", candidate_id="c001", code_hash="h1"),
        event("llm", "finished", purpose="guided_repair_structure_2", call_id="m2"),
        event("guided", "artifact", name="repair_structure-extraction", status="target_missing"),
        event("guided", "artifact", name="repair_structure-failure"),
    ]
    wrong = [
        event("llm", "finished", purpose="guided_solve_recovery", call_id="m3"),
        event("guided", "artifact", name="solve_recovery-extraction", status="ok"),
        event("candidate", "create", source_stage="guided_solve_recovery", source_call_id="unrelated",
              candidate_id="c002", extraction_status="ok"),
        event("llm", "finished", purpose="guided_checker", call_id="m4"),
        event("guided", "artifact", name="checker-failure"),
    ]
    result = report(tmp_path, first + wrong)
    assert result["selected_candidate_complete"] is True
    assert result["latest_complete_candidate_id"] == "c001"
    assert [a["source_call_id"] for a in result["attempts"]] == ["m1", "m2"]
    assert result["attempt_counts"] == {"checker_unknown": 1, "not_delivered": 1}

    explicit = event("extract", "result", candidate_id="c001", source_call_id="m1", complete_new_draft=True)
    result = report(tmp_path, first + [explicit])
    assert len(result["attempts"]) == 2
    assert len([d for d in result["deliveries"] if d["source_call_id"] == "m1"]) == 1


def test_interrupt_timeout_and_environment_are_distinct(tmp_path):
    failed = event("llm", "failed", purpose="guided_checker", call_id="m1",
                   error_kind="interrupted", error_type="Deadline")
    for reason, outcome in (("deadline", "deadline"), ("cancelled", "cancelled"), (None, "interrupted")):
        rows = [failed]
        if reason is not None:
            rows.append(event("budget", "stopped", reason=reason))
        assert report(tmp_path, rows)["attempt_counts"] == {outcome: 1}
    for kind, outcome in (("timeout", "model_timeout"), ("http", "model_request_failed")):
        row = {**failed, "error_kind": kind, "error_type": None}
        assert report(tmp_path, [row])["attempt_counts"] == {outcome: 1}

    code = b"module T(); endmodule"
    rows = [
        event("candidate", "create", candidate_id="c001", source_call_id="m2", code_hash=digest(code)),
        event("extract", "result", candidate_id="c001", source_call_id="m2", complete_new_draft=True),
    ]
    evidence = {"candidate_id": "c001", "failure_kind": "environment", "status": "unavailable",
                "details": {"candidate_hash": digest(code)}}
    check = event("lint", "result", output=evidence)
    assert report(tmp_path, rows + [check])["attempt_counts"] == {"environment_failure": 1}
    other = {**check, "output": {**evidence, "details": {"candidate_hash": "unrelated"}}}
    assert report(tmp_path, rows + [other])["attempt_counts"] == {"checker_unknown": 1}


def test_numbered_recovery_uses_the_same_model_profile_and_address():
    client = Client({"backend": "mock", "model": "primary", "base_url": "http://primary.invalid/v1"},
                    Budget(60, 0), None, {}, profiles={
                        "large": {"enabled": True, "model": "secondary", "base_url": "http://secondary.invalid/v1"}
                    })
    try:
        for stage, role in (("solve_recovery", "author"), ("checker_recovery", "builder")):
            for label in (stage, stage + "_2", "guided_" + stage + "_12"):
                assert role_for_stage(label) == role
                profile = profile_for_stage(label)
                assert profile == "large"
                assert client.profile_model(profile) == "secondary"
                assert client.profile_base_url(profile) == "http://secondary.invalid/v1"
        assert role_for_stage("draft_tool_2") == "author"
        assert profile_for_stage("unregistered_2") == ""
    finally:
        client.close()


@pytest.mark.parametrize(("changes", "accepted"), [
    ({}, True),
    ({"method": "structural", "compared_bits": None, "checker_hash": None, "checker_version": None,
      "behavior_status": None, "functional_passed": False}, True),
    ({"behavior_status": "failed", "functional_passed": False}, False),
    ({"behavior_status": "failed", "functional_passed": False, "checker_disputed": True}, None),
    ({"expectations_revised": True}, None),
    ({"checker_disputed": True}, None),
    ({"checker_disputed": None}, None),
    ({"structural_passed": False}, None),
    ({"behavior_status": "partial_passed"}, None),
    ({"behavior_status": "unknown"}, None),
    ({"behavior_status": "invalid"}, None),
    ({"functional_passed": False}, None),
    ({"behavior_status": "failed", "functional_passed": True}, None),
    ({"compared_bits": 0}, None),
    ({"compared_bits": True}, None),
    ({"checker_hash": ""}, None),
    ({"checker_version": None}, None),
    ({"candidate_id": "c002"}, None),
    ({"candidate_hash": "unrelated"}, None),
])
def test_final_verification_binds_internal_results_only(tmp_path, changes, accepted):
    code = b"module T(); endmodule"
    identity = digest(code)
    created = event("candidate", "create", candidate_id="c001", source_call_id="m1", code_hash=identity)
    extracted = event("extract", "result", candidate_id="c001", source_call_id="m1", complete_new_draft=True)
    check = event("lint", "result", output={"candidate_id": "c001", "status": "passed"})
    proof = event("guided", "verification", candidate_id="c001", candidate_hash=identity,
                  method="table", structural_passed=True, behavior_status="passed", compared_bits=4,
                  checker_hash="original-table", checker_version="version", expectations_revised=False,
                  checker_disputed=False, functional_passed=True)
    proof.update(changes)
    summary = report(tmp_path, [created, extracted, check, proof], code)
    attempt, = summary["attempts"]
    assert attempt["checker_accepted"] is accepted
    assert attempt["outcome"] == {True: "new_draft_unscored", False: "checker_rejected",
                                  None: "checker_unknown"}[accepted]
    assert attempt["scored_candidate_sha256"] is None and summary["external_score"] is None
    assert attempt["eligible_for_effect_comparison"] is False
    assert summary["checks"] == [check] and summary["guided_verifications"] == [proof]


@pytest.mark.parametrize("have_candidate", [False, True])
def test_deadline_before_finish_reports_actual_guided_fallback(tmp_path, have_candidate):
    root = Path(__file__).resolve().parents[1]
    prompt = tmp_path / "input"
    prompt.mkdir()
    (prompt / "prompt.txt").write_text("Design signature:\nmodule TopModule();")
    output = tmp_path / "answer"
    code = "module TopModule(); endmodule\n"

    def interrupt(ctx):
        if have_candidate:
            gateway = ctx.store["submission"] = SubmissionGateway(ctx, policy="author_decides")
            candidate = ctx.candidates.create(code)
            gateway.register(candidate, reason="draft")
        raise Deadline("deadline")

    with patch.dict("os.environ", {"LLM_BACKEND": "mock"}), patch(
        "agent.orchestration.graph.run_graph", side_effect=interrupt
    ):
        main(["--input", str(prompt), "--output", str(output), "--config", str(root / "config/guided_verify.yaml")])
    rows = [json.loads(line) for line in (output / "trace.jsonl").read_text().splitlines()]
    end = rows[-1]
    assert end["tool"] == "run" and end["event"] == "end"
    assert end["submission_mode"] == "fallback" and end["submission_finalized"] is True
    assert end["submission_reason"] == end["stop_reason"] == "deadline"
    assert end["fallback_basis"] == ("latest_complete" if have_candidate else "no_complete_candidate")
    assert end["published_id"] == ("c001" if have_candidate else None)
    assert end["published_sha256"] == (digest(code.encode()) if have_candidate else None)
    assert end["selected_id"] is None and end["submission_structure_status"] == "not_checked"


def test_disputed_author_submission_keeps_external_and_check_results_separate(tmp_path):
    code = b"module T(); endmodule\n"
    identity = digest(code)
    rows = [
        event("candidate", "create", source_call_id="m1", candidate_id="c001", code_hash=identity),
        event("extract", "result", source_call_id="m1", candidate_id="c001", complete_new_draft=True),
        event("select", "result", candidate_id="c001", code_hash=identity, reason="author_submit"),
        event("submission", "finalized", policy="author_decides", mode="author_submit", target_id="c001",
              code_hash=identity, delivery="complete_rtl", reason="wrong table", structure_status="lint_synth_passed"),
        event("guided", "verification", candidate_id="c001", candidate_hash=identity, method="table",
              checker_hash="t", checker_version="v", structural_passed=True, compared_bits=1,
              checker_disputed=True, expectations_revised=False, behavior_status="failed", functional_passed=False),
    ]
    result = report(tmp_path, rows, code)
    assert result["submission_mode"] == "author_submit" and result["submission_reason"] == "wrong table"
    assert result["submission_structure_status"] == "lint_synth_passed" and result["submission_finalized"] is True
    assert result["attempt_counts"] == {"checker_unknown": 1}
    assert result["external_score"] is None and result["attempts"][0]["attempt_success"] is None
    for changes in ({"target_id": "c002"}, {"code_hash": "wrong"}):
        forged = [*rows[:3], {**rows[3], **changes}, rows[4]]
        assert report(tmp_path, forged, code)["submission_mode"] is None
    fallback_write = event("publish", "result", candidate_id="c001", code_hash=identity, reason="finalize:deadline")
    assert report(tmp_path, [*rows[:2], fallback_write, *rows[3:]], code)["submission_mode"] is None
    assert report(tmp_path, rows, b"different bytes")["submission_mode"] is None
    trace = tmp_path / "trace.jsonl"
    report(tmp_path, rows, code)
    with trace.open("ab") as stream:
        stream.write(b'{"tool":')
    assert summarize(trace, tmp_path / "solution.v")["published_candidate_id"] == "c001"


def test_unfinalized_empty_author_workflow_requires_no_registered_draft(tmp_path):
    started = event("submission", "started", policy="author_decides")
    empty = report(tmp_path, [started])
    assert (empty["submission_mode"], empty["submission_finalized"], empty["fallback_basis"]) == (
        "fallback", False, "no_complete_candidate")
    registered = event("submission", "registered", policy="author_decides", candidate_id="c001", code_hash="a")
    assert report(tmp_path, [started, registered])["submission_mode"] is None
