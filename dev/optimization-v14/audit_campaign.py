"""Read-only audit of balanced60, Skill v12, and RAG v12/v13 results."""
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "dev/optimization-v14"


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return sha_bytes(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode())


def read(path):
    return json.loads(Path(path).read_text())


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    temp.replace(path)


def generation_exchange(folder):
    requests = []
    for path in Path(folder).rglob("request.json"):
        request = read(path)
        if request.get("url", "").endswith("/v1/chat/completions"):
            response = read(path.with_name("response.json"))
            requests.append((path, request, response))
    return sorted(requests, key=lambda item: str(item[0]))


def token_total(row):
    usage = row["usage"]
    return usage["tokens_in"] + usage["tokens_out"]


def metrics(rows):
    rows = list(rows)
    known = [token_total(row) for row in rows]
    success = sum(row["attribution"]["attempt_success"] is True for row in rows)
    return dict(
        attempts=len(rows),
        delivered=sum(row["complete_new_draft"] is True for row in rows),
        checker_accepted=sum(row["checker_accepted"] is True for row in rows),
        success=success,
        errors=sum(bool(row["error"]) for row in rows),
        total_tokens=sum(known),
        tokens_per_success=(sum(known) / success if success else None),
        wall_s=sum(row["wall_s"] for row in rows),
        max_tokens=max(known, default=None),
        outcomes=dict(Counter(row["attribution"]["outcome"] for row in rows)),
    )


def audit_single_call_campaign(name, run_root, manifest_path):
    run_root = Path(run_root)
    status = read(run_root / "status.json")
    manifest = read(manifest_path)
    expected = [job for pair in manifest["pairs"] for job in pair["jobs"]]
    expected_ids = [job["id"] for job in expected]
    rows = status["completed"]
    actual_ids = [row["job"]["id"] for row in rows]
    failures = []
    reasoning = {}
    response_content = {}
    request_messages = {}
    request_payload_sha = {}
    per_attempt = {}
    for row in rows:
        job_id = row["job"]["id"]
        folder = run_root / job_id
        exchanges = generation_exchange(folder)
        if len(exchanges) != 1:
            failures.append(f"{job_id}: generation exchanges={len(exchanges)}")
            continue
        path, request, response = exchanges[0]
        payload = request["payload"]
        message = response["choices"][0]["message"]
        request_messages[job_id] = payload["messages"]
        request_payload_sha[job_id] = canonical(payload)
        reasoning[job_id] = message.get("reasoning_content") or ""
        response_content[job_id] = message.get("content") or ""
        final_paths = list(folder.rglob("final-messages.json"))
        checks = {
            "thinking": payload.get("chat_template_kwargs", {}).get("enable_thinking") is True,
            "temperature": payload.get("temperature") == 0,
            "top_p": payload.get("top_p") == 1,
            "seed": payload.get("seed") == manifest["seed"],
            "max_tokens": payload.get("max_tokens") == manifest["max_output_per_call"],
            "model": payload.get("model") == manifest["model"],
            "reasoning_present": bool(reasoning[job_id].strip()),
            "one_final_messages": len(final_paths) == 1,
            "final_messages_equal_request": len(final_paths) == 1 and read(final_paths[0]) == payload["messages"],
            "delivery_thinking": row["delivery"]["phases"][0]["thinking"] is True,
            "delivery_one_call": row["usage"]["calls"] == 1,
            "usage_known": row["usage"]["unknown_tokens_in_calls"] == 0 and row["usage"]["unknown_tokens_out_calls"] == 0,
            "attribution_thinking": row["attribution"]["thinking_on_verified"] is True,
        }
        if row["complete_new_draft"] and row["checker_accepted"]:
            checks.update(
                draft_selected=row["draft_sha256"] == row["selected_sha256"],
                solution_hash=sha_bytes((folder / "solution.v").read_bytes()) == row["draft_sha256"],
            )
        elif row["complete_new_draft"]:
            checks.update(
                rejected_draft_not_scored=row.get("judge") is None and row["attribution"]["attempt_success"] is False,
                retained_solution_hash=sha_bytes((folder / "solution.v").read_bytes()) == row["selected_sha256"],
            )
        if row.get("judge"):
            checks.update(
                judge_source=row["judge"]["source_sha256"] == row["draft_sha256"],
                judge_input_before=row["judge_input_sha256"] == row["draft_sha256"],
                judge_input_after=row["judge_input_sha256_after"] == row["draft_sha256"],
            )
        bad = [key for key, value in checks.items() if not value]
        if bad:
            failures.append(f"{job_id}: " + ",".join(bad))
        per_attempt[job_id] = dict(
            checks=checks,
            finish_reason=row["finish_reason"],
            delivered=row["complete_new_draft"],
            checker_accepted=row["checker_accepted"],
            success=row["attribution"]["attempt_success"],
            outcome=row["attribution"]["outcome"],
            tokens=token_total(row),
            wall_s=row["wall_s"],
            reasoning_characters=len(reasoning[job_id]),
            final_characters=len(response_content[job_id]),
        )
    by_id = {row["job"]["id"]: row for row in rows}
    pair_audit = []
    for pair in manifest["pairs"]:
        pair_rows = [by_id[job["id"]] for job in pair["jobs"]]
        control = next(row for row in pair_rows if row["job"]["arm"] == "control")
        knowledge = next(row for row in pair_rows if row["job"]["arm"] == "knowledge")
        a = control["job"]["id"]
        b = knowledge["job"]["id"]
        same_messages = request_messages[a] == request_messages[b]
        expected_same = pair["condition"] == "fact_already_provided"
        base_same = control["assembly"]["base_messages_sha256"] == knowledge["assembly"]["base_messages_sha256"]
        if same_messages != expected_same or not base_same:
            failures.append(f"{pair['id']}: pair message contract")
        control_success = control["attribution"]["attempt_success"] is True
        knowledge_success = knowledge["attribution"]["attempt_success"] is True
        pair_audit.append(dict(
            pair_id=pair["id"], case=pair["case"], condition=pair["condition"],
            feedback_view=pair["feedback_view"], knowledge_id=pair["knowledge_id"],
            execution_batch=pair.get("execution_batch"), base_messages_equal=base_same,
            actual_messages_equal=same_messages, responses_equal=(reasoning[a], response_content[a]) == (reasoning[b], response_content[b]),
            code_equal=(control.get("draft_sha256") == knowledge.get("draft_sha256") if control["complete_new_draft"] and knowledge["complete_new_draft"] else None),
            control=dict(success=control_success, delivered=control["complete_new_draft"], checker=control["checker_accepted"], tokens=token_total(control), wall_s=control["wall_s"], job_id=a),
            knowledge=dict(success=knowledge_success, delivered=knowledge["complete_new_draft"], checker=knowledge["checker_accepted"], tokens=token_total(knowledge), wall_s=knowledge["wall_s"], job_id=b),
            success_delta=int(knowledge_success)-int(control_success),
            token_delta=token_total(knowledge)-token_total(control),
            token_change_fraction=(token_total(knowledge)/token_total(control)-1 if token_total(control) else None),
        ))
    grouped = {}
    dimensions = ["condition", "feedback_view", "knowledge_id", "case"]
    for field in dimensions:
        grouped[field] = {}
        values = sorted({row["job"][field] for row in rows})
        for value in values:
            selected = [row for row in rows if row["job"][field] == value]
            grouped[field][value] = {arm: metrics(row for row in selected if row["job"]["arm"] == arm) for arm in ("control", "knowledge")}
    positives = [p for p in pair_audit if p["condition"] == "fact_gap_hypothesis" and p["success_delta"] > 0]
    negatives = [p for p in pair_audit if p["condition"] == "fact_gap_hypothesis" and p["success_delta"] < 0]
    same_success = [p for p in pair_audit if p["condition"] == "fact_gap_hypothesis" and p["control"]["success"] and p["knowledge"]["success"]]
    same_failure = [p for p in pair_audit if p["condition"] == "fact_gap_hypothesis" and not p["control"]["success"] and not p["knowledge"]["success"]]
    provided = [p for p in pair_audit if p["condition"] == "fact_already_provided"]
    result = dict(
        name=name, status=status["status"], planned=manifest["maximum_calls"], completed=len(rows), pairs=len(pair_audit),
        expected_job_ids_unique=len(set(expected_ids)) == len(expected_ids), actual_job_ids_unique=len(set(actual_ids)) == len(actual_ids),
        missing_jobs=sorted(set(expected_ids)-set(actual_ids)), extra_jobs=sorted(set(actual_ids)-set(expected_ids)),
        mechanical_failures=failures, all_attempts=metrics(rows), grouped=grouped, pairs_detail=pair_audit,
        gap_pair_outcomes=dict(positive=len(positives), negative=len(negatives), both_success=len(same_success), both_failure=len(same_failure)),
        correct_empty_contract=dict(pairs=len(provided), actual_messages_equal=sum(p["actual_messages_equal"] for p in provided),
                                    responses_equal=sum(p["responses_equal"] for p in provided), code_equal=sum(p["code_equal"] is True for p in provided)),
        notable_pairs=dict(
            positive=positives,
            negative=negatives,
            largest_savings=sorted(same_success, key=lambda p: p["token_delta"])[:8],
            largest_cost_increases=sorted(same_success, key=lambda p: p["token_delta"], reverse=True)[:8],
            both_failure=same_failure,
        ),
        attempts=per_attempt,
    )
    return result, reasoning, response_content


def balanced_audit(root):
    root = Path(root)
    status = read(root / "status.json")
    manifest = read(ROOT / "dev/optimization-v6/manifest.json")
    solved = {(row["task_id"], row["arm"]): row for row in status["solved"]}
    graded = {(row["task_id"], row["arm"]): row for row in status["graded"]}
    failures = []
    reasoning = {}
    tasks = []
    all_generation = []
    for task_id in manifest["tasks"]:
        arms = {}
        for arm in ("off", "rag-on"):
            solve = solved[(task_id, arm)]
            grade = graded[(task_id, arm)]
            folder = root / "solves" / (task_id + "--" + arm)
            exchanges = generation_exchange(folder)
            actual_requests = []
            actual_responses = []
            for path, request, response in exchanges:
                payload = request["payload"]
                message = response["choices"][0]["message"]
                checks = {
                    "thinking": payload.get("chat_template_kwargs", {}).get("enable_thinking") is True,
                    "temperature": payload.get("temperature") == 0,
                    "seed": payload.get("seed") == manifest["seed"],
                    "max_tokens": payload.get("max_tokens") == 16384,
                    "reasoning_present": bool((message.get("reasoning_content") or "").strip()),
                }
                if not all(checks.values()):
                    failures.append(f"{task_id}/{arm}/{path}: {checks}")
                actual_requests.append(payload)
                actual_responses.append(message)
                all_generation.append((task_id, arm, path, checks))
            if len(exchanges) != solve["audit"]["end"]["calls"]:
                failures.append(f"{task_id}/{arm}: generation exchanges={len(exchanges)} expected={solve['audit']['end']['calls']}")
            reasoning[(task_id, arm)] = [message.get("reasoning_content") or "" for message in actual_responses]
            result = grade["grade"]["result"]
            fw = solve["audit"]["framework"]
            input_hash = grade["grade"]["input_sha256"]
            if not (input_hash == grade["grade"]["input_sha256_after"] == fw["solution_sha256"] == solve["audit"]["selected_sha256"]):
                failures.append(f"{task_id}/{arm}: score identity mismatch")
            arms[arm] = dict(
                level=result["level"], functional=result["stages"]["simulate"], stages=result["stages"],
                tool_error=result["tool_error"], delivered=solve["audit"]["delivered"], final_complete=solve["audit"]["final_complete"],
                stop_reason=solve["audit"]["end"]["stop_reason"], calls=solve["audit"]["end"]["calls"],
                tokens=solve["audit"]["end"]["tokens_in"]+solve["audit"]["end"]["tokens_out"],
                selected_sha256=solve["audit"]["selected_sha256"], sent=[card for assembly in fw["assemblies"] for card in assembly.get("sent", [])],
                empty_kinds=[assembly.get("retrieval", {}).get("kind", assembly.get("retrieval", {}).get("reason")) for assembly in fw["assemblies"]],
                request_count=len(actual_requests), request_payloads=actual_requests, response_messages=actual_responses,
                folder=str(folder.relative_to(ROOT)),
            )
        same_requests=arms["off"]["request_payloads"] == arms["rag-on"]["request_payloads"]
        same_responses=arms["off"]["response_messages"] == arms["rag-on"]["response_messages"]
        same_score=arms["off"]["level"] == arms["rag-on"]["level"]
        same_code=arms["off"]["selected_sha256"] == arms["rag-on"]["selected_sha256"]
        tasks.append(dict(task_id=task_id, off={k:v for k,v in arms["off"].items() if k not in ("request_payloads","response_messages")},
                          rag_on={k:v for k,v in arms["rag-on"].items() if k not in ("request_payloads","response_messages")},
                          requests_equal=same_requests,responses_equal=same_responses,score_equal=same_score,code_equal=same_code))
    failed = [row for row in tasks if row["off"]["level"] < 3]
    return dict(
        status=status["status"], tasks=len(manifest["tasks"]), solved=len(status["solved"]), graded=len(status["graded"]),
        generation_calls=len(all_generation), mechanical_failures=failures,
        paired_identity=dict(requests_equal=sum(r["requests_equal"] for r in tasks),responses_equal=sum(r["responses_equal"] for r in tasks),
                             code_equal=sum(r["code_equal"] for r in tasks),score_equal=sum(r["score_equal"] for r in tasks)),
        levels=dict(Counter(row["off"]["level"] for row in tasks)),
        delivered=sum(row["off"]["delivered"] for row in tasks),
        tokens=sum(row["off"]["tokens"] for row in tasks),
        sent_cards=sorted({card for row in tasks for card in row["rag_on"]["sent"]}),
        failed_tasks=failed,tasks_detail=tasks,
    ), reasoning


def main():
    skill, skill_reasoning, skill_content = audit_single_call_campaign(
        "skill-v12", ROOT/"dev/optimization-v12/runs/overnight-skill-v12-1", ROOT/"dev/optimization-v12/manifest-skill.json")
    rag12, rag12_reasoning, rag12_content = audit_single_call_campaign(
        "rag-v12", ROOT/"dev/optimization-v12/runs/overnight-rag-v12-1", ROOT/"dev/optimization-v12/manifest-rag.json")
    rag13, rag13_reasoning, rag13_content = audit_single_call_campaign(
        "rag-v13", ROOT/"dev/optimization-v13/runs/rag-ten-batches-v13-1", ROOT/"dev/optimization-v13/manifest-rag.json")
    balanced, balanced_reasoning = balanced_audit(ROOT/"dev/optimization-v6/runs/repair-chain-balanced60-20261026-v6-1")
    report=dict(status="passed" if not any(x["mechanical_failures"] for x in (skill,rag12,rag13,balanced)) else "failed",
                balanced60=balanced,skill=skill,rag_v12=rag12,rag_v13=rag13)
    save(OUT/"campaign-audit.json",report)
    # Store compact reasoning indices, never treat them as verified causal labels.
    index={"skill":skill_reasoning,"rag_v12":rag12_reasoning,"rag_v13":rag13_reasoning,
           "balanced60":{"|".join(key):value for key,value in balanced_reasoning.items()}}
    save(OUT/"reasoning-index.json",index)
    print(json.dumps({"status":report["status"],"mechanical_failures":{k:len(report[k]["mechanical_failures"]) for k in ("balanced60","skill","rag_v12","rag_v13")},
                      "balanced_failed":len(balanced["failed_tasks"]),"skill":skill["gap_pair_outcomes"],
                      "rag_v12":rag12["gap_pair_outcomes"],"rag_v13":rag13["gap_pair_outcomes"]},indent=2))


if __name__ == "__main__":
    main()
