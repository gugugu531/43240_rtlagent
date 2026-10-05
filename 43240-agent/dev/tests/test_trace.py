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

from agent.core.metadata import git_metadata
from agent.core.config import ModelConfig, ModelConfigError
from agent.recording.redaction import Redactor
from agent.recording.recorder import RunRecorder

class TraceEventTests(unittest.TestCase):
    def test_common_fields_are_stable_and_sequence_is_monotonic(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp, "trace.jsonl")
            trace = RunRecorder(temp)
            trace.write_event(tool="agent", event="start", schema_version=999, seq=99)
            trace.write_event(tool="agent", event="done")
            trace.close()

            events = [json.loads(line) for line in path.read_text().splitlines()]

        self.assertEqual([event["seq"] for event in events], [1, 2, 3])
        self.assertTrue(all(event["run_id"] == trace.run_id for event in events))
        self.assertTrue(all(
            event["schema_version"] == 4 for event in events
        ))
        self.assertTrue(all(isinstance(event["ts"], float) for event in events))
        self.assertEqual(events[1]["tool"], "agent")

    def test_sensitive_fields_and_secrets_inside_text_are_redacted(self):
        secret = "secret-value-123"
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp, "trace.jsonl")
            trace = RunRecorder(temp, secrets=[secret])
            trace.write_event(
                tool="llm",
                api_key=secret,
                nested={"authorization": f"Bearer {secret}"},
                excerpt=f"request failed with {secret}",
                tokens_in=12,
            )
            trace.close()
            raw = path.read_text()
            event = json.loads(raw.splitlines()[1])

        self.assertNotIn(secret, raw)
        self.assertEqual(event["api_key"], "[redacted]")
        self.assertEqual(event["nested"]["authorization"], "[redacted]")
        self.assertEqual(event["excerpt"], "request failed with [redacted]")
        self.assertEqual(event["tokens_in"], 12)

    def test_environment_secret_is_redacted_without_being_passed_to_trace(self):
        with patch.dict("os.environ", {"LLM_API_KEY": "environment-secret"}, clear=False):
            with tempfile.TemporaryDirectory() as temp:
                path = Path(temp, "trace.jsonl")
                trace = RunRecorder(temp)
                trace.write_event(tool="agent", excerpt="bad environment-secret response")
                trace.close()
                raw = path.read_text()

        self.assertNotIn("environment-secret", raw)


class MetadataTests(unittest.TestCase):
    def test_service_metadata_uses_a_public_allowlist(self):
        config = ModelConfig(backend="openai", model="test-model", base_url="http://localhost/v1", api_key="secret-value")
        encoded = json.dumps(config.public_dict())
        self.assertNotIn("secret-value", encoded)
        self.assertNotIn("api_key", encoded)
        self.assertNotIn("temperature", encoded)
        self.assertNotIn("max_tokens", encoded)

    def test_credentials_embedded_in_base_url_are_not_recorded(self):
        with self.assertRaises(ModelConfigError):
            ModelConfig(backend="openai", base_url="https://user:password@example.com/v1")
        public = Redactor().copy("https://user:password@example.com/v1?token=value")
        self.assertNotIn("user:password", public)
        self.assertNotIn("token=value", public)

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


class LifecycleStatisticsTests(unittest.TestCase):
    def test_count_attempts_once_and_use_finish_reason(self):
        sys.path.insert(0, str(AGENT_ROOT / 'dev/eval'))
        from analyze import trace_stats
        stats = trace_stats([
            dict(tool='llm', event='started', call_id='m001'),
            dict(tool='llm', event='succeeded', call_id='m001', finish_reason='length',
                 tokens_in=None, tokens_out=3, elapsed_s=0.5),
            dict(tool='llm', event='started', call_id='m002'),
            dict(tool='llm', event='failed', call_id='m002', rc=1, elapsed_s=0.2),
            dict(tool='llm', event='started', call_id='m003'),
            dict(tool='recording', event='warning', rc=1),
            dict(tool='node', event='succeeded'),
            dict(tool='extract', event='result'),
            dict(tool='candidate', event='select'),
        ])
        self.assertEqual(stats['llm_calls'], 3)
        self.assertEqual(stats['llm_errors'], 1)
        self.assertEqual(stats['truncated'], 1)
        self.assertEqual(stats['llm_s'], 0.7)
        self.assertEqual(stats['tool_calls'], {})


if __name__ == "__main__":
    unittest.main()
