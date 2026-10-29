"""Promote only the three cards that passed the complete v53 gate."""
from collections import Counter
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT / "dev/optimization-v42"), str(ROOT)]

from common42 import fingerprint, load, save, sha
from agent.knowledge.research import (
    RESEARCH_RELEASE,
    implementation_hash,
    load_bundle,
    validate_bundle,
    validate_vector_index,
)


PROMOTE = {
    "v9-lang-context-before-operation": {
        "model_audit": "dev/optimization-v49/audit-33589.json",
        "case_id": "b49-11",
        "route_case_id": "b51-019",
        "model_evidence_kind": "same_version_identical_fixture_reuse",
    },
    "v9-public-batch-final-sample": {
        "model_audit": "dev/optimization-v53/routed-audit-33589.json",
        "case_id": "b51-route-batch",
        "model_evidence_kind": "new_routed_context_pair",
    },
    "v9-public-block-carry-chain": {
        "model_audit": "dev/optimization-v53/routed-audit-33376.json",
        "case_id": "b51-route-carry",
        "model_evidence_kind": "new_routed_context_pair",
    },
}


def artifact(path):
    return {"path": path, "sha256": sha((ROOT / path).read_bytes())}


def run():
    assert RESEARCH_RELEASE == "rag-catalog-v3-rc4.3"
    route = load(HERE / "route-results.json")
    tokenizer = load(HERE / "tokenizer-results.json")
    model = load(HERE / "model-audit-summary.json")
    assert route["base_release"] == "rag-catalog-v3-rc4.2"
    assert route["passed"] == 3 and {row["card_id"] for row in route["rows"] if row["passed"]} == set(PROMOTE)
    assert tokenizer["passed"] == tokenizer["count"] == 10
    assert model["status"] == "passed" and set(model["candidate_promotions"]) == set(PROMOTE)
    assert model["actual_arm_calls"] == 4

    data = load(ROOT / "knowledge/research-v3.json")
    assert data["release_id"] == "rag-catalog-v3-rc4.2"
    save(HERE / "prior-bundle.json", data)
    for name in ("catalog-v3.json", "research-v3-lock.json", "research-v3-vectors-lock.json"):
        save(HERE / ("prior-" + name), load(ROOT / "knowledge" / name))

    route_rows = {row["card_id"]: row for row in route["rows"]}
    token_rows = {row["card_id"]: row for row in tokenizer["rows"]}
    mapping = {card["card_id"]: card for card in data["cards"]}
    changes = []
    for card_id, evidence in PROMOTE.items():
        card = mapping[card_id]
        assert card["activation_state"] == "shadow" and card["injection_eligible"] is True
        assert route_rows[card_id]["passed"] is True
        assert route_rows[card_id]["direct"]["positive"]["card_sha256"] == fingerprint(card)
        assert token_rows[card_id]["passed"] is True and token_rows[card_id]["tokens"] <= 1024
        model_audit = load(ROOT / evidence["model_audit"])
        if evidence["model_evidence_kind"] == "new_routed_context_pair":
            assert model_audit["status"] == "passed" and model_audit["card_sha256"] == fingerprint(card)
            assert all(row["success"] and row["delivered"] and row["mismatches"] == 0 for row in model_audit["rows"])
        else:
            assert model_audit["status"] == "passed"
            row = next(row for row in model_audit["rows"] if row["case_id"] == evidence["case_id"])
            assert row["version"] == card["version"] and row["outcome"] == "both_pass"
        card["activation_state"] = "restricted"
        card["injection_stages"] = ["pre_generation"]
        card["feedback_contract"]["status"] = "restricted_pre_generation_only"
        card["publication_evidence"]["v53_restricted_promotion"] = {
            "routing_and_admission": artifact("dev/optimization-v53/route-results.json"),
            "tokenizer_budget": artifact("dev/optimization-v53/tokenizer-results.json"),
            "model_audit": artifact(evidence["model_audit"]),
            "case_id": evidence["case_id"],
            "route_case_id": evidence.get("route_case_id", evidence["case_id"]),
            "model_evidence_kind": evidence["model_evidence_kind"],
            "observed_card_sha256": route_rows[card_id]["direct"]["positive"]["card_sha256"],
            "bm25_rank": route_rows[card_id]["routes"]["bm25"]["target_rank"],
            "dense_rank": route_rows[card_id]["routes"]["dense"]["target_rank"],
            "projection_tokens": token_rows[card_id]["tokens"],
            "stage_restriction": "pre_generation_only",
            "defaults_changed": False,
        }
        changes.append({"card_id": card_id, "from": "shadow", "to": "restricted", "injection_stages": ["pre_generation"]})

    data["release_id"] = RESEARCH_RELEASE
    for row in data["documents"] + data["rules"]:
        card = mapping[row["card_id"]]
        row["card_sha256"] = fingerprint(card)
        if "activation_state" in row:
            row["activation_state"] = card["activation_state"]
    save(ROOT / "knowledge/research-v3.json", data)

    catalog = load(ROOT / "knowledge/catalog-v3.json")
    catalog.update(release_id=RESEARCH_RELEASE, cards_sha256=fingerprint(data["cards"]))
    for entry in catalog["entries"]:
        card = mapping[entry["card_id"]]
        entry.update(card_sha256=fingerprint(card), state=card["activation_state"], phases=card["phases"])
        if entry["card_id"] in PROMOTE:
            entry["policy_adapter"] = "reviewed_public_specification"
    save(ROOT / "knowledge/catalog-v3.json", catalog)

    lock = load(ROOT / "knowledge/research-v3-lock.json")
    lock.update(
        release_id=RESEARCH_RELEASE,
        bundle_sha256=sha((ROOT / "knowledge/research-v3.json").read_bytes()),
        catalog_sha256=sha((ROOT / "knowledge/catalog-v3.json").read_bytes()),
        cards_sha256=fingerprint(data["cards"]),
        policy_sha256=fingerprint(data["rules"]),
        index_sha256=fingerprint(data["documents"]),
        implementation_sha256=implementation_hash(),
    )
    validate_bundle(data, lock, load(ROOT / "knowledge/research-scope.json"))
    save(ROOT / "knowledge/research-v3-lock.json", lock)

    index = load(ROOT / "knowledge/research-v3-vectors.json")
    documents = {row["card_id"]: row for row in data["documents"]}
    assert all(row["text_sha256"] == documents[row["card_id"]]["text_sha256"] for row in index["vectors"])
    index.update(release_id=RESEARCH_RELEASE, documents_sha256=fingerprint(data["documents"]))
    validate_vector_index(index, data)
    save(ROOT / "knowledge/research-v3-vectors.json", index)
    save(ROOT / "knowledge/research-v3-vectors-lock.json", {
        "release_id": RESEARCH_RELEASE,
        "sha256": sha((ROOT / "knowledge/research-v3-vectors.json").read_bytes()),
    })

    load_bundle.cache_clear()
    load_bundle()
    states = dict(Counter(card["activation_state"] for card in data["cards"]))
    note = {
        "release_id": RESEARCH_RELEASE,
        "base_release": "rag-catalog-v3-rc4.2",
        "changes": changes,
        "states": states,
        "restricted_count": states["restricted"],
        "first_batch_size": 10,
        "promoted": 3,
        "deferred": 7,
        "actual_new_arm_calls": 4,
        "all_promotions_pre_generation_only": True,
        "defaults_changed": False,
        "embedding_vectors_reused": 129,
        "card_projection_text_changed": False,
        "original_39_still_frozen": True,
    }
    save(HERE / "release-note.json", note)
    print(note)


if __name__ == "__main__":
    run()
