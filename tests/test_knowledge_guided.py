"""Content-only knowledge base and retrieval interface."""

import unittest
from unittest.mock import patch

from agent.domain.knowledge import guided
from agent.domain.knowledge.embedding import settings


class KnowledgeGuidedTests(unittest.TestCase):
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
