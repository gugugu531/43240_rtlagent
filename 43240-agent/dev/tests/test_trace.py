from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


AGENT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(AGENT_ROOT))
sys.path.insert(0, str(AGENT_ROOT / "dev" / "eval"))

from agent.trace import (  # noqa: E402
    TRACE_SCHEMA_VERSION,
    Trace,
    git_metadata,
    runtime_metadata,
)
from analyze import trace_stats  # noqa: E402


class TraceEventTests(unittest.TestCase):
    def test_common_fields_are_stable_and_sequence_is_monotonic(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp, "trace.jsonl")
            trace = Trace(str(path), run_id="test-run")
            trace.write(tool="agent", event="start", schema_version=999, seq=99)
            trace.write(tool="agent", event="done")
            trace.close()

            events = [json.loads(line) for line in path.read_text().splitlines()]

        self.assertEqual([event["seq"] for event in events], [1, 2])
        self.assertTrue(all(event["run_id"] == "test-run" for event in events))
        self.assertTrue(all(
            event["schema_version"] == TRACE_SCHEMA_VERSION for event in events
        ))
        self.assertTrue(all(isinstance(event["ts"], float) for event in events))
        self.assertEqual(events[0]["tool"], "agent")

    def test_sensitive_fields_and_secrets_inside_text_are_redacted(self):
        secret = "secret-value-123"
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp, "trace.jsonl")
            trace = Trace(str(path), run_id="redaction", secrets=[secret])
            trace.write(
                tool="llm",
                api_key=secret,
                nested={"authorization": f"Bearer {secret}"},
                excerpt=f"request failed with {secret}",
                tokens_in=12,
            )
            trace.close()
            raw = path.read_text()
            event = json.loads(raw)

        self.assertNotIn(secret, raw)
        self.assertEqual(event["api_key"], "[redacted]")
        self.assertEqual(event["nested"]["authorization"], "[redacted]")
        self.assertEqual(event["excerpt"], "request failed with [redacted]")
        self.assertEqual(event["tokens_in"], 12)

    def test_environment_secret_is_redacted_without_being_passed_to_trace(self):
        with patch.dict("os.environ", {"LLM_API_KEY": "environment-secret"}, clear=False):
            with tempfile.TemporaryDirectory() as temp:
                path = Path(temp, "trace.jsonl")
                trace = Trace(str(path), run_id="env-redaction")
                trace.write(tool="agent", excerpt="bad environment-secret response")
                trace.close()
                raw = path.read_text()

        self.assertNotIn("environment-secret", raw)


class MetadataTests(unittest.TestCase):
    def test_runtime_metadata_uses_a_public_allowlist(self):
        metadata = runtime_metadata(
            max_rounds=3,
            deadline_s=360,
            reserve_s=20,
            resolved_top="TopModule",
            save_candidates=True,
            keep_work=False,
            agent_tmp="/tmp",
            env={
                "LLM_BACKEND": "openai",
                "LLM_MODEL": "test-model",
                "LLM_BASE_URL": "http://127.0.0.1:8000/v1?ignored=yes",
                "LLM_API_KEY": "must-not-appear",
                "RC_COOKIE": "must-not-appear-either",
            },
        )

        encoded = json.dumps(metadata)
        self.assertEqual(metadata["model_request"]["model"], "test-model")
        self.assertEqual(
            metadata["model_request"]["base_url"],
            "http://127.0.0.1:8000/v1",
        )
        self.assertNotIn("must-not-appear", encoded)
        self.assertNotIn("api_key", encoded.lower())
        self.assertNotIn("cookie", encoded.lower())

    def test_credentials_embedded_in_base_url_are_not_recorded(self):
        metadata = runtime_metadata(
            max_rounds=3,
            deadline_s=360,
            reserve_s=20,
            resolved_top="TopModule",
            save_candidates=False,
            keep_work=False,
            agent_tmp="/tmp",
            env={"LLM_BASE_URL": "https://user:password@example.com/v1"},
        )

        encoded = json.dumps(metadata)
        self.assertNotIn("user", encoded)
        self.assertNotIn("password", encoded)
        self.assertEqual(
            metadata["model_request"]["base_url"], "[redacted-invalid-url]"
        )

    def test_git_metadata_accepts_build_time_injection(self):
        metadata = git_metadata(
            "/missing",
            {"AGENT_GIT_COMMIT": "abc123", "AGENT_GIT_DIRTY": "false"},
        )

        self.assertEqual(metadata, {
            "commit": "abc123",
            "dirty": False,
            "source": "environment",
        })


class AnalyzerCompatibilityTests(unittest.TestCase):
    def test_new_metadata_is_reported_but_not_counted_as_a_tool_call(self):
        events = [
            {
                "schema_version": 1,
                "run_id": "run-1",
                "seq": 1,
                "tool": "run",
                "event": "metadata",
                "git": {"commit": "abc123"},
            },
            {"tool": "llm", "round": 1, "tokens_in": 4, "tokens_out": 2},
            {"tool": "lint", "round": 1, "status": "ok"},
        ]

        stats = trace_stats(events)

        self.assertEqual(stats["trace_schema_version"], 1)
        self.assertEqual(stats["trace_run_id"], "run-1")
        self.assertEqual(stats["trace_git_commit"], "abc123")
        self.assertEqual(stats["tool_calls"], {"lint": 1})

    def test_old_trace_without_metadata_remains_supported(self):
        stats = trace_stats([{"tool": "llm", "round": 1, "tokens_in": 3}])

        self.assertEqual(stats["llm_calls"], 1)
        self.assertIsNone(stats["trace_schema_version"])
        self.assertIsNone(stats["trace_run_id"])
        self.assertIsNone(stats["trace_git_commit"])


if __name__ == "__main__":
    unittest.main()
