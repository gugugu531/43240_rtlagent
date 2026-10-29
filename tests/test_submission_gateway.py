"""Submission gateway: LWW publication, selected policy, and finalize audit."""

from types import SimpleNamespace
import json
import tempfile
import unittest
from pathlib import Path

import agent.orchestration.nodes  # noqa: F401 - register built-in tools
from agent.domain.rtl.candidate import CandidateStore
from agent.submission.gateway import SubmissionError, SubmissionGateway
from agent.observability.recorder import Recorder

CODE_A = "module TopModule();\nendmodule\n"
CODE_B = "module TopModule();\n  // second\nendmodule\n"


def make_context(directory, top="TopModule"):
    record = Recorder(directory, level="basic")
    candidates = CandidateStore(record, Path(directory))
    ctx = SimpleNamespace(
        task=SimpleNamespace(top=top), candidates=candidates, record=record
    )
    return ctx, record


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


if __name__ == "__main__":
    unittest.main()
