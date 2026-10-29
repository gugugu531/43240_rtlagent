"""Audit the two immutable routed observations returned by the cloud hosts."""
import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
NOTICE = (
    "The following material provides optional general methods, not task requirements or checker conclusions. "
    "Use it only when applicable. The original task, interface, and current tool evidence take precedence. "
    "Do not invent unspecified behavior or omit required modules. "
    "Continue to follow the RTL output format specified above."
)
EXPECTED = {
    33376: ("carry", "b51-route-carry", "v9-public-block-carry-chain", 2026105301, 257),
    33589: ("batch", "b51-route-batch", "v9-public-batch-final-sample", 2026105302, 292),
}


def load(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def audit_host(input_root, host):
    name, case_id, card_id, seed, extra_tokens = EXPECTED[host]
    returned = input_root / str(host)
    archive = returned / f"routed-results-{host}.tar.gz"
    receipt = load(returned / f"routed-results-{host}-receipt.json")
    base = returned / "extracted-r1" / name
    status = load(base / "status.json")
    meter = load(base / "call-meter.json")
    preflight = load(base / "preflight.json")
    bundle = load(ROOT / "knowledge/research-v3.json")
    card = next(row for row in bundle["cards"] if row["card_id"] == card_id)
    errors = []

    def check(condition, message):
        if not condition:
            errors.append(message)

    check(receipt == {
        "actual_calls": 2,
        "archive_bytes": archive.stat().st_size,
        "archive_sha256": sha(archive),
        "card_id": card_id,
        "case_id": case_id,
        "host": host,
        "status": "completed",
    }, "receipt_or_archive_identity")
    check(status.get("status") == "completed", "status_not_completed")
    check(status.get("automatic_retries") is False, "automatic_retry_enabled")
    check(meter == {"attempted_calls": 2, "max_calls": 2}, "call_meter")
    check(preflight.get("passed") is True and preflight.get("case_sha256"), "preflight")
    attempts = {row.get("arm"): row for row in status.get("attempts", [])}
    check(set(attempts) == {"control", "card"}, "arm_set")
    rows = []
    if set(attempts) == {"control", "card"}:
        control_request = load(base / "control" / "actual-request.json")
        card_request = load(base / "card" / "actual-request.json")
        expected_parameters = {
            "model": "qwen38-27b-q4-k-m",
            "seed": seed,
            "temperature": 0.0,
            "top_p": 1.0,
            "max_tokens": 16384,
            "chat_template_kwargs": {"enable_thinking": True},
        }
        for key, value in expected_parameters.items():
            check(control_request.get(key) == value and card_request.get(key) == value, "request_" + key)
        check(control_request.get("messages", [])[:-1] == card_request.get("messages", [])[:-1], "base_message_prefix")
        check(len(control_request.get("messages", [])) == 2 == len(card_request.get("messages", [])), "message_count")
        if len(control_request.get("messages", [])) == 2 and len(card_request.get("messages", [])) == 2:
            expected_user = control_request["messages"][-1]["content"] + "\n\n" + NOTICE + "\n\n" + card["projection_text"]
            check(card_request["messages"][-1]["content"] == expected_user, "card_projection_not_exact_append")
        for arm in ("control", "card"):
            row = attempts[arm]
            check(row.get("case_id") == case_id and row.get("card_id") == card_id, arm + "_identity")
            check(row.get("case_sha256") == preflight.get("case_sha256"), arm + "_case_hash")
            check(row.get("card_sha256") == fingerprint(card), arm + "_card_hash")
            check(row.get("success") is True and row.get("delivered") is True and row.get("error") is None, arm + "_outcome")
            check(row.get("generation_calls") == 1, arm + "_generation_calls")
            check(row.get("judge", {}).get("passed") is True, arm + "_judge")
            check(row.get("judge", {}).get("summary", {}).get("mismatches") == 0, arm + "_mismatches")
            sent = row.get("assembly", {}).get("sent")
            check(sent == ([] if arm == "control" else [card_id]), arm + "_sent")
            check(row.get("extra_tokens") == (None if arm == "control" else extra_tokens), arm + "_extra_tokens")
            for relative, digest in row.get("artifacts", {}).items():
                check(sha(base / arm / relative) == digest, arm + "_artifact_" + relative)
            rows.append({
                "arm": arm,
                "success": row.get("success"),
                "delivered": row.get("delivered"),
                "comparisons": row.get("judge", {}).get("summary", {}).get("comparisons"),
                "mismatches": row.get("judge", {}).get("summary", {}).get("mismatches"),
                "extra_tokens": row.get("extra_tokens"),
                "tokens_in": row.get("tokens_in"),
                "tokens_out": row.get("tokens_out"),
                "solution_sha256": row.get("solution_sha256"),
            })
    result = {
        "host": host,
        "case_id": case_id,
        "card_id": card_id,
        "card_version": card["version"],
        "card_sha256": fingerprint(card),
        "archive_sha256": sha(archive),
        "actual_arm_calls": meter.get("attempted_calls"),
        "automatic_retries": status.get("automatic_retries"),
        "request_parameters_frozen": not any(error.startswith("request_") for error in errors),
        "exact_card_append": "card_projection_not_exact_append" not in errors,
        "rows": rows,
        "errors": errors,
        "status": "passed" if not errors else "failed",
    }
    (HERE / f"routed-audit-{host}.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def context_reuse_check():
    tasks49 = load(ROOT / "dev/optimization-v49/tasks.json")["tasks"]
    tasks51 = load(ROOT / "dev/optimization-v51/tasks.json")["tasks"]
    old = next(row for row in tasks49 if row["case_id"] == "b49-11")
    current = next(row for row in tasks51 if row["case_id"] == "b51-019")
    fields = ("prompt", "interface", "target", "reference", "adjacent", "bench")
    same = all(old[field] == current[field] for field in fields)
    audit = load(ROOT / "dev/optimization-v49/audit-33589.json")
    row = next(row for row in audit["rows"] if row["case_id"] == "b49-11")
    card = next(row for row in load(ROOT / "knowledge/research-v3.json")["cards"]
                if row["card_id"] == "v9-lang-context-before-operation")
    return {
        "status": "passed" if same and audit["status"] == "passed" and row["outcome"] == "both_pass"
                  and row["version"] == card["version"] else "failed",
        "source_case_id": "b49-11",
        "current_fixture_id": "b51-019",
        "identical_fields": list(fields) if same else [],
        "outcome": row["outcome"],
        "card_version": card["version"],
        "card_sha256": fingerprint(card),
    }


def main(input_root):
    audits = [audit_host(input_root, host) for host in sorted(EXPECTED)]
    context = context_reuse_check()
    summary = {
        "status": "passed" if all(row["status"] == "passed" for row in audits) and context["status"] == "passed" else "failed",
        "routed_model_pairs": audits,
        "context_reused_pair": context,
        "candidate_promotions": [
            "v9-lang-context-before-operation",
            "v9-public-batch-final-sample",
            "v9-public-block-carry-chain",
        ],
        "actual_arm_calls": sum(row["actual_arm_calls"] for row in audits),
        "activation_changed": False,
    }
    (HERE / "model-audit-summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=2))
    if summary["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", type=Path, required=True)
    main(parser.parse_args().input_root)
