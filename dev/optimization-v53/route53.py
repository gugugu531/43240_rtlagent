"""Read-only routing gate for the first ten-card restricted promotion batch."""
from copy import deepcopy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from agent.knowledge.pregen import decide, retrieve_spec
from agent.knowledge.research import load_bundle


def load(path):
    return json.loads(path.read_text())


def main():
    batch = load(HERE / "batch.json")
    data = load_bundle()
    if data["release_id"] != batch["base_release"]:
        raise ValueError("base_release_changed")
    cards = {row["card_id"]: row for row in data["cards"]}
    tasks = {row["case_id"]: row for row in load(ROOT / "dev/optimization-v51/tasks.json")["tasks"]}
    rows = []
    for item in batch["cards"]:
        card = cards[item["card_id"]]
        task = tasks[item["case_id"]]
        direct = {
            "positive": decide(card, task["prompt"], task["interface"], data=data),
            "known": decide(card, card["narrow_fact"], task["interface"], data=data),
            "conflicting": decide(card, "This claim is false: " + card["narrow_fact"], task["interface"], data=data),
            "insufficient": decide(card, "Implement the required module.", task["interface"], data=data),
        }
        changed = deepcopy(card)
        changed["version"] += ".tampered"
        direct["tampered"] = decide(changed, task["prompt"], task["interface"], data=data)
        routes = {}
        for strategy in ("bm25", "dense"):
            options = {
                "strategy": strategy,
                "fallback": "empty",
                "retrieve_k": batch["retrieve_k"],
                "inject_k": batch["inject_k"],
            }
            if strategy == "dense":
                options.update(
                    embedding_url="http://127.0.0.1:8020",
                    embedding_transport="ssh",
                    embedding_ssh_host="root@36.150.116.206",
                    embedding_ssh_port=item["host"],
                    embedding_timeout_s=2.5,
                )
            _, trace = retrieve_spec(task["prompt"], task["interface"], options)
            ids = [row["id"] for row in trace["retrieved"]]
            target_rejections = [row for row in trace["rejected"] if row.get("card_id") == card["card_id"]]
            routes[strategy] = {
                "top5": ids,
                "target_rank": ids.index(card["card_id"]) + 1 if card["card_id"] in ids else None,
                "target_rejections": target_rejections,
                "reason": trace["reason"],
                "error": trace.get("error"),
                "elapsed_ms": trace.get("elapsed_ms"),
                "embedding_ms": trace.get("embedding_ms"),
            }
        checks = {
            "positive_eligible": direct["positive"]["decision_class"] == "eligible",
            "known_not_needed": direct["known"]["decision_class"] == "not_needed",
            "conflicting_not_eligible": direct["conflicting"]["decision_class"] != "eligible",
            "insufficient_not_eligible": direct["insufficient"]["decision_class"] != "eligible",
            "tampered_failure": direct["tampered"]["decision_class"] == "failure",
            "bm25_top5": routes["bm25"]["target_rank"] is not None,
            "dense_top5": routes["dense"]["target_rank"] is not None,
            "shadow_blocks_bm25": any(r.get("reason") == "catalog_shadow_or_hold" for r in routes["bm25"]["target_rejections"]),
            "shadow_blocks_dense": any(r.get("reason") == "catalog_shadow_or_hold" for r in routes["dense"]["target_rejections"]),
        }
        rows.append(
            {
                "card_id": card["card_id"],
                "card_version": card["version"],
                "case_id": task["case_id"],
                "host": item["host"],
                "evidence": item["evidence"],
                "direct": direct,
                "routes": routes,
                "checks": checks,
                "passed": all(checks.values()),
            }
        )
    result = {
        "batch_id": batch["batch_id"],
        "base_release": data["release_id"],
        "count": len(rows),
        "passed": sum(row["passed"] for row in rows),
        "rows": rows,
        "model_calls": 0,
        "activation_changed": False,
        "boundary": "Routing and admission gate only. Real tokenizer/request identity and any missing model observation remain separate promotion requirements.",
    }
    (HERE / "route-results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key != "rows"}, ensure_ascii=False))
    for row in rows:
        print(row["card_id"], "passed=" + str(row["passed"]),
              "bm25=" + str(row["routes"]["bm25"]["target_rank"]),
              "dense=" + str(row["routes"]["dense"]["target_rank"]))
    if result["passed"] != result["count"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
