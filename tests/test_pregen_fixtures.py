"""Only public task text may enter the committed pregen fixtures."""

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/pregen"


class PregenFixtureTests(unittest.TestCase):
    def test_tasks_keep_only_public_text(self):
        rows = json.loads((FIXTURES / "tasks.json").read_text())["tasks"]
        self.assertEqual(len(rows), 30)
        for row in rows:
            self.assertEqual(set(row), {"case_id", "prompt", "interface"})
            self.assertTrue(row["prompt"])

    def test_batches_keep_only_routing_ids(self):
        expected = {"card_id", "route_case_id"}
        for version in ("54", "55", "56"):
            rows = json.loads(
                (FIXTURES / f"batch-v{version}.json").read_text()
            )["cards"]
            self.assertEqual(len(rows), 10)
            for row in rows:
                self.assertEqual(set(row), expected)


if __name__ == "__main__":
    unittest.main()
