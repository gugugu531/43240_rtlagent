"""Submission gateway: LWW publication, selected policy, and finalize audit."""

from types import SimpleNamespace
from dataclasses import replace
import json
import multiprocessing
import os
import signal
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import agent.orchestration.nodes  # noqa: F401 - register built-in tools
from agent.domain.rtl.candidate import CandidateStore
from agent.submission.gateway import SubmissionError, SubmissionGateway
from agent.observability.recorder import Recorder
from agent.domain.knowledge.outcome import summarize
from agent.runtime.budget import Deadline

CODE_A = "module TopModule();\nendmodule\n"
CODE_B = "module TopModule();\n  // second\nendmodule\n"


def make_context(directory, top="TopModule"):
    record = Recorder(directory, level="basic")
    candidates = CandidateStore(record, Path(directory))
    ctx = SimpleNamespace(
        task=SimpleNamespace(top=top), candidates=candidates, record=record
    )
    return ctx, record


def assessment(candidate, **stages):
    checks = {
        stage: {"kind": stage, "candidate_id": candidate.id, "status": status, "rc": rc,
                "failure_kind": kind, "details": {"candidate_hash": candidate.code_hash}}
        for stage, (status, rc, kind) in stages.items()
    }
    return {"candidate_id": candidate.id, "candidate_hash": candidate.code_hash, "checks": checks}


PASSED = ("passed", 0, "unknown")
UNAVAILABLE = ("unavailable", 127, "environment")


def killed_with_unchecked_child(directory):
    ctx, _ = make_context(directory)
    gateway = SubmissionGateway(ctx, policy="author_decides")
    first = ctx.candidates.create(CODE_A)
    gateway.register(first, reason="initial")
    gateway.record_structure(first, assessment(first, lint=PASSED, synth=PASSED))
    gateway.register(ctx.candidates.create(CODE_B, parent_id=first.id), reason="revise")
    os.kill(os.getpid(), signal.SIGKILL)


class SubmissionGatewayTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.ctx, self.record = make_context(self.directory.name)
        self.solution = Path(self.directory.name) / "solution.v"

    def tearDown(self):
        self.record.close()

    def candidate(self, code):
        return self.ctx.candidates.create(code, source_stage="test")

    def test_last_written_publishes_newest_and_records_override(self):
        gateway = SubmissionGateway(self.ctx, policy="last_written")
        first = self.candidate(CODE_A)
        second = self.candidate(CODE_B)
        gateway.register(first, reason="draft")
        gateway.register(second, reason="child")
        self.assertEqual(self.solution.read_text(encoding="utf-8"), CODE_B)

        # Simulate the evidence-backed selection being the older candidate.
        self.ctx.candidates.selected_id = first.id
        record = gateway.finalize("test")
        self.assertEqual(record["final"]["target_id"], second.id)
        self.assertTrue(record["final"]["overrode_selected"])
        self.assertEqual(record["final"]["delivery"], "complete_rtl")
        # Finalize is idempotent and does not rewrite a different candidate.
        again = gateway.finalize("test")
        self.assertEqual(again["final"], record["final"])
        self.assertEqual(self.solution.read_text(encoding="utf-8"), CODE_B)

    def test_selected_policy_waits_for_selection(self):
        gateway = SubmissionGateway(self.ctx, policy="selected")
        candidate = self.candidate(CODE_A)
        gateway.register(candidate, reason="draft")
        self.assertFalse(self.solution.exists())

        self.ctx.candidates.selected_id = candidate.id
        record = gateway.finalize("test")
        self.assertEqual(record["final"]["target_id"], candidate.id)
        self.assertEqual(self.solution.read_text(encoding="utf-8"), CODE_A)

    def test_submit_text_rejects_incomplete_draft(self):
        gateway = SubmissionGateway(self.ctx, policy="last_written")
        with self.assertRaises(SubmissionError):
            gateway.submit_text("module TopModule();", top="TopModule")
        self.assertFalse(self.solution.exists())

    def test_submit_text_rejects_a_different_top(self):
        gateway = SubmissionGateway(self.ctx, policy="last_written")
        with self.assertRaises(SubmissionError):
            gateway.submit_text(
                "module WrongModule; endmodule", top="WrongModule"
            )
        self.assertFalse(self.solution.exists())

    def test_submit_text_registers_and_publishes_complete_draft(self):
        gateway = SubmissionGateway(self.ctx, policy="last_written")
        record = gateway.submit_text(CODE_A, top="TopModule", source_stage="tool")
        self.assertTrue(record["published"])
        self.assertEqual(record["policy"], "last_written")
        self.assertEqual(self.solution.read_text(encoding="utf-8"), CODE_A)

    def test_finalize_without_candidate_keeps_empty_answer(self):
        gateway = SubmissionGateway(self.ctx, policy="last_written")
        record = gateway.finalize("test")
        self.assertFalse(record["final"]["published"])
        self.assertEqual(record["final"]["delivery"], "empty")
        self.assertFalse(self.solution.exists())

    def test_events_are_jsonl_traceable(self):
        gateway = SubmissionGateway(self.ctx, policy="last_written")
        gateway.register(self.candidate(CODE_A), reason="draft")
        gateway.finalize("test")
        events = [
            json.loads(line)
            for line in (Path(self.directory.name) / "trace.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        names = [(row["tool"], row["event"]) for row in events]
        self.assertIn(("publish", "result"), names)
        self.assertIn(("submission", "published"), names)
        self.assertIn(("submission", "finalized"), names)

    def test_hard_kill_after_unchecked_revision_keeps_checked_bytes_and_identity(self):
        case = Path(self.directory.name) / "killed"
        process = multiprocessing.get_context("fork").Process(target=killed_with_unchecked_child, args=(case,))
        process.start()
        process.join(10)
        self.assertEqual(process.exitcode, -signal.SIGKILL)
        self.assertEqual((case / "solution.v").read_text(), CODE_A)
        outcome = summarize(case / "trace.jsonl", case / "solution.v")
        self.assertEqual(outcome["published_candidate_id"], "c001")
        self.assertEqual(outcome["submission_mode"], "fallback")
        self.assertFalse(outcome["submission_finalized"])
        self.assertEqual(outcome["fallback_basis"], "latest_toolchain_passed")
        self.assertIsNone(outcome["selected_candidate_id"])

    def test_only_bound_passing_tool_pair_authorizes_automatic_selection(self):
        gateway = SubmissionGateway(self.ctx, policy="author_decides")
        first, second = self.candidate(CODE_A), self.candidate(CODE_B)
        gateway.register(first, reason="initial")
        gateway.record_structure(first, assessment(first, lint=PASSED, synth=PASSED))
        gateway.register(second, reason="revision")
        for forged in (replace(second, code=CODE_A), replace(second, code_hash=first.code_hash)):
            with self.assertRaises(SubmissionError):
                gateway.register(forged, reason="retry")
        partial = assessment(second, lint=PASSED)
        for wrong in (assessment(first, lint=PASSED), {**partial, "candidate_hash": first.code_hash},
                      {**partial, "checks": assessment(first, lint=PASSED)["checks"]},
                      {**partial, "checks": {"synth": partial["checks"]["lint"]}}, {**partial, "checks": {}}):
            with self.assertRaises(SubmissionError):
                gateway.record_structure(second, wrong)
        with self.assertRaises(SubmissionError):
            gateway.submit_candidate(second, mode="author_submit", reason="never checked")
        with self.assertRaises(SubmissionError):
            gateway.submit_candidate(first, mode="author_submit", reason="old draft")
        for incomplete in (partial, assessment(second, lint=PASSED, synth=UNAVAILABLE),
                           assessment(second, lint=PASSED, synth=("passed", 1, "unknown"))):
            gateway.record_structure(second, {**incomplete, "toolchain_passed": True})
            with self.assertRaises(SubmissionError):
                gateway.submit_candidate(second, mode="structural_auto", reason="invalid")
            self.assertEqual(self.solution.read_text(), CODE_A)
        gateway.record_structure(second, assessment(second, lint=("failed", 1, "code")))
        with self.assertRaises(SubmissionError):
            gateway.submit_candidate(second, mode="author_submit", reason="code error")
        final = gateway.finalize("shared_call_limit")["final"]
        self.assertEqual((final["mode"], final["target_id"], final["code_hash"]),
                         ("fallback", first.id, first.code_hash))
        self.assertEqual(final["fallback_basis"], "latest_toolchain_passed")

    def test_auto_and_author_choose_the_current_registered_draft(self):
        gateway = SubmissionGateway(self.ctx, policy="author_decides")
        first, second = self.candidate(CODE_A), self.candidate(CODE_B)
        for candidate in (first, second):
            gateway.register(candidate, reason="draft")
            gateway.record_structure(candidate, assessment(candidate, lint=PASSED, synth=PASSED))
        gateway.record_structure(first, assessment(first, lint=PASSED, synth=PASSED))
        self.assertEqual(self.solution.read_text(), CODE_B)
        result = gateway.submit_candidate(second, mode="structural_auto", reason="structural route")
        self.assertEqual(result["final"]["mode"], "structural_auto")
        self.assertEqual(result["final"]["structure_status"], "lint_synth_passed")
        self.assertEqual(gateway.finalize("run_end"), result)
        self.assertEqual(gateway.submit_candidate(second, mode="structural_auto", reason="retry"), result)
        with self.assertRaises(SubmissionError):
            gateway.submit_candidate(first, mode="author_submit", reason="old")

    def test_author_can_choose_unverified_draft_and_resume_interrupted_atomic_write(self):
        gateway = SubmissionGateway(self.ctx, policy="author_decides")
        first, second = self.candidate(CODE_A), self.candidate(CODE_B)
        gateway.register(first, reason="initial")
        gateway.record_structure(first, assessment(first, lint=PASSED, synth=PASSED))
        gateway.register(second, reason="revise")
        gateway.record_structure(second, assessment(second, interface=PASSED, lint=UNAVAILABLE))
        with patch.object(self.ctx.candidates, "select", side_effect=Deadline("cancelled")):
            with self.assertRaises(Deadline):
                gateway.submit_candidate(second, mode="author_submit", reason="public intent matches")
        final = gateway.finalize("cancelled")["final"]
        self.assertEqual((final["mode"], final["reason"], final["structure_status"]),
                         ("author_submit", "public intent matches", "unverified"))
        self.assertEqual(final["target_id"], final["selected_id"])
        self.assertEqual(final["code_hash"], second.code_hash)
        self.assertIsNone(final["fallback_basis"])
        self.assertEqual(self.solution.read_text(), CODE_B)

    def test_latest_complete_then_empty_fallback(self):
        gateway = SubmissionGateway(self.ctx, policy="author_decides")
        for invalid in (self.candidate("module Wrong(); endmodule"), self.candidate("module TopModule();")):
            with self.assertRaises(SubmissionError):
                gateway.register(invalid, reason="incomplete")
        self.solution.write_text("stale bytes")
        empty = gateway.finalize("deadline")["final"]
        self.assertEqual((empty["mode"], empty["fallback_basis"], empty["target_id"]),
                         ("fallback", "no_complete_candidate", None))
        self.assertEqual(self.solution.read_bytes(), b"")
        gateway = SubmissionGateway(self.ctx, policy="author_decides")
        first, second = self.candidate(CODE_A), self.candidate(CODE_B)
        gateway.register(first, reason="initial")
        gateway.register(second, reason="child")
        gateway.register(first, reason="retry")
        final = gateway.finalize("deadline")["final"]
        self.assertEqual(self.solution.read_text(), CODE_B)
        self.assertIsNone(final["selected_id"])
        self.assertEqual((final["target_id"], final["fallback_basis"]), (second.id, "latest_complete"))


if __name__ == "__main__":
    unittest.main()
