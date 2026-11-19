"""Strategy, author and independent checker for the guided RTL workflow."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
import time

from agent.kit import Ctx, State, node
from agent.llm.client import ModelError
from agent.runtime.allowance import CompletionLedger
from agent.domain.rtl.extract import extract_result
from agent.domain.rtl.guided_author import (
    AuthorDecisionError, author_decision_request, author_history, parse_author_decision,
)
from agent.domain.rtl.guided_checker import (
    CheckerError,
    checker_contract,
    checker_request,
    evaluate_checker,
    parse_checker,
)
from agent.domain.rtl.guided_plan import Plan, PlanError, parse_plan, plan_request
from agent.domain.rtl.guided_revision import apply_checker_review, checker_review_request
from agent.domain.rtl.observation import observe
from agent.domain.rtl.result import CheckResult, bind_result, checker_hash as checker_version, tool_succeeded
from agent.submission.gateway import SubmissionGateway
from agent.roles import profile_for_stage, role_for_stage
from agent.domain.knowledge.assets import load_assets
from agent.domain.knowledge import guided as knowledge
from agent.domain.knowledge.policy import select_skills


def _g(ctx):
    return ctx.store["guided"]


def _checker_limits(ctx):
    settings = _g(ctx)["settings"]
    return {
        "max_cases": settings.get("max_cases", 4),
        "max_steps": settings.get("max_steps_per_case", 8),
        "init_cycles": settings.get("init_cycles", 2),
    }


def _checker_execution(ctx):
    """Public stimulus/index mapping, never measured outputs or candidate RTL."""
    data = _g(ctx)
    return {
        "contract": checker_contract(ctx.task, **_checker_limits(ctx)),
        "sampling_plan": data["checker"].plan,
    }


def _save(ctx, name, value):
    # Trace links must keep the value at this event, even when a checker is
    # rebuilt for the same candidate. Keep the old location as a latest-value
    # view for consumers that read the final run directory directly.
    data = _g(ctx)
    revision = data.get("artifact_revision", 0) + 1
    data["artifact_revision"] = revision
    path = ctx.record.write_json(
        f"guided/history/{revision:06d}/{name}.json", value
    )
    ctx.record.write_json(f"guided/{name}.json", value)
    ctx.record.emit(
        "guided", "artifact", name=name, path=path, revision=revision,
        status=value.get("status") if isinstance(value, dict) else None,
    )


def _checker_fingerprint(checker):
    """Stable identity for the plan and expected values, not just the plan hash."""
    payload = json.dumps(
        checker.public_dict(), sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _attempt_stage(base, attempt):
    return base if attempt == 1 else f"{base}_{attempt}"


def _behavior_for(data, candidate_id):
    """Return behavior only when it was produced by the current checker."""
    record = data.get("behaviors", {}).get(candidate_id)
    assessment = data["assessments"].get(candidate_id) or {}
    if (not record or not data.get("checker_hash")
            or record["candidate_hash"] != assessment.get("candidate_hash")
            or record["checker_hash"] != data["checker_hash"]
            or record["checker_version"] != data["checker_version"]):
        return {}
    return record.get("behavior") or {}


def _request(ctx, stage, messages, limits, *, followup_s=0, optional=False):
    data = _g(ctx)
    if stage in data["attempted"]:
        raise ValueError(f"guided stage may only request once: {stage}")
    data["attempted"].add(stage)
    remaining_tokens = data["ledger"].snapshot()["output_tokens_remaining"]
    if remaining_tokens and (limits["max_tokens"] is None or remaining_tokens < limits["max_tokens"]):
        limits = {**limits, "max_tokens": remaining_tokens}
    permit = data["ledger"].reserve(
        stage, **limits, followup_s=followup_s, optional=optional,
        min_timeout_s=min(limits["timeout_s"], data["settings"].get("minimum_request_s", 20)),
    )
    if permit is None:
        data["request_outcomes"][stage] = {
            "status": "not_sent", "reason": data["ledger"].last_denial,
        }
        _save(ctx, "request-outcomes", data["request_outcomes"])
        return None
    try:
        with ctx.llm.permitted(permit):
            reply = ctx.llm.chat(
                messages,
                purpose=f"guided_{stage}",
                temperature=data["settings"]["temperature"],
                top_p=data["settings"]["top_p"],
                profile=profile_for_stage(stage) or None,
                **{**limits, "timeout_s": permit.timeout_s},
            )
        data["request_outcomes"][stage] = {
            "status": "returned", "call_id": reply.call_id,
            "finish_reason": reply.finish_reason,
            "profile": profile_for_stage(stage) or None,
            "model": getattr(reply, "model", None),
        }
        return reply
    except ModelError as error:
        data["request_outcomes"][stage] = {
            "status": "error", "kind": error.kind, "reason": str(error),
            "call_id": error.call_id,
        }
        ctx.record.emit("guided", "request_failed", stage=stage, kind=error.kind,
                        reason=str(error))
        return None
    finally:
        _save(ctx, "completion-ledger", data["ledger"].snapshot())
        _save(ctx, "request-outcomes", data["request_outcomes"])


def _empty_failure(reply):
    """Only a confirmed stop/length with no final body permits recovery."""
    if reply is None or reply.content.strip():
        return None
    return {
        "stop": "stop_no_final",
        "length": "length_no_final",
    }.get(reply.finish_reason, "empty_unknown_finish")


def _response_failure(ctx, stage, reply, kind, **details):
    failure = {
        "kind": kind, "source_call_id": reply.call_id,
        "finish_reason": reply.finish_reason, **details,
    }
    outcomes = _g(ctx).setdefault("request_outcomes", {})
    outcomes.setdefault(stage, {}).update({"failure_kind": kind})
    _save(ctx, f"{stage}-failure", failure)
    _save(ctx, "request-outcomes", outcomes)
    return failure


def _recover_empty(ctx, stage, reply, make_messages, limits):
    """Recover confirmed empty responses within the shared budget."""
    data = _g(ctx)
    attempt_key = f"{stage}_recovery_attempts"
    recovered = None
    seen = {}
    while _empty_failure(reply) in ("stop_no_final", "length_no_final"):
        if stage == "checker" and _leave_author_call(data):
            break
        kind = _empty_failure(reply)
        data[attempt_key] = data.get(attempt_key, 0) + 1
        messages = make_messages()
        messages[-1]["content"] += (
            "\n\nA previous independent request returned no final answer. "
            f"Failure category: {kind}. "
            "Produce the requested complete final artifact in this response. "
            "Do not reproduce analysis, stimulus drafts, or an unfinished artifact."
        )
        recovery_stage = _attempt_stage(f"{stage}_recovery", data[attempt_key])
        recovered = _request(
            ctx, recovery_stage, messages, limits,
            followup_s=data["settings"]["first_tools_s"], optional=True,
        )
        # Count actual completion sends, excluding metadata preparation calls.
        prefix = f"{stage}_recovery"
        permits = data["ledger"].snapshot()["permits"]
        data[f"{stage}_recoveries_sent"] = sum(
            (permit["stage"] == prefix or permit["stage"].startswith(prefix + "_"))
            and permit["call_id"] is not None
            for permit in permits
        )
        if recovered is None:
            break
        if _empty_failure(recovered):
            _response_failure(ctx, recovery_stage, recovered, _empty_failure(recovered))
            sent_limit = next((p.get("sent_max_tokens") for p in permits
                               if p["call_id"] == recovered.call_id), None)
            visible = [messages, sent_limit, getattr(recovered, "model", None),
                       recovered.finish_reason, recovered.content, getattr(recovered, "reasoning", {}),
                       getattr(recovered, "tool_calls", []), getattr(recovered, "tokens_out", None)]
            digest = hashlib.sha256(json.dumps(visible, sort_keys=True).encode()).hexdigest()
            if digest in seen:
                if stage == "solve":
                    data["stop_detail"] = "repeated_empty_recovery"
                _save(ctx, "recovery-no-progress", {
                    "reason": "repeated_empty_recovery", "stage": recovery_stage,
                    "previous_call_id": seen[digest], "call_id": recovered.call_id,
                    "visible_request_response_hash": digest,
                })
                break
            seen[digest] = recovered.call_id
        reply = recovered
    return recovered


def _candidate(ctx, reply, *, parent=None, stage="solve", extraction=None):
    if reply is None:
        return None
    extraction = extraction or extract_result(reply.content, ctx.task.top)
    complete = (extraction.status == "ok" and extraction.complete
                and extraction.target_module_found and not extraction.suspected_truncation)
    candidate = None
    if complete:
        candidate = ctx.candidates.create(
            extraction.code, source_stage=f"guided_{stage}",
            round=parent.round + 1 if parent else 1,
            parent_id=parent.id if parent else None,
            finish_reason=reply.finish_reason, extraction_status=extraction.status,
            call_id=reply.call_id,
        )
        ctx.store["submission"].register(candidate, reason=f"guided_{stage}")
    _save(ctx, f"{stage}-extraction", extraction.trace_dict())
    ctx.record.emit("extract", "result", source_call_id=reply.call_id,
                    source_stage=f"guided_{stage}", status=extraction.status,
                    candidate_id=candidate.id if candidate else None, complete_new_draft=complete,
                    diagnostics=list(extraction.diagnostics), finish_reason=reply.finish_reason,
                    parent_id=parent.id if parent else None,
                    retained_candidate_id=parent.id if parent and not candidate else None)
    if not candidate:
        _response_failure(
            ctx, stage, reply, _empty_failure(reply) or "invalid_rtl",
            required_top=ctx.task.top, extraction=extraction.trace_dict(),
        )
        return None
    return candidate


def _skill_assets(ctx):
    data = _g(ctx)
    if "skill_assets" not in data:
        data["skill_assets"] = load_assets(skills=True)
    return data["skill_assets"]


def _skill_and_card_material(ctx, phase="generate"):
    data = _g(ctx)
    assets = _skill_assets(ctx)
    selected, rejected = select_skills(
        assets, list(data["plan"]["skills"]), [phase], automatic=True
    )
    parts = []
    for skill_id in selected:
        parts.append(f"[Skill {skill_id}]\n{assets['skills'][skill_id][1]}")
    cards = knowledge.card_map() if phase == "generate" and data["plan"]["knowledge"] else {}
    card_sent = []
    for card_id in data["plan"]["knowledge"] if phase == "generate" else ():
        card = cards.get(card_id)
        if card is None:
            rejected.append({"id": card_id, "reason": "unknown_card"})
        elif not knowledge.card_allowed(card, "pre_generation"):
            rejected.append({"id": card_id, "reason": "card_not_injectable_at_pre_generation"})
        else:
            parts.append(knowledge.card_text(card))
            card_sent.append(card_id)
    return "\n\n".join(parts), {
        "sent": selected, "cards_sent": card_sent, "rejected": rejected
    }


def _shortlist(ctx, limit):
    data = _g(ctx)
    settings = data["settings"]
    assets = _skill_assets(ctx)
    skills = []
    for identity, (skill, _) in assets["skills"].items():
        if any(
            select_skills(assets, [identity], [phase], automatic=True)[0]
            for phase in ("generate", "repair")
        ):
            skills.append((identity, skill.description))
    mode = settings.get("retrieval_mode", "legacy")
    query = ctx.task.prompt + "\n" + ctx.task.interface
    picked, report = knowledge.retrieve(
        query, mode=mode, limit=limit,
        strategy=settings.get("retrieval_strategy", "bm25"),
        embedding_url=settings.get("embedding_url", ""),
        embedding_timeout_s=settings.get("embedding_timeout_s", 2.0),
        stage="pre_generation",
        record=ctx.record,
    )
    data["retrieval"] = report
    return skills, picked


def _append_material(ctx, messages, phase, artifact):
    material, selection = _skill_and_card_material(ctx, phase)
    if material:
        messages[-1]["content"] += (
            "\n\n## Selected method material (optional; public task takes precedence)\n"
            + material
        )
    _save(ctx, artifact, {
        **selection,
        "phase": phase,
        "resources": _skill_assets(ctx)["resources"],
    })


@node("guided_initialize", reads=["settings"], writes=[])
def initialize(ctx: Ctx, state: State) -> State:
    if "guided" in ctx.store:
        raise ValueError("guided initialization must run exactly once")
    settings = state["settings"]
    ctx.store["guided"] = {
        "settings": settings,
        "ledger": CompletionLedger(
            ctx.budget, ctx.record,
            max_calls=settings["max_calls"],
            max_output_tokens=settings["max_output_tokens"],
        ),
        "attempted": set(),
        "request_outcomes": {},
        "plan": None,
        "method": "structural",
        "checker": None,
        "checker_text": "",
        "checker_status": "not_built",
        "checker_notice": "",
        "checker_version": None,
        "history": [],
        "withdrawn_cases": [],
        "unresolved_reviews": {},
        "expectations_revised": False,
        "author_decisions": 0,
        "checker_reviews": 0,
        "checker_format_repairs": 0,
        "assessments": {},
        "observations": {},
        "behaviors": {},
        "retrieval": {},
        "checker_hash": None,
        "structure_repairs": 0,
        "behavior_repairs": 0,
        "solve_recovery_attempts": 0,
        "solve_recoveries_sent": 0,
        "checker_recovery_attempts": 0,
        "checker_recoveries_sent": 0,
    }
    ctx.store["submission"] = SubmissionGateway(ctx, policy="author_decides")
    _save(ctx, "settings", settings)
    return state


@node("guided_plan", reads=[], writes=["method"])
def plan(ctx: Ctx, state: State) -> State:
    data = _g(ctx)
    settings = data["settings"]
    rules = checker_contract(ctx.task, **_checker_limits(ctx))
    _save(ctx, "checker-contract", rules)
    skills, cards = _shortlist(ctx, settings["knowledge_candidates"])
    _save(ctx, "retrieval", data["retrieval"])
    ctx.record.emit("knowledge", "retrieval", **data["retrieval"])
    messages = plan_request(
        ctx.task, skills, cards, checker_rules=rules,
        max_skills=2, max_cards=settings["knowledge_select"],
    )
    reply = _request(
        ctx, "plan", messages, settings["planner"],
        followup_s=min(settings["solve"]["timeout_s"], settings.get("solve_minimum_s", 120))
        + settings["first_tools_s"],
    )
    chosen = None
    if reply is not None:
        try:
            chosen = parse_plan(
                reply.content,
                skill_ids=[identity for identity, _ in skills],
                card_ids=[card["card_id"] for card in cards],
                max_skills=2,
                max_cards=settings["knowledge_select"],
            )
        except PlanError as error:
            _save(ctx, "plan-error", {"status": "invalid", "reason": str(error)})
    data["plan_source"] = "planner" if chosen is not None else "fallback"
    if chosen is None:
        chosen = Plan("structural", (), (), (), "planner_fallback")
    if chosen.method == "table" and not rules["supported"]:
        data["checker_status"] = "unsupported"
        data["checker_notice"] = rules["reason"]
    _save(ctx, "plan-capability", {
        "requested": chosen.method, "plan_source": data["plan_source"],
        "table_supported": rules["supported"], "reason": rules.get("reason"),
    })
    data["plan"] = chosen.public_dict()
    data["method"] = chosen.method
    _save(ctx, "plan", data["plan"])
    return state.update(method=chosen.method)


@node("guided_solve", reads=[], writes=["target_id"])
def solve(ctx: Ctx, state: State) -> State:
    data = _g(ctx)
    settings = data["settings"]
    messages = ctx.prompts.render(
        "repair.md", task=ctx.task, feedback="", parent=None, plan=None
    )
    _append_material(ctx, messages, "generate", "material")
    reply = _request(
        ctx, "solve", messages, settings["solve"],
        followup_s=settings["first_tools_s"],
    )
    stage = "solve"
    candidate = _candidate(ctx, reply)
    if candidate is None and _empty_failure(reply) in ("stop_no_final", "length_no_final"):
        def fresh_messages():
            fresh = ctx.prompts.render(
                "repair.md", task=ctx.task, feedback="", parent=None, plan=None
            )
            _append_material(ctx, fresh, "generate", "material-solve_recovery")
            return fresh

        recovered = _recover_empty(ctx, "solve", reply, fresh_messages, settings["solve"])
        stage = _attempt_stage("solve_recovery", data["solve_recovery_attempts"])
        candidate = _candidate(ctx, recovered, stage=stage)
    if candidate is not None:
        _remember(ctx, stage, candidate, action="generate", source_call_id=candidate.source_call_id)
    else:
        data.setdefault("stop_detail", _request_reason(data, stage, "no_complete_rtl"))
    return state.update(target_id=candidate.id if candidate else None)


def _check_structure(ctx, candidate, allowance_s):
    data = _g(ctx)
    end = time.monotonic() + (allowance_s or ctx.budget.remaining())
    checks = {}

    def run(stage):
        remaining = min(end - time.monotonic(), ctx.budget.remaining())
        if remaining <= 0:
            check = bind_result(
                CheckResult("timeout", "tool allowance exhausted", failure_kind="timeout"),
                candidate, stage,
            )
        else:
            check = ctx.call(
                stage, candidate_id=candidate.id,
                **({} if stage == "interface" else {"timeout_s": remaining}),
            )
            check = bind_result(check, candidate, stage)
        checks[stage] = check
        if stage != "synth":
            _save(ctx, f"assessments/{candidate.id}/{stage}", check.trace_dict())
        return check

    interface = run("interface")
    compile_allowed = not interface.blocking
    lint = run("lint") if compile_allowed else None
    lint_passed = lint is not None and tool_succeeded(lint.status, lint.rc)
    synth = run("synth") if lint_passed else None
    code_failed = any(
        check is not None and check.status == "failed"
        and check.failure_kind == "code"
        for check in (interface, lint, synth)
    )
    toolchain_passed = synth is not None and tool_succeeded(synth.status, synth.rc)
    interface_verified = tool_succeeded(interface.status, interface.rc) and not interface.blocking
    assessment = {
        "candidate_id": candidate.id,
        "candidate_hash": candidate.code_hash,
        "checks": {name: check.trace_dict() for name, check in checks.items()},
        "code_failed": code_failed,
        "structural_passed": interface_verified and toolchain_passed,
        "toolchain_passed": toolchain_passed,
        "interface_verified": interface_verified,
        "synthesis_hints": synth.details.get("synthesis_hints", []) if synth else [],
    }
    ctx.store["submission"].record_structure(candidate, assessment)
    if synth is not None:
        _save(ctx, f"assessments/{candidate.id}/synth", assessment["checks"]["synth"])
    data["assessments"][candidate.id] = assessment
    _save(ctx, f"assessments/{candidate.id}/assessment", assessment)
    return assessment, checks


@node("guided_structure", reads=["target_id", "method"], writes=["action"])
def structure(ctx: Ctx, state: State) -> State:
    data = _g(ctx)
    settings = data["settings"]
    candidate = ctx.candidates.get(state["target_id"])
    if candidate is None or data.get("repair_request_stopped"):
        return state.update(action="finish")
    assessment, _ = _check_structure(ctx, candidate, settings["first_tools_s"])
    if assessment["code_failed"]:
        action = "repair_structure"
    elif not assessment["toolchain_passed"]:
        action = "author_decision"
    elif data["method"] == "structural":
        ctx.store["submission"].submit_candidate(
            candidate, mode="structural_auto", reason="lint_and_synth_passed",
        )
        action = "finish"
    elif data["checker"] is not None:
        action = "run_checker"
    elif data["checker_status"] == "not_built":
        action = "build_checker"
    else:
        action = "author_decision"
    return state.update(action=action)


@node("guided_repair_structure", reads=["target_id"], writes=["target_id", "action"])
def repair_structure(ctx: Ctx, state: State) -> State:
    data = _g(ctx)
    settings = data["settings"]
    parent = ctx.candidates.get(state["target_id"])
    assessment = data["assessments"].get(parent.id, {})
    feedback = json.dumps({
        "candidate_id": parent.id,
        "candidate_hash": getattr(parent, "code_hash", None),
        "synthesis_hints": assessment.get("synthesis_hints", []),
        "decision_history": author_history(data["history"]),
        "previous_repair_error": data.get("repair_format_error"),
        "checks": [
            {
                "tool": name, "status": check.get("status"),
                "failure_kind": check.get("failure_kind"), "rc": check.get("rc"),
                "repair_diagnostics": (check.get("details") or {}).get("repair_diagnostics"),
                "excerpt": check.get("excerpt", ""),
            }
            for name, check in assessment.get("checks", {}).items()
            if check.get("status") in ("failed", "timeout")
        ],
    }, ensure_ascii=False)
    messages = ctx.prompts.render(
        "repair.md", task=ctx.task, parent=parent, feedback=feedback, plan=None
    )
    data["structure_repairs"] += 1
    stage = _attempt_stage("repair_structure", data["structure_repairs"])
    _append_material(ctx, messages, "repair", f"material-{stage}")
    reply = _request(
        ctx, stage, messages, settings["solve"], followup_s=settings["first_tools_s"],
        optional=bool(data.get("repair_format_error")),
    )
    child = _candidate(ctx, reply, parent=parent, stage=stage)
    if child is None:
        cause = _request_reason(data, stage, "repair_without_candidate")
        if reply is not None:
            _remember(ctx, stage, parent, action="invalid_repair", reason=cause,
                      source_call_id=reply.call_id, outcome="no_complete_replacement")
            signature = (parent.id, reply.finish_reason, reply.content)
            if reply.finish_reason in ("stop", "length") and signature != data.get("invalid_repair_signature"):
                data["invalid_repair_signature"] = signature
                data["repair_format_error"] = (
                    f"{cause}: the current draft still has the reported structural error. "
                    "Return the complete corrected RTL including the required top."
                )
                return state.update(target_id=parent.id, action="retry")
        data["repair_request_stopped"] = True
        data["stop_detail"] = cause
        return state.update(target_id=parent.id, action="finish")
    data.pop("invalid_repair_signature", None)
    data.pop("repair_format_error", None)
    failures = []
    for name, check in assessment["checks"].items():
        if check.get("failure_kind") == "code" and check["status"] == "failed":
            diagnostics = (check.get("details") or {}).get("repair_diagnostics") or {}
            roots = diagnostics.get("root_errors") or []
            message = roots[0].get("message") if roots and isinstance(roots[0], dict) else ""
            failures.append(f"{name}: {(message or check['excerpt'])[:240]}")
    _remember(ctx, stage, parent, action="repair_structure", reason=" / ".join(failures),
              outcome="code_failed", source_call_id=reply.call_id, child_id=child.id,
              child_hash=child.code_hash, changed=child.code_hash != parent.code_hash)
    return state.update(target_id=child.id, action="recheck")


def _remember(ctx, stage, candidate, *, role="author", **fields):
    data = _g(ctx)
    data["history"].append({
        "stage": stage, "role": role, "round": candidate.round,
        "candidate_id": candidate.id, "candidate_hash": candidate.code_hash,
        "checker_hash": data["checker_hash"], **fields,
    })
    _save(ctx, "decision-history", data["history"])


def _request_reason(data, stage, default):
    outcome = data["request_outcomes"].get(stage, {})
    return outcome.get("kind") or outcome.get("reason") or outcome.get("failure_kind") or default


def _leave_author_call(data):
    return data["ledger"].snapshot()["calls_remaining"] == 1


def _checker_reply(ctx, stage, make_messages, parse):
    """Repair the checker's own format in isolation. Preserve a final author turn when possible."""
    data = _g(ctx)
    limits = data["settings"]["checker"]
    if _leave_author_call(data):
        reason = "reserved_last_call_for_author"
        data["request_outcomes"][stage] = {"status": "not_sent", "reason": reason}
        _save(ctx, "request-outcomes", data["request_outcomes"])
        return None, "", reason, stage
    seen = set()
    messages = make_messages()
    initial_stage = stage
    last_diagnostic = ""
    while True:
        reply = _request(ctx, stage, messages, limits,
                         optional=stage != "checker", followup_s=data["settings"]["first_tools_s"])
        if stage == "checker" and _empty_failure(reply) in ("stop_no_final", "length_no_final"):
            _response_failure(ctx, stage, reply, _empty_failure(reply))
            if not _leave_author_call(data):
                reply = _recover_empty(ctx, stage, reply, make_messages, limits)
                stage = _attempt_stage("checker_recovery", data["checker_recovery_attempts"])
        if reply is None:
            reason = _request_reason(data, stage, "checker_request_unavailable")
            if last_diagnostic:
                reason = f"{last_diagnostic} (format repair unavailable: {reason})"
            return None, "", reason, stage
        diagnosis = _empty_failure(reply)
        if diagnosis is None:
            try:
                return parse(reply.content), reply.content, "", stage
            except CheckerError as error:
                diagnosis = str(error)
        _response_failure(ctx, stage, reply, _empty_failure(reply) or "invalid_checker", reason=diagnosis)
        _save(ctx, "checker-error", {"status": "invalid", "stage": stage, "reason": diagnosis,
                                     "source_call_id": reply.call_id})
        signature = (reply.content, diagnosis)
        if (signature in seen or _leave_author_call(data) or not reply.content.strip()
                or data["ledger"].snapshot()["calls_remaining"] == 0):
            return None, "", diagnosis, stage
        seen.add(signature)
        last_diagnostic = diagnosis
        messages = make_messages()
        messages[-1]["content"] += (
            "\n\nYour previous checker reply (up to 16384 characters):\n" + reply.content[:16384]
            + "\n\nHost parser diagnostic: " + diagnosis
            + "\nReturn a complete corrected " + ("table." if initial_stage == "checker" else "review reply.")
        )
        data["checker_format_repairs"] += 1
        stage = _attempt_stage("checker_format_repair", data["checker_format_repairs"])


def _set_checker(ctx, checker, text):
    data = _g(ctx)
    data["checker"] = checker
    data["checker_text"] = text
    data["checker_hash"] = _checker_fingerprint(checker) if checker is not None else None
    data["checker_version"] = checker_version()
    data["checker_status"] = "valid" if checker is not None else "withdrawn"
    data["checker_notice"] = "" if checker is not None else "All test points have been withdrawn."
    _save(ctx, "checker", {"status": data["checker_status"], "checker_hash": data["checker_hash"],
                           **(checker.public_dict() if checker is not None else {"cases": []})})


@node("guided_build_checker", reads=[], writes=["checker_status"])
def build_checker(ctx: Ctx, state: State) -> State:
    data = _g(ctx)
    skill = _skill_assets(ctx)["skills"].get("rtl-behavior-check-keycases")
    if skill is None:
        data["checker_status"] = "unavailable"
        data["checker_notice"] = "Checker skill unavailable."
    else:
        limits = _checker_limits(ctx)
        checker, text, error, stage = _checker_reply(
            ctx, "checker", lambda: checker_request(ctx.task, skill[1], (), **limits),
            lambda text: parse_checker(text, ctx.task, require_explanations=True, **limits),
        )
        if checker is None:
            data["checker_status"] = ("unavailable" if data["request_outcomes"].get(stage, {}).get("status")
                                      in ("not_sent", "error") else "invalid")
            data["checker_notice"] = error
        else:
            _set_checker(ctx, checker, text)
    _save(ctx, "checker-build", {"status": data["checker_status"], "reason": data["checker_notice"],
                                 "checker_hash": data["checker_hash"]})
    return state.update(checker_status=data["checker_status"])

@node("guided_run_checker", reads=["target_id"], writes=["action"])
def run_checker(ctx: Ctx, state: State) -> State:
    data = _g(ctx)
    settings = data["settings"]
    candidate = ctx.candidates.get(state["target_id"])
    checker = data["checker"]
    with ctx.record.span("guided_observe", candidate_id=candidate.id):
        trace = observe(
            ctx, candidate, checker.plan,
            timeout_s=min(settings["recheck_tools_s"] or ctx.budget.remaining(),
                          ctx.budget.remaining()),
        )
    data["observations"][candidate.id] = trace
    _save(ctx, f"assessments/{candidate.id}/observations", trace.public_dict())
    if trace.status == "complete" and getattr(trace, "candidate_hash", None) != candidate.code_hash:
        behavior = {"status": "invalid", "failure_kind": "checker",
                    "summary": "observation belongs to a different candidate",
                    "checked_outputs": list(checker.checked_outputs),
                    "unchecked_outputs": list(checker.unchecked_outputs),
                    "case_results": [], "failed": [], "unknown": [], "compared_bits": 0}
    elif trace.status == "complete":
        behavior = evaluate_checker(checker, trace)
    else:
        behavior = {
            "status": trace.status, "failure_kind": trace.failure_kind,
            "summary": trace.summary, "checked_outputs": list(checker.checked_outputs),
            "unchecked_outputs": list(checker.unchecked_outputs),
            "case_results": [], "failed": [], "unknown": [], "compared_bits": 0,
        }
    identity = {"candidate_id": candidate.id, "candidate_hash": candidate.code_hash,
                "checker_hash": data.get("checker_hash"), "checker_version": data.get("checker_version"),
                "sampling_plan_hash": getattr(trace, "plan_hash", None),
                "execution_id": getattr(trace, "execution_id", None)}
    data["behaviors"][candidate.id] = {**identity, "behavior": behavior}
    _save(
        ctx, f"assessments/{candidate.id}/behavior",
        {**identity, **behavior},
    )
    return state.update(action="author_decision")



def _case_ids(data):
    checker = data["checker"]
    return [case.id for case in checker.cases] if checker is not None else []


def _author_structure(assessment):
    return {**assessment, "checks": {
        name: {field: check.get(field) for field in ("status", "rc", "failure_kind", "excerpt")}
        for name, check in assessment["checks"].items()
    }}


@node("guided_author_decision", reads=["target_id"], writes=["target_id", "action"])
def author_decision(ctx: Ctx, state: State) -> State:
    data = _g(ctx)
    candidate = ctx.candidates.get(state["target_id"])
    assessment = data["assessments"][candidate.id]
    behavior = _behavior_for(data, candidate.id)
    issues = {
        "status": data["checker_status"], "reason": data["checker_notice"],
        "requested_method": data["method"], "withdrawn_cases": list(data["withdrawn_cases"]),
        "criterion_changed": data["expectations_revised"], "unresolved_reviews": data["unresolved_reviews"],
    }
    if not assessment["toolchain_passed"]:
        issues["structural_gate"] = "Vivado lint and synthesis have not both passed for this candidate."
    issues["previous_decision_error"] = data.get("decision_error")
    budget = data["ledger"].snapshot()
    remaining = {key: budget[key] for key in ("calls_remaining", "output_tokens_remaining",
                                               "unknown_usage_calls", "unconfirmed_calls")}
    remaining["seconds_remaining"] = round(ctx.budget.remaining(), 2)
    binding = data["behaviors"].get(candidate.id, {}) if behavior else {}
    messages = author_decision_request(
        ctx.task, candidate, structure=_author_structure(assessment),
        behavior=({**{k: v for k, v in binding.items() if k != "behavior"}, **behavior}
                  if behavior else {"status": "not_run", "compared_bits": 0}),
        checker_text=data["checker_text"], checker_status=issues,
        case_ids=_case_ids(data), history=data["history"], budget=remaining,
        execution=_checker_execution(ctx) if data["checker"] is not None else None,
    )
    data["author_decisions"] += 1
    stage = _attempt_stage("author_decision", data["author_decisions"])
    _append_material(ctx, messages, "repair", f"material-{stage}")
    messages[-1]["content"] += (
        "\n\nFor this decision, use the action/reason reply format above. "
        "Apply any selected skill to the RTL when revising. Only revise includes a fenced RTL block."
    )
    reply = _request(ctx, stage, messages, data["settings"]["solve"], optional=bool(data.get("decision_error")))
    if reply is None:
        data["stop_detail"] = _request_reason(data, stage, "author_unavailable")
        return state.update(action="finish")
    try:
        decision = parse_author_decision(reply.content, top=ctx.task.top, case_ids=_case_ids(data))
    except AuthorDecisionError as error:
        kind = _empty_failure(reply) or "invalid_author_decision"
        _response_failure(ctx, stage, reply, kind, reason=str(error))
        signature = (candidate.id, data["checker_hash"], reply.content, str(error))
        _remember(ctx, stage, candidate, action="invalid", reason=str(error), source_call_id=reply.call_id)
        if signature == data.get("invalid_decision_signature") or kind == "empty_unknown_finish":
            data["stop_detail"] = kind
            return state.update(action="finish")
        data["invalid_decision_signature"] = signature
        data["decision_error"] = str(error)
        return state.update(action="retry")

    data.pop("decision_error", None)
    data.pop("invalid_decision_signature", None)
    outcome = behavior.get("status") or (
        data["checker_status"] if assessment["toolchain_passed"] else "structure_unverified"
    )
    note = {**decision.public_dict(), "source_call_id": reply.call_id, "outcome": outcome,
            "checked": behavior.get("compared_bits", 0) > 0}
    child = None
    if decision.action == "submit":
        ctx.store["submission"].submit_candidate(candidate, mode="author_submit", reason=decision.reason)
    elif decision.action == "revise":
        child = _candidate(ctx, reply, parent=candidate, stage=stage, extraction=decision.extraction)
        data["behavior_repairs"] += 1
        note.update(child_id=child.id, child_hash=child.code_hash, changed=child.code_hash != candidate.code_hash)
    else:
        data["review_case"] = decision.case_id
    _remember(ctx, stage, candidate, **note)
    return state.update(action=decision.action, target_id=child.id if child is not None else candidate.id)


@node("guided_checker_review", reads=["target_id"], writes=["action"])
def checker_review(ctx: Ctx, state: State) -> State:
    data = _g(ctx)
    candidate = ctx.candidates.get(state["target_id"])
    case_id = data.pop("review_case")
    limits = _checker_limits(ctx)
    old_text = data["checker_text"]
    old_hash = data["checker_hash"]
    skill = _skill_assets(ctx)["skills"]["rtl-behavior-check-keycases"][1]
    data["checker_reviews"] += 1
    stage = _attempt_stage("checker_review", data["checker_reviews"])
    review, _, error, reply_stage = _checker_reply(
        ctx, stage, lambda: checker_review_request(ctx.task, skill, old_text, case_id, **limits),
        lambda text: apply_checker_review(text, ctx.task, old_text, case_id, **limits),
    )
    action = "author_decision"
    if review is None:
        result, reason = "unresolved", error
        data["unresolved_reviews"][case_id] = {"reason": error, "checker_hash": old_hash}
        data["checker_notice"] = f"Independent review of {case_id} did not complete: {error}"
    else:
        result, reason = review.action, review.reason
        data["unresolved_reviews"].pop(case_id, None)
        data["checker_notice"] = ""
        if result in ("correct", "withdraw"):
            if result == "withdraw":
                data["withdrawn_cases"].append(case_id)
            else:
                previous = next(case for case in data["checker"].cases if case.id == case_id)
                updated = next(case for case in review.checker.cases if case.id == case_id)
                if (list(previous.expectations()) != list(updated.expectations())
                        or data["checker"].plan != review.checker.plan):
                    data["expectations_revised"] = True
            _set_checker(ctx, review.checker, review.table_text)
            if review.checker is not None and data["assessments"][candidate.id]["toolchain_passed"]:
                action = "run_checker"
    detail = {
        "case_id": case_id, "review_action": result, "review_reason": reason,
        "reviewed_checker_hash": old_hash, "checker_hash": data["checker_hash"],
        "source_call_id": data["request_outcomes"].get(reply_stage, {}).get("call_id"),
    }
    data["last_revision"] = {"candidate_id": candidate.id, "candidate_hash": candidate.code_hash, **detail}
    _save(ctx, "checker-revision", data["last_revision"])
    _remember(ctx, stage, candidate, role="checker", **detail)
    return state.update(action=action)


@node("guided_finish", reads=["target_id"], writes=["status", "stop_reason"])
def finish(ctx: Ctx, state: State) -> State:
    data = _g(ctx)
    submission = ctx.store["submission"].finalize(data.get("stop_detail") or "workflow_finished")
    final = submission["final"]
    identity = final["target_id"]
    assessment = data["assessments"].get(identity, {})
    behavior = _behavior_for(data, identity)
    matched = behavior.get("status") == "passed" and behavior.get("compared_bits", 0) > 0
    revised = data["expectations_revised"]
    withdrawn = list(data["withdrawn_cases"])
    unresolved = data["unresolved_reviews"]
    functional = matched and not revised and not withdrawn and not unresolved
    submitted_with_mismatch = final["mode"] == "author_submit" and behavior.get("status") == "failed"
    disputed = bool(withdrawn or revised or unresolved or submitted_with_mismatch)
    status = "completed" if final["mode"] in ("author_submit", "structural_auto") else "stopped"
    evidence = {
        "method": data["method"], "structural_passed": bool(assessment.get("structural_passed")),
        "toolchain_passed": assessment.get("toolchain_passed"), "interface_verified": assessment.get("interface_verified"),
        "behavior_status": behavior.get("status"), "compared_bits": behavior.get("compared_bits"),
        "checker_hash": data["checker_hash"], "checker_version": data["checker_version"],
        "functional_passed": functional, "current_table_passed": matched, "expectations_revised": revised,
        "withdrawn_cases": withdrawn, "checker_disputed": disputed, "submission_mode": final["mode"],
        "submitted_with_mismatch": submitted_with_mismatch, "unresolved_reviews": unresolved,
    }
    if identity:
        ctx.record.emit("guided", "verification", candidate_id=identity, candidate_hash=final["code_hash"], **evidence)
    budget = data["ledger"].snapshot()
    calls_by_role = Counter(role_for_stage(p["stage"]) for p in budget["permits"] if p["call_id"] is not None)
    result = {
        "status": status, "selected_id": final["selected_id"], "evidence_candidate_id": identity,
        "published_id": identity, "delivery": final["delivery"], "plan": data["plan"],
        "plan_source": data["plan_source"], "checker_status": data["checker_status"], "checker_notice": data["checker_notice"],
        "behavior_candidate_id": identity if behavior else None, "behavior": behavior,
        "partial_behavior": behavior.get("status") == "partial_passed", "last_checker_revision": data.get("last_revision"),
        "stop_detail": final["reason"], "fallback_basis": final.get("fallback_basis"),
        "retrieval": data["retrieval"], "decision_history": data["history"], "submission": submission,
        "request_outcomes": data["request_outcomes"], "budget": budget,
        "calls_sent_by_role": {role: calls_by_role[role] for role in ("analyst", "author", "builder")},
        "author_decision_attempts": data["author_decisions"], "checker_review_attempts": data["checker_reviews"],
        "author_decisions": sum(note.get("action") in ("submit", "revise", "review") for note in data["history"]),
        "checker_reviews": sum(note.get("review_action") in ("keep", "correct", "withdraw") for note in data["history"]),
        "structure_repair_attempts": data["structure_repairs"],
        "structure_repairs": sum(note.get("action") == "repair_structure" for note in data["history"]),
        **evidence,
        **{key: data[key] for key in (
            "checker_format_repairs", "behavior_repairs",
            "solve_recovery_attempts", "solve_recoveries_sent", "checker_recovery_attempts", "checker_recoveries_sent",
        )},
    }
    _save(ctx, "result", result)
    return state.update(status=status, stop_reason=final["reason"])
