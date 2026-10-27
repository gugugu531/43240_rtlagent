"""ToolResult envelope: rc mapping, bounded excerpt, full artifacts."""

from dataclasses import dataclass, field
import unittest

from agent.runtime.tool_result import (
    EXCERPT_LIMIT,
    RC_FAILED,
    RC_OK,
    RC_TIMEOUT,
    ToolResult,
    truncate_excerpt,
)


@dataclass
class FakeCheck:
    status: str
    summary: str
    failure_kind: str = "code"
    log_paths: tuple = ()
    details: dict = field(default_factory=dict)
    blocking: bool = False
    rc: int = 0
    elapsed_s: float = 1.5
    command: tuple = ()
    id: str = "check-1"
    kind: str = "lint"
    candidate_id: str = "c001"


class ToolResultTests(unittest.TestCase):
    def test_check_result_mapping_keeps_rc_status_and_artifacts(self):
        result = ToolResult.from_check_result(
            FakeCheck("failed", "ERROR: cannot find port", log_paths=("/tmp/lint.log",)),
            tool="lint",
        )
        self.assertEqual(result.tool, "lint")
        self.assertEqual(result.rc, RC_FAILED)
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.failure_kind, "code")
        self.assertEqual(result.artifacts, ("/tmp/lint.log",))
        self.assertEqual(result.meta["check_id"], "check-1")
        self.assertFalse(result.truncated)

    def test_timeout_and_pass_rc_mapping(self):
        self.assertEqual(
            ToolResult.from_check_result(FakeCheck("timeout", "late")).rc, RC_TIMEOUT
        )
        self.assertEqual(
            ToolResult.from_check_result(FakeCheck("passed", "ok")).rc, RC_OK
        )

    def test_excerpt_is_cut_on_utf8_boundary_and_marked(self):
        text = "中" * (EXCERPT_LIMIT // 3 + 10)
        excerpt, truncated = truncate_excerpt(text)
        self.assertTrue(truncated)
        self.assertIn("[truncated:", excerpt)
        # The kept prefix must still be valid UTF-8 text.
        excerpt.encode("utf-8")
        self.assertLess(len(excerpt.encode("utf-8")), len(text.encode("utf-8")))

    def test_from_value_serializes_dicts(self):
        result = ToolResult.from_value({"accepted": True}, tool="submit")
        self.assertEqual(result.rc, RC_OK)
        self.assertIn('"accepted": true', result.excerpt)

    def test_failure_helper_truncates(self):
        result = ToolResult.failure(tool="x", excerpt="e" * 5000, failure_kind="code")
        self.assertTrue(result.truncated)
        self.assertIn("[truncated:", result.excerpt)


if __name__ == "__main__":
    unittest.main()
