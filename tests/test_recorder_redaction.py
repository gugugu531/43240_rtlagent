"""Recorder JSON integrity and redaction boundaries; no model or EDA tool required."""

from copy import deepcopy
import json
import tempfile
import unittest

from agent.observability.recorder import Recorder


def strict_loads(text):
    """Parse JSON while rejecting the non-standard NaN/Infinity constants."""
    def non_finite(constant):
        raise ValueError(f"non-finite JSON constant: {constant}")

    return json.loads(text, parse_constant=non_finite)


class RecorderRedactionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.recorder = Recorder(self.directory.name, secrets=["sk-live-secret"])
        self.addCleanup(self.recorder.close)

    def written(self, relative):
        return (self.recorder.record_dir / relative).read_text(encoding="utf-8")

    def test_emit_uses_contract_timestamps(self):
        # docs/API_CONTRACT.md asks for Unix seconds; ts_iso is the readable copy.
        from datetime import datetime

        self.recorder.emit("probe", "result", rc=0)
        rows = [
            strict_loads(line)
            for line in (self.recorder.output_dir / "trace.jsonl").read_text(
                encoding="utf-8"
            ).splitlines()
        ]
        row = rows[-1]
        self.assertIsInstance(row["ts"], float)
        parsed = datetime.fromisoformat(row["ts_iso"])
        self.assertAlmostEqual(parsed.timestamp(), row["ts"], places=3)

    def test_write_json_emits_strict_parseable_json_with_escaped_secrets(self):
        # Text-level redaction after json.dumps corrupted JSON when a secret
        # carried escape characters; object-level redaction must not.
        secret = 'sk-"quoted"\\path\nline'
        data = {
            "api-key": secret,
            "note": 'keep "escaped"\\text\nline',
            "n": 3,
            "nested": {"items": [{"password": "p@ss word"}]},
        }
        self.recorder.write_json("artifacts/evidence.json", data)
        text = self.written("artifacts/evidence.json")
        parsed = strict_loads(text)
        self.assertEqual(parsed["api-key"], "[redacted]")
        self.assertEqual(parsed["nested"]["items"][0]["password"], "[redacted]")
        self.assertEqual(parsed["note"], data["note"])
        self.assertEqual(parsed["n"], 3)
        self.assertNotIn(secret, text)
        self.assertNotIn("p@ss word", text)

    def test_sensitive_keys_are_redacted_at_every_nesting_level(self):
        data = {
            "outer": {"Authorization": "Bearer abc123", "keep": "x"},
            "list": [
                {"token": "t0ken"},
                {"deep": {"refresh-token": "r3fr3sh", "ok": 1}},
            ],
            "plain": {"value": "visible"},
        }
        original = deepcopy(data)
        self.recorder.write_json("nested.json", data)
        parsed = strict_loads(self.written("nested.json"))
        self.assertEqual(parsed["outer"]["Authorization"], "[redacted]")
        self.assertEqual(parsed["outer"]["keep"], "x")
        self.assertEqual(parsed["list"][0]["token"], "[redacted]")
        self.assertEqual(parsed["list"][1]["deep"]["refresh-token"], "[redacted]")
        self.assertEqual(parsed["list"][1]["deep"]["ok"], 1)
        self.assertEqual(parsed["plain"]["value"], "visible")
        # Recording sanitizes a copy; the caller's object is untouched.
        self.assertEqual(data, original)

    def test_write_text_redacts_once_and_write_json_redacts_the_object_only(self):
        calls = []
        copy = self.recorder.redactor.copy

        def spy(value):
            calls.append(value)
            return copy(value)

        self.recorder.redactor.copy = spy
        text = "token=abc123 raw sk-live-secret"
        self.recorder.write_text("notes/reply.txt", text)
        self.assertEqual(len(calls), 1)
        self.assertIsInstance(calls[0], str)
        self.assertEqual(self.written("notes/reply.txt"), copy(text))
        self.assertNotIn("sk-live-secret", self.written("notes/reply.txt"))

        calls.clear()
        self.recorder.write_json("object.json", {"api_key": "sk-live-secret", "keep": "v"})
        # Exactly one pass, applied to the Python object before serialization;
        # a second pass over the serialized text is what corrupted escaping.
        self.assertEqual(len(calls), 1)
        self.assertIsInstance(calls[0], dict)
        parsed = strict_loads(self.written("object.json"))
        self.assertEqual(parsed["api_key"], "[redacted]")
        self.assertEqual(parsed["keep"], "v")

    def test_model_input_messages_are_not_modified_by_recording(self):
        secret = "sk-model-input-secret"
        messages = [
            {"role": "system", "content": "token=" + secret},
            {"role": "user", "content": "api_key: " + secret},
        ]
        before = deepcopy(messages)
        self.recorder.write_json("model/request.json", {"messages": messages})
        self.assertEqual(messages, before)
        record = strict_loads(self.written("model/request.json"))
        self.assertEqual(len(record["messages"]), 2)
        self.assertNotIn(secret, self.written("model/request.json"))


if __name__ == "__main__":
    unittest.main()
