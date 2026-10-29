"""Public tools and graph actions share the same checking implementations."""

import json
import uuid
from agent.kit import Ctx, State, node, tool
from agent.domain.rtl.interface import check_interface
from agent.domain.rtl.result import bind_result
from agent.domain.rtl.vivado import lint as run_lint, synth as run_synth
from agent.domain.rtl.suite.testbench import simulate


@tool("interface_check")
def interface(ctx: Ctx, candidate_id: str):
    candidate = ctx.candidates.get(candidate_id)
    return bind_result(check_interface(ctx, candidate), candidate, "interface")


@tool("vivado_lint")
def lint(ctx: Ctx, candidate_id: str, *, timeout_s: float = 300):
    candidate = ctx.candidates.get(candidate_id)
    return bind_result(run_lint(ctx, candidate, timeout_s=timeout_s), candidate, "lint")


@tool("vivado_synth")
def synth(ctx: Ctx, candidate_id: str, *, timeout_s: float = 300):
    candidate = ctx.candidates.get(candidate_id)
    return bind_result(
        run_synth(ctx, candidate, timeout_s=timeout_s), candidate, "synth"
    )


@tool("functional_sim")
def functional(ctx: Ctx, candidate_id: str, suite: dict, *, timeout_s: float = 300):
    candidate = ctx.candidates.get(candidate_id)
    return bind_result(
        simulate(ctx, candidate, suite, timeout_s=timeout_s),
        candidate,
        "functional",
        suite,
    )


def repair_feedback(check):
    diagnostics = check.details.get("repair_diagnostics", {})
    return json.dumps(
        {
            "kind": check.kind,
            "check_id": check.id,
            "candidate_id": check.candidate_id,
            "status": check.status,
            "diagnostics": diagnostics,
            "summary": check.summary[:8000] if not diagnostics.get("items") else "",
            "log_paths": list(check.log_paths),
            "instruction": "Apply the correction to complete RTL; inspect declaration types and every procedural writer together.",
        },
        ensure_ascii=False,
    )


def remember_repair_check(ctx, check):
    """Hand one source-attributed compiler execution to the next repair turn."""
    ctx.store.pop("repair_check", None)
    if (
        check.status == "failed"
        and check.failure_kind == "code"
        and check.kind in ("lint", "synth")
    ):
        execution_id = uuid.uuid4().hex
        ctx.store["repair_check"] = {
            "check": check,
            "execution_id": execution_id,
        }
        ctx.record.emit(
            "knowledge",
            "check_evidence",
            execution_id=execution_id,
            check_id=check.id,
            candidate_id=check.candidate_id,
            candidate_hash=check.details.get("candidate_hash"),
        )


def remember_functional_check(ctx, check, suite):
    """Preserve actual public simulation evidence, never a diagnosis alone."""
    from agent.domain.knowledge.assets import sha256
    ctx.store.pop('repair_check', None)
    evidence = {'check': check, 'suite': suite, 'execution_id': uuid.uuid4().hex,
                'public_task_sha256': sha256(ctx.task.prompt+'\n'+ctx.task.interface)}
    from agent.domain.knowledge.feedback import bound_feedback
    try:
        bound_feedback(evidence, ctx.candidates.get(check.candidate_id), ctx.task)
    except (ValueError, KeyError, TypeError, AttributeError):
        return
    ctx.store['repair_check'] = evidence
    ctx.record.emit('knowledge', 'functional_check_evidence',
                    execution_id=evidence['execution_id'], check_id=check.id,
                    candidate_id=check.candidate_id, suite_hash=check.details.get('suite_hash'))


def check_stages(ctx, candidate, stages):
    ctx.store.pop("repair_check", None)
    for stage in stages:
        check = ctx.call(stage, candidate_id=candidate.id)
        if (
            stage == "interface"
            and not check.blocking
            and check.status in ("passed", "failed", "skipped")
            and check.failure_kind not in ("environment", "timeout")
        ):
            continue
        if check.blocking or check.status != "passed":
            remember_repair_check(ctx, check)
            return check
    return None


@node(
    "rtl_checks",
    reads=["target_id"],
    writes=["failure_kind", "feedback", "check_passed"],
)
def checks(
    ctx: Ctx, state: State, *, stages: list[str] = ["interface", "lint", "synth"]
) -> State:
    failed = check_stages(ctx, ctx.candidates.get(state["target_id"]), stages)
    if failed is None:
        ctx.candidates.select(
            state["target_id"],
            reason="synth_passed" if "synth" in stages else "checks_passed",
        )
        return state.update(failure_kind="", check_passed=True)
    return state.update(
        failure_kind=failed.failure_kind,
        feedback=repair_feedback(failed),
        check_passed=False,
    )
