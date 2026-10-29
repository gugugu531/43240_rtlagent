"""Smoke-test the promoted rc4.3 production routing state."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from agent.knowledge.catalog import validate_catalog
from agent.knowledge.pregen import decide, retrieve_spec
from agent.knowledge.research import load_bundle


HOSTS = {
    "v9-lang-context-before-operation": 33589,
    "v9-public-batch-final-sample": 33589,
    "v9-public-block-carry-chain": 33376,
}
CASES = {
    "v9-lang-context-before-operation": "b51-019",
    "v9-public-batch-final-sample": "b51-route-batch",
    "v9-public-block-carry-chain": "b51-route-carry",
}


def load(path):
    return json.loads(path.read_text())


def main():
    data = load_bundle()
    assert data["release_id"] == "rag-catalog-v3-rc4.3"
    catalog = validate_catalog(data)
    cards = {row["card_id"]: row for row in data["cards"]}
    tasks = {row["case_id"]: row for row in load(ROOT / "dev/optimization-v51/tasks.json")["tasks"]}
    entries = {row["card_id"]: row for row in catalog["entries"]}
    rows = []
    for card_id, host in HOSTS.items():
        card = cards[card_id]
        task = tasks[CASES[card_id]]
        assert card["activation_state"] == "restricted"
        assert card["injection_stages"] == ["pre_generation"]
        assert entries[card_id]["state"] == "restricted"
        assert entries[card_id]["policy_adapter"] == "reviewed_public_specification"
        decision = decide(card, task["prompt"], task["interface"], data=data)
        assert decision["admit"] and decision["decision_class"] == "eligible"
        routes = {}
        for strategy in ("bm25", "dense"):
            options = {"strategy": strategy, "fallback": "empty", "retrieve_k": 5, "inject_k": 1}
            if strategy == "dense":
                options.update(
                    embedding_url="http://127.0.0.1:8020",
                    embedding_transport="ssh",
                    embedding_ssh_host="root@36.150.116.206",
                    embedding_ssh_port=host,
                    embedding_timeout_s=3.5,
                )
            admitted, trace = retrieve_spec(task["prompt"], task["interface"], options)
            ids = [row["id"] for row in trace["retrieved"]]
            assert [row["card_id"] for row in admitted] == [card_id]
            assert trace["admitted"] == [card_id]
            assert trace["actually_sent"] == []
            routes[strategy] = {
                "rank": ids.index(card_id) + 1,
                "admitted": trace["admitted"],
                "reason": trace["reason"],
                "error": trace.get("error"),
                "elapsed_ms": trace.get("elapsed_ms"),
                "embedding_ms": trace.get("embedding_ms"),
            }
        rows.append({"card_id": card_id, "case_id": task["case_id"], "host": host, "routes": routes, "passed": True})
    deferred = [row for row in load(HERE / "route-results.json")["rows"] if not row["passed"]]
    assert len(deferred) == 7 and all(cards[row["card_id"]]["activation_state"] == "shadow" for row in deferred)
    result = {
        "release_id": data["release_id"],
        "status": "passed",
        "restricted_count": sum(card["activation_state"] == "restricted" for card in cards.values()),
        "promoted_count": len(rows),
        "deferred_shadow_count": len(deferred),
        "rows": rows,
        "model_calls": 0,
        "assembly_boundary": "retrieve_spec admits cards; exact message assembly was separately audited in routed model pairs",
    }
    (HERE / "post-promotion-smoke.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
