"""Guided solve/check workflow: small planner, host TB, bounded repair."""

from __future__ import annotations

import hashlib
import json
import time

from agent.kit import Ctx, State, node
from agent.llm.client import ModelError
from agent.runtime.allowance import CompletionLedger
from agent.domain.rtl.extract import extract_result
from agent.domain.rtl.guided_adjudicate import (
    AdjudicationError,
    adjudicate_request,
    parse_adjudication,
)
from agent.domain.rtl.guided_checker import (
    CheckerError,
    checker_request,
    evaluate_checker,
    parse_checker,
)
from agent.domain.rtl.guided_plan import Plan, PlanError, parse_plan, plan_request
from agent.domain.rtl.observation import observe
from agent.domain.rtl.result import CheckResult, bind_result
from agent.submission.gateway import SubmissionGateway
from agent.llm.router import profile_for_stage
from agent.domain.knowledge.assets import load_assets
from agent.domain.knowledge import guided as knowledge
from agent.domain.knowledge.policy import select_skills


def _g(ctx):
    return ctx.store["guided"]


def _save(ctx, name, value):
    path = ctx.record.write_json(f"guided/{name}.json", value)
    ctx.record.emit(
        "guided", "artifact", name=name, path=path,
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
    if not record or record.get("checker_hash") != data.get("checker_hash"):
        return {}
    return record.get("behavior") or {}


def _request(ctx, stage, messages, limits, *, followup_s=0):
    data = _g(ctx)
    if stage in data["attempted"]:
        raise ValueError(f"guided stage may only request once: {stage}")
    data["attempted"].add(stage)
    permit = data["ledger"].reserve(
        stage, **limits, followup_s=followup_s, optional=False
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
                **limits,
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
        }
        ctx.record.emit("guided", "request_failed", stage=stage, kind=error.kind,
                        reason=str(error))
        return None
    finally:
        _save(ctx, "completion-ledger", data["ledger"].snapshot())
        _save(ctx, "request-outcomes", data["request_outcomes"])


def _candidate(ctx, reply, *, parent=None, stage="solve", extraction=None):
    if reply is None:
        return None
    extraction = extraction or extract_result(reply.content, ctx.task.top)
    _save(ctx, f"{stage}-extraction", extraction.trace_dict())
    if (
        extraction.status != "ok"
        or not extraction.complete
        or not extraction.target_module_found
        or extraction.suspected_truncation
    ):
        _save(ctx, f"{stage}-failure", {
            "source_call_id": reply.call_id,
            "finish_reason": reply.finish_reason,
            "required_top": ctx.task.top,
            "extraction": extraction.trace_dict(),
        })
        return None
    candidate = ctx.candidates.create(
        extraction.code,
        source_stage=f"guided_{stage}",
        round=2 if parent else 1,
        parent_id=parent.id if parent else None,
        finish_reason=reply.finish_reason,
        extraction_status=extraction.status,
        call_id=reply.call_id,
    )
    if parent is None:
        ctx.candidates.select(candidate.id, reason="complete_unverified_fallback")
    gateway = ctx.store.get("submission")
    if gateway is not None:
        gateway.register(candidate, reason=f"guided_{stage}")
    return candidate


def _skill_and_card_material(ctx):
    data = _g(ctx)
    assets = load_assets(skills=True)
    selected, rejected = select_skills(
        assets, list(data["plan"]["skills"]), ["generate"], automatic=True
    ) if data["plan"]["skills"] else ([], [])
    parts = []
    for skill_id in selected:
        parts.append(f"[Skill {skill_id}]\n{assets['skills'][skill_id][1]}")
    cards = knowledge.card_map()
    for card_id in data["plan"]["knowledge"]:
        if card_id in cards:
            parts.append(knowledge.card_text(cards[card_id]))
    return "\n\n".join(parts), {"sent": selected, "rejected": rejected}


def _shortlist(ctx, limit):
    data = _g(ctx)
    settings = data["settings"]
    assets = load_assets(skills=True)
    skills = [
        (identity, skill.description)
        for identity, (skill, _) in assets["skills"].items()
    ]
    mode = settings.get("retrieval_mode", "legacy")
    statuses = {"legacy": {"legacy_policy"}, "rag": {"legacy_policy", "restricted"},
                "all": {"legacy_policy", "restricted", "shadow", "mechanical_only"}}.get(mode, set())
    cards = [card for card in knowledge.load_cards() if card.get("activation_state") in statuses]
    query = ctx.task.prompt + "\n" + ctx.task.interface
    if settings.get("retrieval_strategy") == "dense" and mode != "off":
        try:
            picked, _ = knowledge.retrieve(
                query, mode=mode, limit=limit, strategy="dense",
                embedding_url=settings.get("embedding_url", ""),
                embedding_timeout_s=settings.get("embedding_timeout_s", 2.0),
            )
        except (OSError, ValueError, RuntimeError):
            picked = []
    else:
        ranked = [card_id for card_id, _ in knowledge.bm25_rank(cards, query)]
        by_id = {card["card_id"]: card for card in cards}
        ordered = ranked + [c["card_id"] for c in cards if c["card_id"] not in ranked]
        picked = [by_id[identity] for identity in ordered[:limit]]
    return skills, picked


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
        "checker_rebuild_context": None,
        "assessments": {},
        "observations": {},
        "behaviors": {},
        "checker_hash": None,
        "behavior": None,
        "selection": None,
        "structure_repairs": 0,
        "behavior_repairs": 0,
        "checker_rebuilds": 0,
        "adjudications": 0,
    }
    ctx.store["submission"] = SubmissionGateway(
        ctx, policy=settings.get("submission_policy", "last_written")
    )
    _save(ctx, "settings", settings)
    return state


@node("guided_plan", reads=[], writes=["method"])
def plan(ctx: Ctx, state: State) -> State:
    data = _g(ctx)
    settings = data["settings"]
    skills, cards = _shortlist(ctx, settings["knowledge_candidates"])
    messages = plan_request(ctx.task, skills, cards)
    reply = _request(
        ctx, "plan", messages, settings["planner"],
        followup_s=settings["solve"]["timeout_s"] + settings["first_tools_s"],
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
    if chosen is None:
        chosen = Plan("structural", (), (), (), "planner_fallback")
    data["plan"] = chosen.public_dict()
    data["method"] = chosen.method
    _save(ctx, "plan", data["plan"])
    return state.update(method=chosen.method)


@node("guided_solve", reads=[], writes=["target_id"])
def solve(ctx: Ctx, state: State) -> State:
    data = _g(ctx)
    settings = data["settings"]
    messages = ctx.prompts.render(
        "repair.j2", task=ctx.task, feedback="", parent=None, plan=None
    )
    material, selection = _skill_and_card_material(ctx)
    if material:
        messages[-1]["content"] += (
            "\n\n## Selected method material (optional; public task takes precedence)\n"
            + material
        )
    _save(ctx, "material", selection)
    reply = _request(
        ctx, "solve", messages, settings["solve"],
        followup_s=settings["first_tools_s"],
    )
    candidate = _candidate(ctx, reply)
    return state.update(target_id=candidate.id if candidate else None)


def _check_structure(ctx, candidate, allowance_s):
    data = _g(ctx)
    end = time.monotonic() + allowance_s
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
        _save(ctx, f"assessments/{candidate.id}/{stage}", check.trace_dict())
        return check

    interface = run("interface")
    compile_allowed = not interface.blocking
    lint = run("lint") if compile_allowed else None
    synth = run("synth") if lint is not None and lint.status == "passed" else None
    code_failed = any(
        check is not None and check.status == "failed"
        and check.failure_kind == "code"
        for check in (interface, lint, synth)
    )
    structural_passed = (
        not interface.blocking
        and lint is not None and lint.status == "passed"
        and synth is not None and synth.status == "passed"
    )
    assessment = {
        "candidate_id": candidate.id,
        "candidate_hash": candidate.code_hash,
        "checks": {name: check.trace_dict() for name, check in checks.items()},
        "code_failed": code_failed,
        "structural_passed": structural_passed,
        "interface_verified": interface.status == "passed",
    }
    data["assessments"][candidate.id] = assessment
    _save(ctx, f"assessments/{candidate.id}/assessment", assessment)
    return assessment, checks


@node("guided_structure", reads=["target_id", "method"], writes=["action"])
def structure(ctx: Ctx, state: State) -> State:
    data = _g(ctx)
    settings = data["settings"]
    candidate = ctx.candidates.get(state["target_id"])
    if candidate is None:
        return state.update(action="finish")
    assessment, checks = _check_structure(
        ctx, candidate, settings["first_tools_s"]
    )
    if assessment["code_failed"] and data["structure_repairs"] < settings["structure_repair_limit"]:
        action = "repair_structure"
    elif state["method"] == "table" and data["checker"] is None and data["checker_status"] == "not_built":
        action = "build_checker"
    elif state["method"] == "table" and data["checker"] is not None:
        action = "run_checker"
    else:
        action = "finish"
    return state.update(action=action)


@node("guided_repair_structure", reads=["target_id"], writes=["target_id"])
def repair_structure(ctx: Ctx, state: State) -> State:
    data = _g(ctx)
    settings = data["settings"]
    parent = ctx.candidates.get(state["target_id"])
    assessment = data["assessments"].get(parent.id, {})
    feedback = "\n".join(
        f"{name}: {check.get('excerpt', '')}"
        for name, check in assessment.get("checks", {}).items()
        if check.get("status") in ("failed", "timeout")
    )
    messages = ctx.prompts.render(
        "repair.j2", task=ctx.task, parent=parent, feedback=feedback, plan=None
    )
    data["structure_repairs"] += 1
    stage = _attempt_stage("repair_structure", data["structure_repairs"])
    reply = _request(
        ctx, stage, messages, settings["solve"],
        followup_s=settings["first_tools_s"],
    )
    child = _candidate(ctx, reply, parent=parent, stage="repair_structure")
    return state.update(target_id=child.id if child else parent.id)


@node("guided_build_checker", reads=[], writes=["checker_status"])
def build_checker(ctx: Ctx, state: State) -> State:
    data = _g(ctx)
    settings = data["settings"]
    assets = load_assets(skills=True)
    identity = "rtl-behavior-check-keycases"
    entry = assets["skills"].get(identity)
    if entry is None:
        data["checker_status"] = "invalid"
        return state.update(checker_status="invalid")
    body = entry[1]
    messages = checker_request(ctx.task, body, data["plan"].get("focus", ()))
    context = data.get("checker_rebuild_context")
    if context:
        messages[-1]["content"] += (
            "\n\nPrevious checker (do not copy observed values):\n"
            + context["checker_text"]
            + "\nFailed case ids: "
            + ", ".join(context["failed_cases"])
            + "\nDecision category: checker_error"
            + "\nNo candidate RTL or measured outputs are provided."
        )
    stage = (
        _attempt_stage("checker_rebuild", data["checker_rebuilds"])
        if context else "checker"
    )
    reply = _request(
        ctx, stage, messages, settings["checker"],
        followup_s=settings["first_tools_s"],
    )
    if reply is None:
        data["checker_status"] = "invalid"
        data["checker_hash"] = None
        return state.update(checker_status="invalid")
    try:
        checker = parse_checker(
            reply.content, ctx.task,
            max_cases=settings["max_cases"],
            max_steps=settings["max_steps_per_case"],
            init_cycles=settings["init_cycles"],
        )
    except CheckerError as error:
        data["checker_status"] = "invalid"
        data["checker_hash"] = None
        _save(ctx, "checker-error", {"status": "invalid", "reason": str(error)})
        return state.update(checker_status="invalid")
    data["checker"] = checker
    data["checker_hash"] = _checker_fingerprint(checker)
    data["checker_text"] = reply.content
    data["checker_status"] = "valid"
    data["checker_rebuild_context"] = None
    _save(ctx, "checker", checker.public_dict())
    return state.update(checker_status="valid")


@node("guided_run_checker", reads=["target_id"], writes=["action"])
def run_checker(ctx: Ctx, state: State) -> State:
    data = _g(ctx)
    settings = data["settings"]
    candidate = ctx.candidates.get(state["target_id"])
    checker = data["checker"]
    with ctx.record.span("guided_observe", candidate_id=candidate.id):
        trace = observe(
            ctx, candidate, checker.plan,
            timeout_s=min(settings["recheck_tools_s"], ctx.budget.remaining()),
        )
    data["observations"][candidate.id] = trace
    _save(ctx, f"assessments/{candidate.id}/observations", trace.public_dict())
    if trace.status == "complete":
        behavior = evaluate_checker(checker, trace)
    else:
        behavior = {
            "status": trace.status, "failure_kind": trace.failure_kind,
            "summary": trace.summary, "checked_outputs": list(checker.checked_outputs),
            "unchecked_outputs": list(checker.unchecked_outputs),
            "failed": [], "unknown": [], "compared_bits": 0,
        }
    data["behavior"] = behavior
    data["behaviors"][candidate.id] = {
        "checker_hash": data.get("checker_hash"),
        "behavior": behavior,
    }
    _save(
        ctx, f"assessments/{candidate.id}/behavior",
        {"checker_hash": data.get("checker_hash"), **behavior},
    )
    if (
        behavior["status"] in ("failed", "unknown")
        and data["adjudications"] < settings["adjudicate_limit"]
    ):
        action = "adjudicate"
    else:
        action = "finish"
    return state.update(action=action)


@node("guided_adjudicate", reads=["target_id"], writes=["action"])
def adjudicate(ctx: Ctx, state: State) -> State:
    data = _g(ctx)
    settings = data["settings"]
    candidate = ctx.candidates.get(state["target_id"])
    behavior = data["behavior"]
    failures = behavior.get("failed", []) + behavior.get("unknown", [])
    messages = adjudicate_request(
        ctx.task, candidate, data["checker_text"], failures
    )
    data["adjudications"] += 1
    stage = "adjudicate" if data["adjudications"] == 1 else f"adjudicate_{data['adjudications']}"
    reply = _request(
        ctx, stage, messages, settings["adjudicate"],
        followup_s=settings["first_tools_s"],
    )
    if reply is None:
        return state.update(action="finish")
    try:
        decision = parse_adjudication(
            reply.content,
            case_ids=[case.id for case in data["checker"].cases],
        )
    except AdjudicationError as error:
        _save(ctx, "adjudication-error", {"status": "invalid", "reason": str(error)})
        return state.update(action="finish")
    data["adjudication"] = decision.public_dict()
    _save(ctx, "adjudication", data["adjudication"])
    if (
        decision.decision == "solution_error"
        and data["behavior_repairs"] < settings["behavior_repair_limit"]
    ):
        action = "repair_behavior"
    elif (
        decision.decision == "checker_error"
        and data["checker_rebuilds"] < settings["checker_rebuild_limit"]
    ):
        data["checker_rebuilds"] += 1
        data["checker_rebuild_context"] = {
            "checker_text": data["checker_text"],
            "failed_cases": list(decision.failed_cases),
        }
        data["checker_status"] = "rebuild"
        action = "rebuild_checker"
    else:
        action = "finish"
    return state.update(action=action)


@node("guided_repair_behavior", reads=["target_id"], writes=["target_id"])
def repair_behavior(ctx: Ctx, state: State) -> State:
    data = _g(ctx)
    settings = data["settings"]
    parent = ctx.candidates.get(state["target_id"])
    behavior = data["behavior"]
    feedback = (
        "Checker mismatch. Checker table:\n"
        + data["checker_text"]
        + "\nFailures:\n"
        + json.dumps(
            behavior.get("failed", []) + behavior.get("unknown", []),
            ensure_ascii=False,
        )
    )
    messages = ctx.prompts.render(
        "repair.j2", task=ctx.task, parent=parent, feedback=feedback, plan=None
    )
    data["behavior_repairs"] += 1
    stage = _attempt_stage("repair_behavior", data["behavior_repairs"])
    reply = _request(
        ctx, stage, messages, settings["solve"],
        followup_s=settings["first_tools_s"],
    )
    child = _candidate(ctx, reply, parent=parent, stage="repair_behavior")
    return state.update(target_id=child.id if child else parent.id)


@node("guided_finish", reads=["target_id"], writes=["status", "stop_reason"])
def finish(ctx: Ctx, state: State) -> State:
    data = _g(ctx)
    selected = ctx.candidates.selected_id
    target = state.get("target_id")
    target_assessment = data["assessments"].get(target)
    target_behavior = _behavior_for(data, target)
    # Promote the current child only when its structural and behavior checks
    # from this checker support it. A child checked against an older checker
    # cannot inherit the current evidence.
    if (
        target and target != selected and target_assessment is not None
        and target_assessment.get("structural_passed")
        and (
            data["method"] == "structural"
            or target_behavior.get("status") in ("passed", "partial_passed")
        )
    ):
        ctx.candidates.select(target, reason="guided_checked")
        selected = target
    gateway = ctx.store.get("submission")
    submission = gateway.finalize("workflow_finished") if gateway else None
    final = (submission or {}).get("final") or {}
    published = bool(final.get("published"))
    # Under last-write-wins the published answer can differ from the
    # evidence-backed selection. Report the candidate actually delivered, and
    # keep selected_id as the promotion audit.
    evidence_id = final.get("target_id") if published else selected
    assessment = data["assessments"].get(evidence_id)
    # The evidence candidate uses only behavior recorded under the current
    # checker; a child's result cannot stand in for the parent.
    behavior = _behavior_for(data, evidence_id)
    structural = bool(assessment and assessment.get("structural_passed"))
    functional = behavior.get("status") == "passed"
    status = "completed" if structural and (data["method"] == "structural" or functional) else "stopped"
    result = {
        "status": status,
        "selected_id": selected,
        "evidence_candidate_id": evidence_id,
        "published_id": final.get("target_id") if published else None,
        "delivery": "complete_rtl" if published else "empty",
        "method": data["method"],
        "plan": data.get("plan"),
        "checker_status": data["checker_status"],
        "checker_hash": data.get("checker_hash"),
        "behavior_candidate_id": evidence_id if behavior else None,
        "behavior": behavior,
        "structural_passed": structural,
        "functional_passed": functional,
        "partial_behavior": behavior.get("status") == "partial_passed",
        "structure_repairs": data["structure_repairs"],
        "behavior_repairs": data["behavior_repairs"],
        "checker_rebuilds": data["checker_rebuilds"],
        "adjudications": data["adjudications"],
        "adjudication": data.get("adjudication"),
        "submission": submission,
        "request_outcomes": data["request_outcomes"],
        "budget": data["ledger"].snapshot(),
    }
    _save(ctx, "result", result)
    return state.update(status=status, stop_reason=status)
