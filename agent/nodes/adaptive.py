"""Explicit adaptive stages. Checks never select or mutate the frozen checker."""

from dataclasses import replace
import time
import uuid

from agent.kit import Ctx, State, node
from agent.llm.client import ModelError
from agent.runtime.allowance import CompletionLedger
from agent.rtl.adaptive_analysis import analysis_request, parse_analysis, choose_route
from agent.rtl.adaptive_check import (
    checker_request, parse_checker, review_request, approve_review,
    revision_request, parse_checker_revision,
    recover_checker_format,
)
from agent.rtl.adaptive_repair import repair_request, parse_repair, diagnostic_codes
from agent.rtl.adaptive_assessment import BehaviorAssessment, CandidateAssessment
from agent.rtl.extract import extract_result
from agent.rtl.result import CheckResult, bind_result, checker_hash


def _data(ctx):
    return ctx.store["adaptive"]


def _approved_checker(ctx):
    checker = _data(ctx)["checker"]
    return checker if checker is not None and checker.repair_authorized else None


def _save(ctx, name, value):
    path = ctx.record.write_json(f"adaptive/{name}.json", value)
    ctx.record.emit("adaptive", "artifact", name=name, path=path,
                    status=value.get("status") if isinstance(value, dict) else None)


def _request(ctx, stage, messages, *, limits=None, followup_s=0, optional=True, parent=None, evidence=None):
    data = _data(ctx)
    if stage in data["attempted"]:
        raise ValueError(f"adaptive stage may only request once: {stage}")
    data["attempted"].add(stage)
    settings, ledger = data["settings"], data["ledger"]
    limits = limits or settings[stage]
    permit = ledger.reserve(stage, **limits, followup_s=followup_s, optional=optional)
    if permit is None:
        data["request_outcomes"][stage] = {"status": "not_sent", "reason": ledger.last_denial}
        _save(ctx, "completion-ledger", ledger.snapshot())
        _save(ctx, "request-outcomes", data["request_outcomes"])
        return None
    assembly = None
    try:
        with ctx.llm.permitted(permit):
            if stage in ("draft", "rescue", "repair"):
                from agent.knowledge.context import prepare

                messages, assembly = prepare(
                    ctx, messages, parent, evidence,
                    skill_ids=list(data["routing"].skill_ids), skill_phases=["generate", "repair"],
                    rag=settings["rag"] and parent is not None,
                    max_tokens=limits["max_tokens"], max_extra_tokens=settings["knowledge_max_tokens"],
                    diagnostic_first=parent is not None,
                    skill_mode=settings['skill_mode'], rag_mode=settings['rag_mode'],
                    retrieval_options=settings['retrieval'], automatic=True,
                )
            reply = ctx.llm.chat(messages, purpose=f"adaptive_{stage}",
                                 temperature=settings["temperature"], top_p=settings["top_p"], **limits)
        if assembly is not None:
            ctx.record.emit("knowledge", "model_result", assembly_id=assembly["assembly_id"],
                            messages_sha256=assembly["messages_sha256"], call_id=reply.call_id)
        data["request_outcomes"][stage] = {"status": "returned", "call_id": reply.call_id,
                                            "finish_reason": reply.finish_reason}
        return reply
    except ModelError as error:
        data["request_outcomes"][stage] = {"status": "error", "kind": error.kind, "reason": str(error)}
        ctx.record.emit("adaptive", "request_failed", stage=stage, kind=error.kind, reason=str(error))
        return None
    finally:
        _save(ctx, "completion-ledger", ledger.snapshot())
        _save(ctx, "request-outcomes", data["request_outcomes"])


def _plan_projection(analysis):
    """Routing metadata only; the original task stays authoritative for generation."""
    if analysis is None:
        return None
    return {
        "classification": {"kind": analysis.kind, "clocks": list(analysis.clocks),
                           "risks": list(analysis.risks)},
        "ambiguities": list(analysis.ambiguities),
    }


def _generation_messages(ctx, *, failure=None):
    data = _data(ctx)
    messages = ctx.prompts.render("repair.j2", task=ctx.task, feedback="", parent=None,
                              plan=_plan_projection(data.get("analysis")))
    if failure is not None:
        import json

        messages[-1]["content"] += (
            "\n\n## Previous delivery failure\n"
            + json.dumps(failure, ensure_ascii=False)
            + "\nThe previous response did not produce an accepted implementation. "
            "Recheck the public task and exact top name; a valid module name alone does not prove behavior. "
            "Deliver one complete implementation in one fenced verilog block in the final response. "
            "Do not only describe or plan the solution."
        )
    return messages


def _delivery_failure(reply, extraction, top):
    """Describe observed delivery evidence, without guessing why content is absent."""
    return {
        "source_call_id": reply.call_id,
        "finish_reason": reply.finish_reason,
        "required_top": top,
        "final_content_present": bool(reply.content.strip()),
        "kind": ("length_truncated" if reply.finish_reason == "length" else
                 "no_final_content" if not reply.content.strip() else "extraction_rejected"),
        "extraction": extraction.trace_dict(),
    }


def _candidate(ctx, reply, *, parent=None, stage="draft", extraction=None):
    if reply is None:
        return None
    extraction = extraction or extract_result(reply.content, ctx.task.top)
    _save(ctx, f"{stage}-extraction", extraction.trace_dict())
    ctx.record.emit('extract', 'delivery', source_call_id=reply.call_id, stage=stage,
                    parent_id=parent.id if parent else None, finish_reason=reply.finish_reason,
                    complete_new_draft=bool(extraction.status == 'ok' and extraction.complete
                        and extraction.target_module_found and not extraction.suspected_truncation))
    if (extraction.status != "ok" or not extraction.complete
            or not extraction.target_module_found or extraction.suspected_truncation):
        failure = _delivery_failure(reply, extraction, ctx.task.top)
        # Standalone extraction consumers also use this helper without workflow state.
        if "adaptive" in ctx.store:
            _data(ctx)[f"{stage}_failure"] = failure
        _save(ctx, f"{stage}-failure", failure)
        return None
    candidate = ctx.candidates.create(
        extraction.code, source_stage=f"adaptive_{stage}", round=2 if parent else 1,
        parent_id=parent.id if parent else None, finish_reason=reply.finish_reason,
        extraction_status=extraction.status, call_id=reply.call_id,
    )
    if parent is None:
        ctx.candidates.select(candidate.id, reason="complete_unverified_fallback")
    return candidate


@node("adaptive_initialize", reads=["settings"], writes=[])
def initialize(ctx: Ctx, state: State) -> State:
    if "adaptive" in ctx.store:
        raise ValueError("adaptive initialization must run exactly once")
    settings = state["settings"]
    ctx.store["adaptive"] = {
        "settings": settings, "ledger": CompletionLedger(ctx.budget, ctx.record,
            max_calls=settings["max_calls"], max_output_tokens=settings["max_output_tokens"]),
        "attempted": set(), "request_outcomes": {}, "assessments": {},
        "analysis": None, "routing": choose_route(ctx.task), "checker": None,
        "rescue_used": False, "repair_used": False, "checker_revision_used": False,
        "review_retry_used": False, "review_contract": {},
    }
    from agent.knowledge.policy import modes
    ctx.store["knowledge_rag_enabled"] = modes(settings['skill_mode'], settings['rag_mode'], rag=settings['rag'])[1] != 'off'
    _save(ctx, "settings", settings)
    return state


@node("adaptive_analyze", reads=[], writes=["route"])
def analyze(ctx: Ctx, state: State) -> State:
    data, settings = _data(ctx), _data(ctx)["settings"]
    reply = _request(ctx, "profile", analysis_request(ctx.task),
                     followup_s=settings["draft"]["timeout_s"] + settings["first_tools_s"], optional=False)
    if reply:
        try:
            data["analysis"] = parse_analysis(reply.content, ctx.task, finish_reason=reply.finish_reason)
            _save(ctx, "analysis", {"status": "valid", **data["analysis"].model_dump(mode="json")})
        except ValueError as error:
            _save(ctx, "analysis", {"status": "invalid", "reason": str(error)})
    data["routing"] = choose_route(ctx.task, data["analysis"], sequential_skill=settings["sequential_skill"])
    _save(ctx, "route", data["routing"].public_dict())
    return state.update(route=data["routing"].route)


@node("adaptive_generate", reads=[], writes=["target_id", "has_candidate", "stop_reason"])
def generate(ctx: Ctx, state: State) -> State:
    data = _data(ctx)
    reply = _request(ctx, "draft", _generation_messages(ctx), followup_s=data["settings"]["first_tools_s"], optional=False)
    # Only a well-formed HTTP reply establishes a usable service for one rescue.
    data["draft_reply"] = reply
    candidate = _candidate(ctx, reply)
    return state.update(target_id=candidate.id if candidate else None, has_candidate=candidate is not None,
                        stop_reason="" if candidate else "no_complete_first_draft")


@node("adaptive_rescue", reads=[], writes=["target_id", "has_candidate", "route", "stop_reason"])
def rescue(ctx: Ctx, state: State) -> State:
    data = _data(ctx)
    if ctx.candidates.selected_id is not None:
        raise ValueError("rescue cannot replace a complete first draft")
    data["rescue_used"] = True
    data["routing"] = replace(data["routing"], route="structural", reason="first_draft_rescue")
    reply = None
    draft_reply = data.get("draft_reply")
    if draft_reply is not None:
        failure = data.get("draft_failure")
        _save(ctx, "rescue-context", {
            "source_call_id": getattr(draft_reply, "call_id", None),
            "failure_present": failure is not None,
            "reason": "draft_failure_present" if failure is not None else "draft_failure_missing",
        })
        reply = _request(ctx, "rescue", _generation_messages(ctx, failure=failure), limits=data["settings"]["draft"],
                         followup_s=data["settings"]["first_tools_s"], optional=False)
    else:
        _save(ctx, "rescue-context", {
            "source_call_id": None, "failure_present": False,
            "reason": "first_draft_request_failed",
        })
    candidate = _candidate(ctx, reply, stage="rescue")
    return state.update(target_id=candidate.id if candidate else None, has_candidate=candidate is not None,
                        route="structural", stop_reason="rescue_structural_only" if candidate else "no_complete_candidate")


@node("adaptive_build_checker", reads=["route"], writes=["checker_status"])
def build_checker(ctx: Ctx, state: State) -> State:
    data, settings = _data(ctx), _data(ctx)["settings"]
    if state["route"] == "structural":
        return state.update(checker_status="not_requested")
    followup = (settings["review"]["timeout_s"] + settings["revision"]["timeout_s"]
                + settings["rereview"]["timeout_s"] + _rtl_followup(settings))
    reply = _request(ctx, "construction", checker_request(ctx.task, state["route"]), followup_s=followup)
    if reply is None:
        return state.update(checker_status="unavailable")
    draft = parse_checker(reply.content, ctx.task, state["route"], finish_reason=reply.finish_reason)
    data["checker_draft"] = draft
    _save(ctx, "checker-draft", draft.public_dict())
    if draft.preflight.get("format_correction_eligible"):
        data["checker_syntax_reply"] = reply
        return state.update(checker_status="format_invalid")
    return state.update(checker_status=draft.status)


@node("adaptive_correct_checker_format", reads=[], writes=["checker_status"])
def correct_checker_format(ctx: Ctx, state: State) -> State:
    data = _data(ctx)
    if data["checker_revision_used"]:
        raise ValueError("checker recovery is limited to one format correction or semantic revision")
    original, prior_reply = data["checker_draft"], data["checker_syntax_reply"]
    data["checker_revision_used"] = True
    draft = recover_checker_format(ctx.task, original, prior_reply.content,
                                   finish_reason=prior_reply.finish_reason)
    data["checker_draft"] = draft
    _save(ctx, "checker-format-corrected-draft", draft.public_dict())
    lineage = {"attempt": 1, "original_call_id": prior_reply.call_id,
               "original_response_sha256": original.preflight["response_sha256"],
               "original_draft_artifact": "adaptive/checker-draft.json",
               "method": "local_punctuation", "model_calls": 0,
               "status": draft.status, "checker_hash": draft.checker_hash or None,
               "reason": draft.reason, "binding": draft.preflight.get("format_correction")}
    data["checker_format_correction"] = lineage
    _save(ctx, "checker-format-correction", lineage)
    return state.update(checker_status=draft.status)


def _rtl_followup(settings):
    return settings["first_tools_s"] + settings["repair"]["timeout_s"] + settings["recheck_tools_s"]


def _review_record(frozen, stage, *, model_calls):
    violations = []
    for item in getattr(frozen, "violations", None) or []:
        violations.append(item if isinstance(item, str) else str(item))
    return {"stage": stage, "attempts": model_calls, "status": frozen.status,
            "violations": violations, "model_calls": model_calls}


def _record_review_contract(ctx, stage, contract):
    data = _data(ctx)
    data.setdefault("review_contract", {})[stage] = contract
    _save(ctx, "review-contract", data["review_contract"])
    return contract


def _review_checker(ctx, draft, stage):
    data, settings = _data(ctx), _data(ctx)["settings"]
    followup = _rtl_followup(settings)
    if stage == "review" and not data["checker_revision_used"]:
        followup += settings["revision"]["timeout_s"] + settings["rereview"]["timeout_s"]
    reply = _request(ctx, stage, review_request(ctx.task, draft), followup_s=followup)
    if reply is None:
        _record_review_contract(ctx, stage, {"stage": stage, "attempts": 0,
                                             "status": "not_sent", "violations": [],
                                             "model_calls": 0})
        return None
    frozen = approve_review(reply.content, draft, finish_reason=reply.finish_reason)
    contract = _review_record(frozen, stage, model_calls=1)
    # One controlled retry only when the host rejected the review contract itself and
    # the freeze is retryable. A semantic reject or unknown is never retried.
    if stage == "review" and not data["review_retry_used"] and frozen.status == "invalid":
        contract["first_status"] = frozen.status
        contract["retryable"] = bool(getattr(frozen, "retryable", False))
        if contract["retryable"]:
            data["review_retry_used"] = True
            contract["first_violations"] = contract["violations"]
            retry = _request(ctx, "review_retry",
                             review_request(ctx.task, draft, violations=contract["violations"]),
                             followup_s=followup)
            contract.update(attempts=2, retry_used=True)
            if retry is None:
                contract["retry_status"] = "not_sent"
            else:
                frozen = approve_review(retry.content, draft, finish_reason=retry.finish_reason)
                contract.update(model_calls=2, status=frozen.status, retry_status=frozen.status,
                                violations=_review_record(frozen, stage, model_calls=2)["violations"])
    _record_review_contract(ctx, stage, contract)
    data["checker"] = frozen
    _save(ctx, "checker-initial-review" if stage == "review" else "checker-revised-review", frozen.public_dict())
    _save(ctx, "frozen-checker", frozen.public_dict())
    return frozen


@node("adaptive_review_checker", reads=[], writes=["checker_status"])
def review_checker(ctx: Ctx, state: State) -> State:
    data = _data(ctx)
    frozen = _review_checker(ctx, data["checker_draft"], "review")
    status = frozen.status if frozen else "review_unavailable"
    if status == "rejected":
        if data["checker_revision_used"]:
            status = "rejected_after_format_correction"
        elif data["review_retry_used"]:
            # The single contract retry consumes the one recovery slot: a revision
            # would exceed the 7-call completion bound, so finish instead.
            data["checker_revision_used"] = True
            status = "rejected_after_review_retry"
    return state.update(checker_status=status)


@node("adaptive_revise_checker", reads=[], writes=["checker_status"])
def revise_checker(ctx: Ctx, state: State) -> State:
    data, settings = _data(ctx), _data(ctx)["settings"]
    if data["checker_revision_used"]:
        raise ValueError("only one checker revision is allowed")
    original, rejected = data["checker_draft"], data["checker"]
    # The component validates the formal rejection before a request can be sent.
    messages = revision_request(ctx.task, original, rejected)
    data["checker_revision_used"] = True
    lineage = {"attempt": 1, "parent_checker_hash": original.checker_hash,
               "initial_review_artifact": "adaptive/checker-initial-review.json",
               "revised_checker_hash": None, "status": "started"}
    data["checker_revision"] = lineage
    _save(ctx, "checker-revision", lineage)
    reply = _request(ctx, "revision", messages,
                     followup_s=settings["rereview"]["timeout_s"] + _rtl_followup(settings))
    lineage.update(status="unavailable", request=data["request_outcomes"]["revision"])
    if reply is not None:
        draft = parse_checker_revision(reply.content, ctx.task, original, rejected,
                                       finish_reason=reply.finish_reason)
        data["revised_checker_draft"] = draft
        _save(ctx, "checker-revised-draft", draft.public_dict())
        lineage.update(status=draft.status, revised_checker_hash=draft.checker_hash or None,
                       binding=draft.preflight.get("revision"), reason=draft.reason)
    _save(ctx, "checker-revision", lineage)
    return state.update(checker_status=lineage["status"])


@node("adaptive_rereview_checker", reads=[], writes=["checker_status"])
def rereview_checker(ctx: Ctx, state: State) -> State:
    data = _data(ctx)
    frozen = _review_checker(ctx, data["revised_checker_draft"], "rereview")
    status = frozen.status if frozen else "rereview_unavailable"
    data["checker_revision"].update(status=status,
                                    rereview_artifact="adaptive/checker-revised-review.json" if frozen else None,
                                    rereview_request=data["request_outcomes"]["rereview"])
    _save(ctx, "checker-revision", data["checker_revision"])
    return state.update(checker_status=status)


def _check_candidate(ctx, candidate, allowance_s) -> CandidateAssessment:
    from agent.rtl.adaptive_selection import check_plan_hash
    from agent.rtl.observation import observe, sampling_plan_from_suite
    from agent.rtl.properties import evaluate_properties
    from agent.rtl.adaptive_execute import evaluate_model

    data, frozen = _data(ctx), _data(ctx)["checker"]
    approved = frozen is not None and frozen.repair_authorized
    plan = (frozen.payload["sampling"] if frozen.route == "properties"
            else sampling_plan_from_suite(frozen.payload)) if approved else None
    end = time.monotonic() + allowance_s
    assessment = CandidateAssessment(
        candidate_id=candidate.id, candidate_hash=candidate.code_hash,
        parent_id=candidate.parent_id,
        parent_hash=ctx.candidates.get(candidate.parent_id).code_hash if candidate.parent_id else None,
        execution_id=uuid.uuid4().hex, checker_hash=frozen.checker_hash if approved else "",
        check_plan_hash=check_plan_hash(frozen) if approved else "",
        checker_implementation_hash=checker_hash(),
        behavior=BehaviorAssessment(route=frozen.route if approved else "structural"),
    )

    def run_structure(stage, *, skipped=False):
        remaining = min(end - time.monotonic(), ctx.budget.remaining())
        if skipped or remaining <= 0:
            check = bind_result(CheckResult(
                "skipped" if skipped else "timeout", "prior structural stage incomplete" if skipped else "tool allowance exhausted",
                failure_kind="unknown" if skipped else "timeout"), candidate, stage)
        else:
            check = ctx.call(stage, candidate_id=candidate.id, **({} if stage == "interface" else {"timeout_s": remaining}))
        check = replace(check, details={**check.details, "execution_id": uuid.uuid4().hex})
        assessment.structure[stage] = check
        _save(ctx, f"assessments/{candidate.id}/{stage}", check.trace_dict())
        return check

    interface = run_structure("interface")
    # A candidate declaration our parser cannot read still needs a compiler
    # diagnosis. Keep the interface error intact: it cannot authorize a repair,
    # functional sampling, or promotion of an unverifiable child on its own.
    candidate_parse_error = (
        interface.status == "error" and interface.failure_kind == "unknown"
        and interface.details.get("parse_error_scope") == "candidate"
    )
    compile_allowed = not interface.blocking or candidate_parse_error
    lint = run_structure("lint", skipped=not compile_allowed)
    if approved and lint.status == "passed" and not interface.blocking and end > time.monotonic():
        with ctx.record.span("adaptive_observe", candidate_id=candidate.id, route=frozen.route):
            trace = observe(ctx, candidate, plan, timeout_s=end - time.monotonic())
            data.setdefault("observations", {})[candidate.id] = trace
            _save(ctx, f"assessments/{candidate.id}/observations", trace.public_dict())
        observation_status = "passed" if trace.status == "complete" else (
            "failed" if trace.failure_kind == "code" else trace.status)
        observation_check = bind_result(CheckResult(
            observation_status, trace.summary, rc=0 if trace.status == "complete" else (trace.rc or 1),
            failure_kind=trace.failure_kind, elapsed_s=trace.elapsed_s, log_paths=tuple(trace.log_paths),
            details={"execution_id": trace.execution_id, "plan_hash": trace.plan_hash,
                     "sampling_status": trace.status}), candidate, "observation")
        assessment.structure["observation"] = observation_check
        _save(ctx, f"assessments/{candidate.id}/observation-check", observation_check.trace_dict())
        if trace.status == "complete":
            details = evaluate_properties(frozen.payload, trace) if frozen.route == "properties" else evaluate_model(frozen.payload, trace)
            status = details.get("status") if frozen.route == "properties" else (
                "failed" if details["failed_cases"] else "unknown" if details["unknown_cases"]
                else "untested" if details["untested_cases"] else "passed" if details["compared_bits"] else "untested")
        else:
            details, status = trace.public_dict(), trace.status
        details = {**details, "checker_hash": assessment.checker_implementation_hash}
        assessment.behavior = BehaviorAssessment(
            route=frozen.route, status=status, failure_kind=trace.failure_kind, details=details,
        )
        _save(ctx, f"assessments/{candidate.id}/behavior", assessment.behavior.public_dict())
    run_structure("synth", skipped=lint.status != "passed" or not compile_allowed)
    data["assessments"][candidate.id] = assessment
    _save(ctx, f"assessments/{candidate.id}/assessment", assessment.public_dict())
    return assessment


@node("adaptive_check", reads=["target_id"], writes=[])
def check(ctx: Ctx, state: State) -> State:
    _check_candidate(ctx, ctx.candidates.get(state["target_id"]), _data(ctx)["settings"]["first_tools_s"])
    return state


@node("adaptive_decide", reads=["target_id"], writes=["action", "stop_reason"])
def decide(ctx: Ctx, state: State) -> State:
    from agent.rtl.adaptive_selection import repair_opportunity

    data = _data(ctx)
    assessment = data["assessments"][state["target_id"]]
    opportunity = repair_opportunity(assessment.public_dict(), data["checker"])
    data["opportunity"] = opportunity
    allowed = opportunity is not None and not data["rescue_used"] and not data["repair_used"]
    _save(ctx, "repair-opportunity", {"opportunity": opportunity, "allowed": allowed})
    return state.update(action="repair" if allowed else "finish", stop_reason="repair_available" if allowed else "assessment_complete")


@node("adaptive_repair", reads=["target_id"], writes=["target_id", "parent_id", "action", "stop_reason"])
def repair(ctx: Ctx, state: State) -> State:
    data = _data(ctx)
    if data["repair_used"] or data["rescue_used"]:
        raise ValueError("only one RTL repair is allowed, and none after rescue")
    data["repair_used"] = True
    parent = ctx.candidates.get(state["target_id"])
    prompt_evidence = dict(data["opportunity"])
    observation = data.get("observations", {}).get(parent.id)
    if observation is not None and prompt_evidence.get("counterexample"):
        import json

        counterexample = prompt_evidence["counterexample"]
        case_id = counterexample["case_id"]
        last_step = counterexample.get("end_step", counterexample.get("step", counterexample.get("trigger_step", 0)))
        history = [{"step": row["step"], "phase": row["phase"], "clock_tick": row["clock_tick"], "values": row["values"]}
                   for row in observation.rows if row["case_id"] == case_id and row["step"] <= last_step]
        omitted = []
        # Full reset-to-failure observations stay in the saved artifact. If a wide
        # interface is too large, remove oldest intermediate pairs, never bits.
        while len(history) > 4 and len(json.dumps(history)) > 20000:
            removed = history.pop(2)
            omitted.append({"step": removed["step"], "phase": removed["phase"]})
        prompt_evidence["observations"] = {"case_id": case_id, "rows": history,
            "omitted": omitted, "complete_history_artifact": observation.artifacts.get("rows")}
    evidence = None
    for stage in ("lint", "synth"):
        check = data["assessments"][parent.id].structure.get(stage)
        if check and check.status == "failed" and check.failure_kind == "code":
            evidence = {"check": check, "execution_id": check.details["execution_id"]}
            break
    checker = _approved_checker(ctx)
    if prompt_evidence.get("kind") == "behavior" and checker is not None:
        # Only the public checker schema is exposed so the model can name a real requirement.
        prompt_evidence["requirement_ids"] = [item["id"] for item in
                                              checker.payload.get("requirements") or []]
    else:
        failure = prompt_evidence.get("failure")
        details = failure.get("details") if isinstance(failure, dict) else None
        prompt_evidence["diagnostic_codes"] = diagnostic_codes(details)
    _save(ctx, "repair-evidence", prompt_evidence)
    reply = _request(ctx, "repair", repair_request(ctx.task, parent, prompt_evidence,
                     checker if prompt_evidence["kind"] == "behavior" else None),
                     followup_s=data["settings"]["recheck_tools_s"], parent=parent, evidence=evidence)
    if reply is None:
        return state.update(action="finish", stop_reason="repair_not_completed")
    try:
        decision, extraction = parse_repair(
            reply.content, ctx.task.top, task=ctx.task, evidence=prompt_evidence,
            checker_payload=checker.payload if checker is not None else None,
            finish_reason=reply.finish_reason)
        _save(ctx, "repair-decision", decision)
    except ValueError as error:
        _save(ctx, "repair-decision", {"status": "invalid", "reason": str(error)})
        return state.update(action="finish", stop_reason="repair_invalid")
    if decision["decision"] != "rtl_error":
        data["repair_authority_revoked"] = decision["decision"]
        return state.update(action="finish", stop_reason=decision["decision"])
    child = _candidate(ctx, reply, parent=parent, stage="repair", extraction=extraction)
    if child is None or child.code_hash == parent.code_hash:
        return state.update(action="finish", stop_reason="repair_unchanged" if child else "repair_incomplete")
    return state.update(target_id=child.id, parent_id=parent.id, action="recheck", stop_reason="awaiting_recheck")


@node("adaptive_recheck", reads=["target_id"], writes=[])
def recheck(ctx: Ctx, state: State) -> State:
    _check_candidate(ctx, ctx.candidates.get(state["target_id"]), _data(ctx)["settings"]["recheck_tools_s"])
    return state


@node("adaptive_select", reads=["target_id", "parent_id"], writes=["stop_reason"])
def select(ctx: Ctx, state: State) -> State:
    from agent.rtl.adaptive_selection import promotion_decision

    data = _data(ctx)
    outcome = promotion_decision(
        data["assessments"][state["parent_id"]].public_dict(),
        data["assessments"][state["target_id"]].public_dict(),
        repair_kind=data["opportunity"]["kind"], checker=_approved_checker(ctx),
    )
    data["selection"] = outcome
    _save(ctx, "selection", outcome)
    if outcome["allowed"]:
        ctx.candidates.select(state["target_id"], reason=outcome["reason"])
    return state.update(stop_reason=outcome["reason"])


@node("adaptive_finish", reads=["stop_reason", "checker_status"], writes=["status", "stop_reason"])
def finish(ctx: Ctx, state: State) -> State:
    data = _data(ctx)
    selected = ctx.candidates.selected_id
    assessment = data["assessments"].get(selected)
    structural_passed = assessment is not None and assessment.structural_passed
    functional_passed = assessment is not None and assessment.behavior.status == "passed"
    status = "completed" if structural_passed and functional_passed and not data.get("repair_authority_revoked") else "stopped"
    _save(ctx, "result", {
        "status": status, "selected_id": selected, "delivery": "complete_rtl" if selected else "empty",
        "stop_reason": state["stop_reason"], "checker_status": state["checker_status"],
        "route": data["routing"].public_dict(), "structural_passed": structural_passed,
        "interface_verified": assessment is not None and assessment.interface_verified,
        "functional_passed": functional_passed, "assessment": assessment.public_dict() if assessment else {},
        "coverage_scope": assessment.behavior.route if assessment else "structural",
        "semantic_completeness_proven": False,
        "repair_authority_revoked": data.get("repair_authority_revoked"),
        "checker_revision": data.get("checker_revision"),
        "checker_format_correction": data.get("checker_format_correction"),
        "review_contract": data.get("review_contract") or {},
        "review_retry_used": data.get("review_retry_used", False),
        "selection": data.get("selection"), "request_outcomes": data["request_outcomes"],
        "budget": data["ledger"].snapshot(),
    })
    return state.update(status=status, stop_reason=state["stop_reason"] or "assessment_complete")
