"""Knowledge loading and retrieval for guided and RAG generation routes.

The knowledge base stores card content only. There is no stored version,
release lock, file path or hash; retrieval is a deterministic function of the
cards and the runtime embedding settings.
"""

from __future__ import annotations

import json
import math
import re

import httpx
from collections import Counter
from functools import lru_cache
from pathlib import Path

from .embedding import embed_query, vector

ROOT = Path(__file__).resolve().parents[3]
CARDS_PATH = ROOT / "knowledge/cards.json"
VECTORS_PATH = ROOT / "knowledge/vectors.json"
_MODES = {
    "legacy": {"legacy_policy"},
    "rag": {"legacy_policy", "restricted"},
    "all": {"legacy_policy", "restricted", "shadow", "mechanical_only"},
}


@lru_cache(maxsize=1)
def load_cards():
    data = json.loads(CARDS_PATH.read_text(encoding="utf-8"))
    cards = tuple(data["cards"])
    if len({card["card_id"] for card in cards}) != len(cards):
        raise ValueError("duplicate knowledge card id")
    return cards


def card_map():
    return {card["card_id"]: card for card in load_cards()}


@lru_cache(maxsize=1)
def load_vectors():
    data = json.loads(VECTORS_PATH.read_text(encoding="utf-8"))
    rows = {}
    for row in data["vectors"]:
        rows[row["card_id"]] = vector(row["vector"])
    if set(rows) != set(card_map()):
        raise ValueError("vector/card identity mismatch")
    return rows


def card_text(card):
    text = card.get("search_text")
    if not text:
        text = "\n".join(
            str(part)
            for part in (
                card.get("title", ""),
                card.get("family", ""),
                " ".join(card.get("keywords", [])),
                card.get("narrow_fact", ""),
                " ".join(card.get("applies_when", [])),
                " ".join(card.get("refuse_when", [])),
            )
            if part
        )
    return text


def _tokens(text):
    return [
        token.casefold()
        for token in re.findall(r"[A-Za-z][A-Za-z0-9_+-]*|\d+|[\u3400-\u9fff]", text)
    ]


def bm25_rank(cards, query):
    documents = [_tokens(card_text(card)) for card in cards]
    frequencies = Counter(token for document in documents for token in set(document))
    average = sum(map(len, documents)) / max(1, len(documents))
    ranked = []
    for card, document in zip(cards, documents):
        counts = Counter(document)
        score = 0.0
        matched = 0
        for term in sorted(set(_tokens(query))):
            frequency = counts[term]
            if not frequency:
                continue
            matched += 1
            score += (
                math.log(
                    1 + (len(cards) - frequencies[term] + 0.5)
                    / (frequencies[term] + 0.5)
                )
                * frequency
                * 2.5
                / (frequency + 1.5 * (0.25 + 0.75 * len(document) / max(average, 1)))
            )
        if matched >= 2:
            ranked.append((card["card_id"], score))
    return sorted(ranked, key=lambda item: (-item[1], item[0]))


def dense_rank(cards, query, *, embedding_url, timeout_s=2.0, trace=None):
    query_vector = embed_query(
        query, url=embedding_url, timeout_s=timeout_s, trace=trace
    )
    vectors = load_vectors()
    ranked = [
        (card["card_id"], sum(a * b for a, b in zip(query_vector, vectors[card["card_id"]])))
        for card in cards
    ]
    return sorted(ranked, key=lambda item: (-item[1], item[0]))


def retrieve(
    query,
    *,
    mode="legacy",
    limit=5,
    strategy="bm25",
    embedding_url="",
    embedding_timeout_s=2.0,
    trace=None,
):
    report = {"mode": mode, "strategy": strategy, "retrieved": [], "selected": []}
    if mode == "off":
        report["reason"] = "disabled"
        if trace is not None:
            trace.update(report)
        return [], report
    if mode not in _MODES:
        raise ValueError("unknown knowledge retrieval mode")
    statuses = _MODES[mode]
    cards = [
        card
        for card in load_cards()
        if card.get("activation_state") in statuses
    ]
    try:
        if strategy == "dense":
            if not embedding_url:
                raise ValueError("embedding_endpoint_unconfigured")
            ranking = dense_rank(
                cards,
                query,
                embedding_url=embedding_url,
                timeout_s=embedding_timeout_s,
                trace=trace,
            )
        elif strategy == "bm25":
            ranking = bm25_rank(cards, query)
        else:
            raise ValueError("unknown knowledge retrieval strategy")
    except (OSError, ValueError, RuntimeError, httpx.HTTPError) as error:
        report["error"] = type(error).__name__ + ": " + str(error)
        report["reason"] = "embedding_unavailable" if strategy == "dense" else "retrieval_unavailable"
        if trace is not None:
            trace.update(report)
        return [], report
    selected = [card_map()[card_id] for card_id, _ in ranking[:limit]]
    report.update(
        retrieved=[
            {"card_id": card_id, "score": score}
            for card_id, score in ranking[:limit]
        ],
        selected=[card["card_id"] for card in selected],
        reason="retrieved" if selected else "empty",
    )
    if trace is not None:
        trace.update(report)
    return selected, report
