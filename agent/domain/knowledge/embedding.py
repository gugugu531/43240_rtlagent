"""Embedding runtime settings shared by index construction and querying.

Knowledge cards and vectors contain content only. The model identity and the
projection parameters live here so building and querying cannot drift.
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

import httpx
import yaml


ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = ROOT / "config/rag_embedding.yaml"


@lru_cache(maxsize=1)
def settings():
    raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    required = {
        "model_alias": str,
        "dimensions": int,
        "pooling": str,
        "normalization": str,
        "similarity": str,
        "max_length": int,
        "query_instruction": str,
        "query_template": str,
    }
    for key, kind in required.items():
        if not isinstance(raw.get(key), kind):
            raise ValueError(f"invalid embedding setting: {key}")
    if raw["dimensions"] <= 0 or raw["max_length"] <= 0:
        raise ValueError("invalid embedding dimensions")
    if raw["normalization"] != "l2":
        raise ValueError("unsupported embedding normalization")
    return raw


def vector(value):
    data = settings()
    if (
        not isinstance(value, list)
        or len(value) != data["dimensions"]
        or any(type(item) not in (int, float) or not math.isfinite(item) for item in value)
    ):
        raise ValueError("invalid_embedding_vector")
    norm = math.sqrt(sum(item * item for item in value))
    if norm == 0:
        raise ValueError("zero_embedding_vector")
    return [item / norm for item in value]


def query_text(query, stage=""):
    data = settings()
    return data["query_template"].format(
        instruction=data["query_instruction"], query=query, stage=stage
    )


def embed_query(query, *, url, timeout_s=2.0, trace=None):
    data = settings()
    request = {
        "model": data["model_alias"],
        "input": [query_text(query)],
        "encoding_format": "float",
    }
    base = url.rstrip("/")
    with httpx.Client(
        timeout=timeout_s, trust_env=False, follow_redirects=False
    ) as client:
        models = client.get(base + "/v1/models")
        models.raise_for_status()
        advertised = models.json()
        rows = advertised.get("data") if isinstance(advertised, dict) else None
        if not isinstance(rows, list) or not any(
            isinstance(row, dict) and row.get("id") == data["model_alias"]
            for row in rows
        ):
            raise ValueError("embedding_advertised_model_mismatch")
        response = client.post(base + "/v1/embeddings", json=request)
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, dict) or payload.get("model") != data["model_alias"]:
        raise ValueError("embedding_model_mismatch")
    rows = payload.get("data")
    if (
        not isinstance(rows, list)
        or len(rows) != 1
        or not isinstance(rows[0], dict)
        or rows[0].get("index") != 0
        or "embedding" not in rows[0]
    ):
        raise ValueError("invalid_embedding_response")
    if trace is not None:
        trace["embedding_model"] = payload["model"]
        trace["embedding_usage"] = payload.get("usage")
    return vector(rows[0]["embedding"])
