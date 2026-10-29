"""One immutable two-arm routed-first observation on one cloud host."""
import argparse
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
import sys
import tarfile
import urllib.request


V52 = Path("/root/rtl-rag-cohort52-20261029-r1")
V51 = Path("/root/rtl-rag-mechanical51-20261029-r2")
HERE51 = V51 / "dev/optimization-v51"
sys.path[:0] = [str(V52 / "dev/optimization-v42"), str(V52 / "dev/optimization-v37"), str(V52)]

from common42 import fingerprint, load, save, sha
from worker42 import attempt


ASSIGNMENTS = {
    33376: "b51-route-carry",
    33589: "b51-route-batch",
}


def health():
    with urllib.request.urlopen("http://127.0.0.1:8010/health", timeout=5) as response:
        service = json.load(response)
    with urllib.request.urlopen("http://127.0.0.1:8010/slots", timeout=5) as response:
        slots = json.load(response)
    return service.get("status") == "ok" and not any(row.get("is_processing") for row in slots)


def run(host, output):
    case_id = ASSIGNMENTS[host]
    tasks = load(HERE51 / "tasks.json")["tasks"]
    case = next(row for row in tasks if row["case_id"] == case_id)
    card = next(row for row in load(HERE51 / "candidate-bundle.json")["cards"] if row["card_id"] == case["card_id"])
    mechanical = load(HERE51 / "runs" / str(host) / "cases" / case_id / "result.json")
    if mechanical["status"] != "model_ready" or not mechanical["simulation"]["passed"]:
        raise ValueError("mechanical_prerequisite_missing")
    if mechanical["case_sha256"] != fingerprint(case) or mechanical["card_sha256"] != fingerprint(card):
        raise ValueError("mechanical_identity_mismatch")
    output.mkdir(parents=True, exist_ok=False)
    state = {
        "host": host,
        "case_id": case_id,
        "card_id": card["card_id"],
        "status": "running",
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "automatic_retries": False,
        "attempts": [],
    }
    save(output / "status.json", state)
    meter = {"attempted_calls": 0, "max_calls": 2}
    save(output / "call-meter.json", meter)
    preflight = {
        "passed": True,
        "checks": mechanical["simulation"]["checks"],
        "case_sha256": fingerprint(case),
        "source": "independently_audited_v51_r2_mechanical_result",
    }
    save(output / "preflight.json", preflight)
    try:
        with Path("/root/rtlagent-v12-model-8010.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if not health():
                raise RuntimeError("model_not_idle")
            arms = ["control", "card"] if host == 33376 else ["card", "control"]
            seed = 2026105300 + (1 if host == 33376 else 2)
            for arm in arms:
                row = attempt(case, card, preflight, arm, output / arm, meter, seed)
                state["attempts"].append(row)
                save(output / "status.json", state)
        state["status"] = "completed"
    except Exception as error:
        state.update(status="infrastructure_failure", error=type(error).__name__ + ": " + str(error))
    finally:
        state["finished_utc"] = datetime.now(timezone.utc).isoformat()
        save(output / "status.json", state)
    archive = output.parent / ("routed-results-" + str(host) + ".tar.gz")
    with tarfile.open(archive, "w:gz") as tar:
        for path in output.rglob("*"):
            if path.is_file() and "xsim.dir" not in path.parts and path.suffix not in (".pb", ".jou"):
                tar.add(path, arcname=str(path.relative_to(output.parent)), recursive=False)
        for path in (HERE51 / "tasks.json", HERE51 / "candidate-bundle.json"):
            tar.add(path, arcname=path.name, recursive=False)
    receipt = {
        "host": host,
        "case_id": case_id,
        "card_id": card["card_id"],
        "archive_sha256": sha(archive.read_bytes()),
        "archive_bytes": archive.stat().st_size,
        "actual_calls": meter["attempted_calls"],
        "status": state["status"],
    }
    save(output.parent / ("routed-results-" + str(host) + "-receipt.json"), receipt)
    print(json.dumps(receipt))
    if state["status"] != "completed" or meter["attempted_calls"] != 2:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", type=int, choices=sorted(ASSIGNMENTS), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.host, args.output)
