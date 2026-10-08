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

from agent.recording.artifacts import ArtifactStore, atomic_write_text  # noqa: E402
from agent.core.candidate import CandidateFactory  # noqa: E402


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
    def test_store_updates_solution_and_checkpoint_only(self):
        with tempfile.TemporaryDirectory() as temp:
            store = ArtifactStore(temp)
            self.assertEqual(Path(temp, "solution.v").read_text(), "")
            candidate = CandidateFactory().create(
                "module TopModule; endmodule\n",
                source_stage="generate",
                round=1,
            )
            store.select(candidate, reason="latest_extracted")

            self.assertEqual(Path(temp, "solution.v").read_text(), candidate.code)
            selection = json.loads(Path(temp, "selection.json").read_text())
            self.assertEqual(selection["candidate_id"], "c001")
            self.assertEqual(selection["code_hash"], candidate.code_hash)
            self.assertEqual(selection["reason"], "latest_extracted")
            self.assertEqual(sorted(p.name for p in Path(temp).iterdir()), ["selection.json", "solution.v"])

    def test_failed_replace_keeps_previous_complete_file(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp, "solution.v")
            atomic_write_text(target, "old complete answer\n")

            with patch("agent.recording.artifacts.os.replace", side_effect=OSError("boom")):
                with self.assertRaises(OSError):
                    atomic_write_text(target, "new answer\n")

            self.assertEqual(target.read_text(), "old complete answer\n")
            self.assertEqual(list(Path(temp).glob(".solution.v.*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
