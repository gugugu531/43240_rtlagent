"""Embedding runtime settings shared by index construction and querying.

Knowledge cards and vectors contain content only. The model identity and the
projection parameters live here so building and querying cannot drift.
"""

from __future__ import annotations

import json
import math
import time
import uuid
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


def _request(client, method, url, *, payload=None, record=None, validate):
    """Record each HTTP attempt, including invalid responses and interruptions."""
    call_id = "embedding-" + uuid.uuid4().hex
    tool = "embedding" if method == "POST" else "embedding_models"
    started = time.monotonic()
    usage = {"tokens_in": None, "tokens_out": None}
    status = None
    fields = dict(call_id=call_id, method=method, url=url)
    if record is not None:
        record.write_json(f"calls/{call_id}/request.json", {
            "method": method, "url": url, "payload": payload,
        })
        record.emit(tool, "started", **fields)
    try:
        response = client.post(url, json=payload) if method == "POST" else client.get(url)
        status = getattr(response, "status_code", None)
        if record is not None:
            record.write_text(f"calls/{call_id}/response.txt", response.text)
            record.write_json(f"calls/{call_id}/http.json", {"status_code": status})
        response.raise_for_status()
        body = response.json()
        if method == "POST" and isinstance(body, dict) and isinstance(body.get("usage"), dict):
            for field, key in (("tokens_in", "prompt_tokens"), ("tokens_out", "completion_tokens")):
                value = body["usage"].get(key)
                usage[field] = value if type(value) is int and value >= 0 else None
        validate(body)
    except BaseException as error:
        if record is not None:
            record.emit(tool, "failed", **fields, **usage, rc=1,
                        http_status=status, elapsed_s=time.monotonic() - started,
                        error_type=type(error).__name__, excerpt=str(error))
        raise
    if record is not None:
        record.emit(tool, "finished", **fields, **usage, rc=0,
                    http_status=status, elapsed_s=time.monotonic() - started)
    return body


def embed_query(query, *, url, timeout_s=2.0, trace=None, record=None):
    data = settings()
    request = {
        "model": data["model_alias"],
        "input": [query_text(query)],
        "encoding_format": "float",
    }
    def validate_models(advertised):
        rows = advertised.get("data") if isinstance(advertised, dict) else None
        if not isinstance(rows, list) or not any(
            isinstance(row, dict) and row.get("id") == data["model_alias"]
            for row in rows
        ):
            raise ValueError("embedding_advertised_model_mismatch")

    def validate_embedding(payload):
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
        vector(rows[0]["embedding"])

    base = url.rstrip("/")
    with httpx.Client(
        timeout=timeout_s, trust_env=False, follow_redirects=False
    ) as client:
        _request(client, "GET", base + "/v1/models", record=record,
                 validate=validate_models)
        payload = _request(client, "POST", base + "/v1/embeddings", payload=request,
                           record=record, validate=validate_embedding)
    if trace is not None:
        trace["embedding_model"] = payload["model"]
        trace["embedding_usage"] = payload.get("usage")
    return vector(payload["data"][0]["embedding"])
