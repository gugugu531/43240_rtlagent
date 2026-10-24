"""Small visible actions for the independent design/verify state machine."""

import hashlib
import json
from agent.kit import Ctx, State, node
from agent.nodes.checks import check_stages, remember_repair_check, repair_feedback
from agent.nodes.suite import build_suite
from agent.nodes.plan import _quoted
from agent.nodes.recovery import rtl_repair_blocker, stop
from agent.nodes.structured import request
from agent.rtl.specification import resolve_requirement
from agent.rtl.suite.model import (
    SuiteError, suite_hash, require_comparable_expectations,
    require_requirement_coverage,
)
from agent.rtl.suite.evaluate import coverage_summary, analyze_expectations


def candidate_compile_failure(check, candidate):
    """Only source-attributed, bound compiler diagnostics permit an RTL edit."""
    details = check.details
    return (
        check.status == "error"
        and check.failure_kind == "code"
        and details.get("failure_kind") == "code"
        and details.get("attribution") == "candidate"
        and check.candidate_id == candidate.id
        and details.get("candidate_hash") == candidate.code_hash
        and bool(details.get("repair_diagnostics", {}).get("items"))
    )


def stimuli(suite):
    clocks = suite.get("clocks", {})
    if suite.get("clock"):
        clocks = {suite["clock"]["port"]: {"edge": suite["clock"]["edge"]}}
    # Validation has already rejected values outside their declared domains.
    # Signed and unsigned spellings of the SAME legal bit pattern are not new stimuli.
    return {
        json.dumps(
            {
                "clocks": clocks,
                "steps": [
                    {
                        "inputs": {
                            name: value & ((1 << suite["ports"][name]["width"]) - 1)
                            for name, value in step["inputs"].items()
                        },
                        "edges": sorted(
                            step.get("edges", clocks if step.get("edge", True) else [])
                        ),
                        "sample": step.get("sample", True),
                    }
                    for step in case["steps"]
                ],
            },
            sort_keys=True,
        )
        for case in suite["cases"]
    }


def comparison_stimuli(suite, analysis):
    """Count only histories that reach a predicted comparison, never unseen tails."""
    return {event["comparison_signature"] for event in analysis["comparison_events"]}


@node(
    "design_dedupe",
    reads=[
        "target_id",
        "round",
        "unchanged_attempts",
        "unchanged_retries",
        "max_rounds",
    ],
    writes=[
        "action",
        "feedback",
        "stop_reason",
        "status",
        "unchanged_attempts",
        "verification_actions",
    ],
)
def dedupe(ctx: Ctx, state: State) -> State:
    candidate = ctx.candidates.get(state["target_id"])
    ctx.store["candidates"][candidate.id] = candidate
    seen = ctx.store["seen"]
    if candidate.code_hash in seen:
        attempts = state.get("unchanged_attempts", 0)
        if (
            attempts < state["unchanged_retries"]
            and state["round"] < state["max_rounds"]
        ):
            ctx.record.emit(
                "unchanged_repair",
                "result",
                candidate_id=candidate.id,
                parent_id=candidate.parent_id,
                attempt=attempts + 1,
                code_hash=candidate.code_hash,
                action="feedback_without_rechecking",
            )
            return state.update(
                action="generate",
                unchanged_attempts=attempts + 1,
                feedback="[modification_not_applied] RTL repeats an earlier candidate exactly. Apply a real localized "
                "correction to complete code; preserve required procedural variable types.\n"
                + state.get("feedback", ""),
            )
        return stop(state, "repeated_candidate")
    seen.add(candidate.code_hash)
    return state.update(action="structure", verification_actions=0)


@node(
    "design_structure",
    reads=["target_id", "suite_status"],
    writes=["action", "feedback", "stop_reason", "status"],
)
def structure(ctx: Ctx, state: State) -> State:
    candidate = ctx.candidates.get(state["target_id"])
    ctx.store["structural"][candidate.id] = False
    failed = check_stages(ctx, candidate, ["interface", "lint"])
    if failed:
        if failed.failure_kind != "code":
            return stop(state, "structure_" + failed.failure_kind)
        feedback = repair_feedback(failed)
        ctx.record.emit(
            "repair_feedback",
            "result",
            check_id=failed.id,
            candidate_id=candidate.id,
            diagnostics=failed.details.get("repair_diagnostics", {}),
            feedback_hash=hashlib.sha256(feedback.encode()).hexdigest(),
        )
        return state.update(action="generate", feedback=feedback)
    ctx.store["structural"][candidate.id] = True
    if not ctx.store["structural"].get(ctx.candidates.selected_id):
        ctx.candidates.select(candidate.id, reason="compiled_fallback")
    return state.update(action="functional" if ctx.store["suites"] else "synth_only")


def select_comparable(ctx):
    candidates, structural, evidence, suites = (
        ctx.store[k] for k in ("candidates", "structural", "evidence", "suites")
    )
    selected = ctx.candidates.selected_id

    def passed(cid):
        return {
            (key, case)
            for key in suites
            for case in evidence[cid, key].details.get("passed_cases", ())
        }

    for cid in candidates:
        if not structural.get(cid) or cid == selected:
            continue
        if any(evidence[cid, key].status not in ("passed", "failed") for key in suites):
            continue
        old = passed(selected) if structural.get(selected) else set()
        if old < passed(cid):
            ctx.candidates.select(
                cid, reason="same_active_suites_preserved_cases_and_improved"
            )
            selected = cid


@node(
    "design_functional",
    reads=[
        "target_id",
        "checker_revisions",
        "verification_actions",
        "acceptance_attempted",
        "round",
        "max_rounds",
    ],
    writes=[
        "action",
        "stop_reason",
        "status",
        "checker_unknown",
        "verification_actions",
        "feedback",
    ],
)
def functional(ctx: Ctx, state: State) -> State:
    count = state.get("verification_actions", 0) + 1
    if count > state["checker_revisions"] + 3:
        return stop(state, "verification_action_limit")
    state = state.update(verification_actions=count)
    candidates, structural, evidence, suites = (
        ctx.store[k] for k in ("candidates", "structural", "evidence", "suites")
    )
    for cid, candidate in candidates.items():
        if not structural.get(cid):
            continue
        for key, suite in suites.items():
            if (cid, key) not in evidence:
                evidence[cid, key] = ctx.call(
                    "functional", candidate_id=candidate.id, suite=suite
                )
    checks = [evidence[state["target_id"], key] for key in suites]
    candidate = candidates[state["target_id"]]
    compile_failure = next(
        (check for check in checks if candidate_compile_failure(check, candidate)),
        None,
    )
    if compile_failure:
        if reason := rtl_repair_blocker(ctx, state, origin="functional_compile"):
            return stop(state, reason)
        feedback = repair_feedback(compile_failure)
        ctx.record.emit(
            "repair_feedback",
            "result",
            check_id=compile_failure.id,
            candidate_id=candidate.id,
            origin="functional_compile",
            diagnostics=compile_failure.details["repair_diagnostics"],
            feedback_hash=hashlib.sha256(feedback.encode()).hexdigest(),
        )
        return state.update(action="generate", feedback=feedback, checker_unknown=False)
    unresolved = next(
        (check for check in checks if check.status not in ("passed", "failed")), None
    )
    unknown = bool(
        unresolved
        and unresolved.status == "skipped"
        and (
            unresolved.details.get("attribution") == "checker_uninformative"
            or any(
                unresolved.details.get(name, 0)
                for name in ("unknown_expected", "guard_unknown", "mask_unknown")
            )
        )
    )
    if unresolved and not unknown:
        return stop(state, "functional_" + unresolved.status)
    select_comparable(ctx)
    failing = (
        unresolved
        if unknown
        else next((check for check in checks if check.status == "failed"), None)
    )
    if failing:
        key = str(failing.details.get("suite_hash", ""))
        if key not in suites:
            return stop(state, "missing_suite_identity")
        ctx.store["failing"] = failing
        ctx.store["failing_suite"] = key
        return state.update(action="diagnose", checker_unknown=unknown)
    return state.update(
        action="final_synth" if state.get("acceptance_attempted") else "acceptance",
        checker_unknown=False,
    )


@node(
    "design_diagnose",
    reads=[
        "target_id", "checker_unknown", "revisions", "checker_revisions",
        "round", "max_rounds",
    ],
    writes=["action", "feedback", "stop_reason", "status"],
)
def diagnose(ctx: Ctx, state: State, *, max_tokens: int = 8192) -> State:
    candidate = ctx.candidates.get(state["target_id"])
    failing, key = ctx.store["failing"], ctx.store["failing_suite"]
    suite = ctx.store["suites"][key]
    first = failing.details.get("first_mismatch")
    traces = failing.details.get("traces", [])
    window = (
        traces[:5]
        if not first
        else [
            t
            for t in traces
            if t["case_id"] == first["case_id"]
            and first["step"] - 3 <= t["step"] <= first["step"] + 2
        ]
    )
    diagnosis = request(
        ctx,
        "Analyze the earliest mismatch. Neither RTL nor generated checker is trusted. Return attribution "
        "rtl|plan|checker|uncertain, quote (exact task excerpt), reason (specific cause), repair_feedback "
        "(localized change), and optional revision:{target:outputs|state_next|async_reset_values,names:[existing signals]}. "
        "Revision identifies only expressions to re-derive from public requirements; do not send actual values, RTL "
        "snippets or proposed replacement behavior to the builder. Never weaken tests. Unknown expected values "
        "alone do not justify an RTL repair: choose checker only with a public requirement proving an omitted "
        "transition, otherwise uncertain.",
        "functional_diagnosis",
        {
            "plan": ctx.store["plan"],
            "rtl": candidate.code,
            "suite": suite,
            "first_mismatch": first,
            "trace_window": window,
            "check_status": failing.status,
            "expectation_analysis": failing.details.get("expectation_analysis", {}),
        },
        max_tokens,
    )
    if (
        diagnosis.status != "ready"
        or not _quoted(diagnosis.data, ctx.task)
        or not diagnosis.data.get("reason")
    ):
        return stop(state, "diagnosis_unresolved")
    cause = diagnosis.data["attribution"]
    if state.get("checker_unknown") and cause != "checker":
        return stop(state, "checker_unknown_unresolved")
    ctx.store["diagnosis"] = diagnosis
    ctx.record.emit(
        "functional_diagnosis",
        "result",
        candidate_id=candidate.id,
        check_id=failing.id,
        suite_hash=key,
        diagnosis=diagnosis.data,
    )
    if cause in ("plan", "rtl"):
        if reason := rtl_repair_blocker(ctx, state, origin="diagnosis_" + cause):
            return stop(state, reason)
    feedback = json.dumps(
        {"diagnosis": diagnosis.data, "first_mismatch": first, "trace_window": window},
        ensure_ascii=False,
    )
    if cause == "checker" and state.get("revisions", 0) < state["checker_revisions"]:
        return state.update(action="revise_suite")
    if cause == "plan":
        return state.update(
            action="revise_plan",
            feedback=str(diagnosis.data.get("repair_feedback", "")),
        )
    if cause == "rtl":
        return state.update(action="generate", feedback=feedback)
    return stop(state, "diagnosis_" + cause)


@node(
    "revise_suite",
    reads=["revisions"],
    writes=["action", "revisions", "stop_reason", "status"],
)
def revise_suite(ctx: Ctx, state: State) -> State:
    diagnosis, key = ctx.store["diagnosis"], ctx.store["failing_suite"]
    suite = ctx.store["suites"][key]
    revision = diagnosis.data.get("revision")
    if not isinstance(revision, dict):
        return stop(state, "checker_correction_missing")
    target, names = revision.get("target"), revision.get("names")
    signals = (
        suite.get("outputs", {}) if target == "outputs" else suite.get("state", {})
    )
    if (
        target not in ("outputs", "state_next", "async_reset_values")
        or not names
        or any(n not in signals for n in names)
    ):
        return stop(state, "checker_correction_invalid")
    correction = json.dumps(
        {
            "kind": "specification_revision",
            "origin": "code_aware_diagnosis",
            "quote": resolve_requirement(
                diagnosis.data, ctx.task.prompt + "\n" + ctx.task.interface
            )["quote"],
            "target": target,
            "names": names,
        },
        ensure_ascii=False,
    )
    revised = build_suite(
        ctx, feedback=correction, previous=suite, **ctx.store["suite_options"]
    )
    state = state.update(revisions=state.get("revisions", 0) + 1)
    if revised.status != "ready" or suite_hash(revised.suite) == key:
        return stop(state, "checker_revision_invalid")
    newkey = suite_hash(revised.suite)
    del ctx.store["suites"][key]
    ctx.store["suites"][newkey] = revised.suite
    ctx.record.emit(
        "suite_retired",
        "result",
        suite_hash=key,
        replacement=newkey,
        diagnosis_call_id=diagnosis.call_id,
        reason=diagnosis.data["reason"],
    )
    # Preserve the one-per-run independent acceptance bound, including revisions.
    return state.update(action="functional")


@node(
    "design_acceptance",
    reads=["acceptance_attempted"],
    writes=["action", "acceptance_attempted", "acceptance_outcome"],
)
def acceptance(ctx: Ctx, state: State) -> State:
    suites = ctx.store["suites"]
    state = state.update(acceptance_attempted=True)
    coverage = coverage_summary(suites.values())
    ctx.record.emit("functional_coverage", "result", **coverage)
    if coverage["stateless_exhaustive"]:
        ctx.record.emit("acceptance_exhaustive", "result", **coverage)
        return state.update(
            action="final_synth", acceptance_outcome="exhaustive_combinational_domain"
        )
    built = build_suite(
        ctx,
        feedback="Independent final acceptance: prepare new directed scenarios for omitted "
        "requirements and boundaries. Do not read implementation, plans, past failures, or existing suite.",
        **ctx.store["suite_options"],
    )
    outcome = "acceptance_" + built.status
    if built.status == "ready":
        try:
            analysis = require_comparable_expectations(
                built.suite, task_text=ctx.task.prompt + "\n" + ctx.task.interface
            )
            requirement_coverage = require_requirement_coverage(built.suite)
        except SuiteError as error:
            ctx.record.emit(
                "acceptance_contract", "invalid", reason=str(error),
                suite_hash=suite_hash(built.suite), semantic_coverage_proven=False,
            )
            return state.update(
                action="final_synth", acceptance_outcome="acceptance_contract_invalid"
            )
        key = suite_hash(built.suite)
        known = set().union(*(stimuli(s) for s in suites.values()))
        fresh = stimuli(built.suite) - known
        known_comparisons = set().union(*(
            comparison_stimuli(s, analyze_expectations(s)) for s in suites.values()
        ))
        fresh_comparisons = comparison_stimuli(built.suite, analysis) - known_comparisons
        ctx.record.emit(
            "acceptance_contract", "validated", **requirement_coverage,
            covered_source_ids=sorted({
                r["source_id"] for r in requirement_coverage["requirements"]
                if r.get("source_id")
            }),
            new_comparison_events=len(fresh_comparisons),
        )
        if key not in suites and fresh_comparisons:
            suites[key] = built.suite
            ctx.record.emit(
                "acceptance_promoted",
                "result",
                suite_hash=key,
                new_stimulus_sequences=len(fresh),
                new_comparison_events=len(fresh_comparisons),
                requirement_coverage=requirement_coverage,
                coverage=coverage_summary(suites.values()),
            )
            return state.update(action="functional", acceptance_outcome="")
        outcome = "acceptance_repeated_suite"
    ctx.record.emit(
        "acceptance_incomplete",
        "result",
        reason=outcome,
        action="synthesize_existing_checked_candidate",
    )
    return state.update(action="final_synth", acceptance_outcome=outcome)


@node(
    "design_synth",
    reads=["target_id", "suite_status", "acceptance_outcome"],
    writes=["action", "feedback", "stop_reason", "status"],
)
def synthesis(ctx: Ctx, state: State, *, structure_only: bool = False) -> State:
    candidate = ctx.candidates.get(state["target_id"])
    check = ctx.call("synth", candidate_id=candidate.id)
    remember_repair_check(ctx, check)
    if check.status == "passed":
        ctx.candidates.select(
            candidate.id,
            reason="structure_only_checker_" + state["suite_status"]
            if structure_only
            else "all_active_self_checks_and_synth_passed",
        )
        if structure_only:
            return stop(state, "functional_" + state["suite_status"])
        outcome = state.get("acceptance_outcome", "")
        if outcome and outcome != "exhaustive_combinational_domain":
            return stop(state, outcome)
        return state.update(
            action="finish",
            status="completed",
            stop_reason="self_checks_exhaustive_and_synth_passed"
            if outcome
            else "self_checks_and_synth_passed",
        )
    if check.failure_kind == "code":
        return state.update(action="generate", feedback=repair_feedback(check))
    return stop(state, "synth_" + check.failure_kind)


@node(
    "design_next_round",
    reads=["round", "max_rounds"],
    writes=["action", "stop_reason", "status"],
)
def next_round(ctx: Ctx, state: State) -> State:
    return (
        state.update(action="generate")
        if state["round"] < state["max_rounds"]
        else stop(state, "round_limit")
    )
