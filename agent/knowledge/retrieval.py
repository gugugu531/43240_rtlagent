"""Exact diagnostic retrieval with current-candidate and execution binding."""

from agent.rtl.result import checker_hash


def retrieve(cards, evidence, parent):
    result = {"reason": "no_current_code_failure", "hits": [], "rejected": [], "binding": None}
    if not evidence or parent is None:
        return [], result
    check = evidence["check"]
    result["binding"] = {
        "execution_id": evidence["execution_id"], "check_id": check.id,
        "candidate_id": check.candidate_id,
        "candidate_hash": check.details.get("candidate_hash"),
        "checker_hash": check.details.get("checker_hash"),
    }
    if (
        check.status != "failed" or check.failure_kind != "code"
        or check.kind not in ("lint", "synth") or not check.id
        or check.candidate_id != parent.id
        or check.details.get("candidate_hash") != parent.code_hash
        or check.details.get("checker_hash") != checker_hash()
    ):
        result["reason"] = "ineligible_or_stale_check"
        return [], result
    diagnostics = check.details.get("knowledge_diagnostics", {})
    if diagnostics.get("complete") is not True:
        result["reason"] = "incomplete_diagnostics"
        return [], result
    matches = []
    for card in sorted(cards, key=lambda item: item.id):
        code_matches = []
        for item in diagnostics.get("items", []):
            if item.get("severity") != "error" or item.get("cascade"):
                continue
            for trigger in card.triggers:
                if item.get("code") not in trigger.codes:
                    continue
                code_matches.append(item)
                if (
                    item.get("tool") in trigger.tools
                    and item.get("version") in trigger.versions
                    and item.get("process_status") == "failed"
                    and any(fragment.casefold() in item.get("message", "").casefold()
                            for fragment in trigger.message_contains_any)
                ):
                    matches.append(card)
                    result["hits"].append({
                        "id": card.id, "version": card.version,
                        "code": item["code"], "tool": item["tool"],
                        "tool_version": item["version"],
                        "command_index": item["command_index"],
                    })
                    break
            else:
                continue
            break
        if code_matches and card not in matches:
            result["rejected"].append({"id": card.id, "reason": "tool_version_or_message_mismatch"})
    result["reason"] = "matched" if matches else "no_match"
    result["omitted"] = [{"id": card.id, "reason": "injection_limit"} for card in matches[1:]]
    return matches[:1], result
