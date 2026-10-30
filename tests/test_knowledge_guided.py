"""Content-only knowledge base and retrieval interface."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx

from agent.domain.knowledge import guided
from agent.domain.knowledge.embedding import embed_query, settings
from agent.observability.recorder import Recorder


class KnowledgeGuidedTests(unittest.TestCase):
    def test_embedding_http_lifecycle_and_unknown_usage(self):
        for usage in ({"prompt_tokens": 7}, {}, {"prompt_tokens": True, "completion_tokens": -1}):
            with self.subTest(usage=usage), tempfile.TemporaryDirectory() as directory:
                calls = []

                def handle(request):
                    calls.append(request)
                    if request.url.path.endswith("/models"):
                        return httpx.Response(200, json={"data": [{"id": settings()["model_alias"]}]})
                    return httpx.Response(200, json={
                        "model": settings()["model_alias"], "usage": usage,
                        "data": [{"index": 0, "embedding": [1.0] + [0.0] * (settings()["dimensions"] - 1)}],
                    })

                client = httpx.Client(transport=httpx.MockTransport(handle))
                record = Recorder(directory, secrets=["private-query"])
                with patch("agent.domain.knowledge.embedding.httpx.Client", return_value=client):
                    result = embed_query("private-query", url="http://localhost:8020", record=record)
                record.close()
                rows = [json.loads(line) for line in Path(directory, "trace.jsonl").read_text().splitlines()]
                self.assertEqual([(row["tool"], row["event"]) for row in rows], [
                    ("embedding_models", "started"), ("embedding_models", "finished"),
                    ("embedding", "started"), ("embedding", "finished"),
                ])
                self.assertEqual(rows[0]["call_id"], rows[1]["call_id"])
                self.assertEqual(rows[2]["call_id"], rows[3]["call_id"])
                self.assertNotEqual(rows[0]["call_id"], rows[2]["call_id"])
                self.assertEqual(rows[-1]["tokens_in"], 7 if usage.get("prompt_tokens") == 7 else None)
                self.assertIsNone(rows[-1]["tokens_out"])
                self.assertEqual(result[0], 1.0)
                self.assertEqual(len(calls), 2)
                request_file = record.record_dir / "calls" / rows[-1]["call_id"] / "request.json"
                self.assertNotIn("private-query", request_file.read_text())
                self.assertTrue(request_file.with_name("response.txt").is_file())

    def test_embedding_failures_remain_retrieval_fallback_and_are_recorded(self):
        for failure in ("discovery", "connection", "http", "json", "model", "vector"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                def handle(request):
                    if request.url.path.endswith("/models"):
                        return httpx.Response(200, json={"data": [{
                            "id": "wrong" if failure == "discovery" else settings()["model_alias"],
                        }]})
                    if failure == "connection":
                        raise httpx.ConnectError("offline", request=request)
                    if failure == "http":
                        return httpx.Response(503, text="unavailable")
                    if failure == "json":
                        return httpx.Response(200, text="invalid json")
                    return httpx.Response(200, json={
                        "model": "wrong" if failure == "model" else settings()["model_alias"],
                        "usage": {"prompt_tokens": 9},
                        "data": [{"index": 0, "embedding": []}],
                    })

                client = httpx.Client(transport=httpx.MockTransport(handle))
                record = Recorder(directory)
                with patch("agent.domain.knowledge.embedding.httpx.Client", return_value=client):
                    cards, report = guided.retrieve(
                        "counter", mode="rag", strategy="dense", embedding_url="http://localhost:8020",
                        record=record,
                    )
                record.close()
                self.assertEqual(cards, [])
                self.assertEqual(report["reason"], "embedding_unavailable")
                rows = [json.loads(line) for line in Path(directory, "trace.jsonl").read_text().splitlines()]
                self.assertEqual(rows[-1]["event"], "failed")
                self.assertEqual(rows[-1]["rc"], 1)
                self.assertEqual(rows[-2]["event"], "started")
                self.assertEqual(rows[-1]["call_id"], rows[-2]["call_id"])
                self.assertEqual(rows[-1]["tokens_in"], 9 if failure in ("model", "vector") else None)
                self.assertIsNone(rows[-1]["tokens_out"])
                self.assertEqual(len(rows), 2 if failure == "discovery" else 4)

    def test_card_set_is_complete_and_has_no_release_metadata(self):
        cards = guided.load_cards()
        self.assertEqual(len(cards), 129)
        self.assertEqual(len({card["card_id"] for card in cards}), 129)
        states = {card.get("activation_state") for card in cards}
        self.assertEqual(states, {"legacy_policy", "restricted", "shadow", "mechanical_only"})
        self.assertEqual(sum(card["activation_state"] == "legacy_policy" for card in cards), 32)
        self.assertEqual(sum(card["activation_state"] == "restricted" for card in cards), 38)
        forbidden = {"version", "sha256", "path", "release_id", "projection_text", "source", "origin"}

        def keys(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    yield key
                    yield from keys(child)
            elif isinstance(value, list):
                for child in value:
                    yield from keys(child)

        for card in cards:
            self.assertFalse(forbidden & set(keys(card)), card["card_id"])
            self.assertTrue(card["title"])
            self.assertTrue(guided.card_text(card))

    def test_vectors_are_complete_and_match_embedding_settings(self):
        vectors = guided.load_vectors()
        self.assertEqual(set(vectors), {card["card_id"] for card in guided.load_cards()})
        data = settings()
        self.assertEqual(data["dimensions"], 1024)
        self.assertEqual(data["pooling"], "last")
        self.assertEqual(data["normalization"], "l2")
        for value in vectors.values():
            self.assertEqual(len(value), data["dimensions"])

    def test_legacy_diagnostic_cards_are_not_pre_generation_candidates(self):
        cards, report = guided.retrieve(
            "synchronous reset counter register shift", mode="legacy", limit=3
        )
        self.assertEqual(cards, [])
        self.assertEqual(report["stage"], "pre_generation")
        self.assertNotIn("diag-vrfc-10-1280", report["selected"])

    def test_forbidden_card_is_filtered_before_dense_ranking(self):
        from agent.domain.knowledge.embedding import settings

        class Response:
            def __init__(self, payload):
                self.payload = payload

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        class Client:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def get(self, url):
                return Response({"data": [{"id": settings()["model_alias"]}]})

            def post(self, url, json):
                return Response({
                    "model": settings()["model_alias"],
                    "data": [{
                        "index": 0,
                        "embedding": [1.0] + [0.0] * (settings()["dimensions"] - 1),
                    }],
                })

        with patch("agent.domain.knowledge.embedding.httpx.Client", Client):
            cards, report = guided.retrieve(
                "VRFC 10-1280 procedural assignment non-register",
                mode="rag", limit=5, strategy="dense",
                embedding_url="http://127.0.0.1:8020",
            )
        # The query would rank the diagnostic card highly, but its phase and
        # injection_eligible flag forbid first-draft injection.
        self.assertNotIn("diag-vrfc-10-1280", report["selected"])
        self.assertNotIn("diag-vrfc-10-1280", {row["card_id"] for row in report["retrieved"]})
        self.assertTrue(all(guided.card_allowed(card, "pre_generation") for card in cards))

    def test_dense_route_uses_the_configured_http_embedding_service(self):
        from agent.domain.knowledge.embedding import settings

        captured = {}

        class Response:
            def __init__(self, payload):
                self.payload = payload

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        class Client:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def get(self, url):
                return Response({"data": [{"id": settings()["model_alias"]}]})

            def post(self, url, json):
                captured.update(json)
                return Response({
                    "model": settings()["model_alias"],
                    "data": [{
                        "index": 0,
                        "embedding": [1.0] + [0.0] * (settings()["dimensions"] - 1),
                    }],
                })

        with patch("agent.domain.knowledge.embedding.httpx.Client", Client):
            cards, report = guided.retrieve(
                "signed arithmetic width carry", mode="rag", limit=3,
                strategy="dense", embedding_url="http://127.0.0.1:8020",
            )
        self.assertTrue(cards)
        self.assertEqual(report["strategy"], "dense")
        self.assertTrue(report["selected"])
        self.assertEqual(captured["model"], settings()["model_alias"])
        self.assertIn("Query:", captured["input"][0])
        self.assertIn("stage:", captured["input"][0])

    def test_rag_retrieval_can_return_restricted_cards(self):
        cards, report = guided.retrieve(
            "signed arithmetic width carry", mode="rag", limit=5
        )
        self.assertTrue(report["selected"])
        self.assertTrue(all(card["activation_state"] in {"legacy_policy", "restricted"} for card in cards))


if __name__ == "__main__":
    unittest.main()
