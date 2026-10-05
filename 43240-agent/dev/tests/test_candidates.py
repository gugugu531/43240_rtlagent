from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


AGENT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(AGENT_ROOT))

from agent.artifacts import ArtifactStore, atomic_write_text  # noqa: E402
from agent.candidate import CandidateFactory  # noqa: E402


class CandidateTests(unittest.TestCase):
    def test_factory_assigns_identity_lineage_and_hash(self):
        factory = CandidateFactory()
        first = factory.create(
            "module TopModule; endmodule\n",
            source_stage="generate",
            round=1,
            finish_reason="stop",
        )
        second = factory.create(
            "module TopModule; wire x; endmodule\n",
            source_stage="repair",
            round=2,
            parent_id=first.id,
            finish_reason="length",
        )

        self.assertEqual(first.id, "c001")
        self.assertEqual(second.id, "c002")
        self.assertEqual(second.parent_id, "c001")
        self.assertEqual(second.source_stage, "repair")
        self.assertEqual(
            first.code_hash,
            hashlib.sha256(first.code.encode("utf-8")).hexdigest(),
        )
        self.assertNotIn("code", first.public_dict())
        self.assertEqual(first.trace_dict()["candidate_id"], "c001")

    def test_factory_rejects_empty_code(self):
        with self.assertRaises(ValueError):
            CandidateFactory().create("", source_stage="generate", round=1)


class ArtifactStoreTests(unittest.TestCase):
    def test_development_mode_saves_candidate_and_selection(self):
        with tempfile.TemporaryDirectory() as temp:
            store = ArtifactStore(temp, save_candidates=True)
            self.assertEqual(Path(temp, "solution.v").read_text(), "")
            candidate = CandidateFactory().create(
                "module TopModule; endmodule\n",
                source_stage="generate",
                round=1,
            )

            store.save_candidate(candidate)
            store.select(candidate, reason="latest_extracted")

            self.assertEqual(Path(temp, "solution.v").read_text(), candidate.code)
            self.assertEqual(
                Path(temp, "candidates", "c001.v").read_text(),
                candidate.code,
            )
            metadata = json.loads(
                Path(temp, "candidates", "c001.json").read_text()
            )
            selection = json.loads(Path(temp, "selection.json").read_text())
            self.assertEqual(metadata["id"], "c001")
            self.assertEqual(metadata["code_hash"], candidate.code_hash)
            self.assertEqual(selection["candidate_id"], "c001")
            self.assertEqual(selection["reason"], "latest_extracted")

    def test_submission_mode_only_updates_solution(self):
        with tempfile.TemporaryDirectory() as temp:
            store = ArtifactStore(temp)
            candidate = CandidateFactory().create(
                "module TopModule; endmodule\n",
                source_stage="generate",
                round=1,
            )
            store.save_candidate(candidate)
            store.select(candidate, reason="latest_extracted")

            self.assertEqual(Path(temp, "solution.v").read_text(), candidate.code)
            self.assertFalse(Path(temp, "candidates").exists())
            self.assertTrue(Path(temp, "selection.json").exists())

    def test_failed_replace_keeps_previous_complete_file(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp, "solution.v")
            atomic_write_text(target, "old complete answer\n")

            with patch("agent.artifacts.os.replace", side_effect=OSError("boom")):
                with self.assertRaises(OSError):
                    atomic_write_text(target, "new answer\n")

            self.assertEqual(target.read_text(), "old complete answer\n")
            self.assertEqual(list(Path(temp).glob(".solution.v.*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
