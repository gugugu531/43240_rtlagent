"""Grounded design plans and a separate review before generation."""

from collections.abc import Mapping
import copy
import json
from agent.kit import Ctx, State, node
from agent.rtl.specification import (
    normalize_requirements,
    resolve_requirement,
    source_catalog,
)
from agent.nodes.structured import request
from agent.nodes.recovery import rtl_repair_blocker, stop


def _thaw(value):
    return copy.deepcopy(value)


def _quoted(data, task):
    try:
        resolve_requirement(data, task.prompt + "\n" + task.interface)
        return True
    except (TypeError, ValueError):
        return False


def _normalized_plan(data, task):
    if (
        not isinstance(data, Mapping)
        or not isinstance(data.get("plan"), (tuple, list))
        or not data["plan"]
    ):
        raise ValueError("plan needs nonempty implementation steps")
    return {
        "requirements": normalize_requirements(
            data.get("requirements"), task.prompt + "\n" + task.interface
        ),
        "plan": _thaw(data["plan"]),
        "uncertain": _thaw(data.get("uncertain", [])),
    }


class Planner:
    def __init__(self, plan_retries=1, plan_max_tokens=4096, review_max_tokens=4096):
        if type(plan_retries) is not int or not 0 <= plan_retries <= 2:
            raise ValueError("plan_retries must be in 0..2")
        if any(
            type(cap) is not int or not 256 <= cap <= 16384
            for cap in (plan_max_tokens, review_max_tokens)
        ):
            raise ValueError("plan/review token cap must be in 256..16384")
        self.plan_retries = plan_retries
        self.plan_max_tokens = plan_max_tokens
        self.review_max_tokens = review_max_tokens

    def _plan(self, ctx, previous=None, feedback=""):
        catalog = source_catalog(ctx.task.prompt + "\n" + ctx.task.interface)
        ctx.store["plan_behavior_conflicts"] = []
        for attempt in range(self.plan_retries + 1):
            result = request(
                ctx,
                "Prepare a compact design plan. Return requirements:[{id,source_id,quote,meaning}], "
                "plan:[steps], uncertain:[items]. A public source_id may replace quote; if both are supplied "
                "the quote must come from that source. Preserve exact source text; whitespace may be normalized. "
                "Explain clock/reset, priority, widths, old/new state, hold, latency and required implementation structure. "
                "Use small numeric or edge-by-edge checks for arithmetic/scaling and latency. "
                "Do not turn unspecified behavior into a requirement. Do not write RTL. Prefer at most 8 concise steps. "
                "Use feedback only where justified by the original task.",
                "design_plan",
                {"previous": previous, "feedback": feedback, "sources": catalog},
                self.plan_max_tokens,
            )
            no_progress = result.raw_text_metadata.get("no_progress", False)
            try:
                if result.status != "ready":
                    raise ValueError(result.reason)
                plan = _normalized_plan(result.data, ctx.task)
                previous = plan
                audit = request(
                    ctx,
                    'Review this plan against the original task. Return decision:"accept"|"revise"|"reject", '
                    "reason:string. For accept, do not return a changed plan. For revise, return the full corrected "
                    "requirements, plan and uncertain fields with source references. For reject explain what remains unresolved. "
                    "An identified contradiction requires revise or reject, never accept. Check small numeric examples, "
                    "old/new state, cycle latency, and explicit structural requirements. Do not invent initialization, "
                    "priority or latency, or resolve assumptions merely by calling them reasonable. "
                    "Report unresolved behavioral contradictions in behavior_conflicts:[{source_id,quote,reason}]. "
                    "Each conflict must cite a public requirement and explain the incompatible observable behavior. "
                    "Naming choices alone are not behavioral conflicts. An empty conflict list does not prove "
                    "that unspecified behavior or every uncertain item has been resolved.",
                    "design_plan_review",
                    {"plan": plan, "sources": catalog},
                    self.review_max_tokens,
                )
                no_progress = audit.raw_text_metadata.get("no_progress", False)
                if audit.status != "ready":
                    raise ValueError(audit.reason)
                data = audit.data
                if data.get("behavior_conflicts"):
                    conflicts = [
                        {
                            **resolve_requirement(
                                item, ctx.task.prompt + "\n" + ctx.task.interface
                            ),
                            "reason": item["reason"],
                        }
                        for item in data["behavior_conflicts"]
                    ]
                    ctx.store["plan_behavior_conflicts"] = conflicts
                    ctx.record.emit(
                        "plan", "behavior_conflict", call_id=audit.call_id,
                        conflicts=conflicts,
                    )
                    raise ValueError(
                        "Unresolved public behavioral conflicts; revise only with public evidence: "
                        + json.dumps(conflicts, ensure_ascii=False)
                    )
                decision = data.get("decision")
                if (
                    decision is not None
                    and "accepted" in data
                    and (
                        type(data["accepted"]) is not bool
                        or data["accepted"] != (decision == "accept")
                    )
                ):
                    raise ValueError(
                        "review decision conflicts with accepted; return one consistent verdict"
                    )
                if decision is None and type(data.get("accepted")) is bool:
                    decision = "accept" if data["accepted"] else "revise"
                if decision == "accept":
                    if "plan" in data and _thaw(data["plan"]) != plan["plan"]:
                        raise ValueError(
                            "review accepts but changes the implementation plan; use decision=revise"
                        )
                    if (
                        "requirements" in data
                        and normalize_requirements(
                            data["requirements"],
                            ctx.task.prompt + "\n" + ctx.task.interface,
                        )
                        != plan["requirements"]
                    ):
                        raise ValueError(
                            "review accepts but changes requirements; use decision=revise"
                        )
                    if (
                        "uncertain" in data
                        and _thaw(data["uncertain"]) != plan["uncertain"]
                    ):
                        raise ValueError(
                            "review accepts but changes uncertain items; use decision=revise"
                        )
                    chosen = plan
                elif decision == "revise":
                    chosen = _normalized_plan(data, ctx.task)
                else:
                    raise ValueError(
                        "review rejected or unresolved: "
                        + str(data.get("reason", "missing decision"))[:1000]
                    )
                ctx.record.emit(
                    "plan",
                    "design_plan_attempt",
                    attempt=attempt + 1,
                    status="ready",
                    decision=decision,
                    call_id=result.call_id,
                    review_call_id=audit.call_id,
                )
                ctx.store["plan_behavior_conflicts"] = []
                return chosen
            except (ValueError, TypeError) as error:
                feedback = str(error)
                ctx.record.emit(
                    "plan",
                    "design_plan_attempt",
                    attempt=attempt + 1,
                    status="invalid",
                    call_id=result.call_id,
                    reason=feedback,
                    retry=attempt < self.plan_retries and not no_progress,
                )
                if no_progress:
                    break
        return None


@node(
    "design_plan", reads=[],
    writes=["plan_ready", "action", "stop_reason", "status"],
)
def plan(
    ctx: Ctx,
    state: State,
    *,
    plan_retries: int = 1,
    plan_max_tokens: int = 4096,
    review_max_tokens: int = 4096,
) -> State:
    options = dict(
        plan_retries=plan_retries,
        plan_max_tokens=plan_max_tokens,
        review_max_tokens=review_max_tokens,
    )
    ctx.store["plan_options"] = options
    result = Planner(**options)._plan(ctx)
    ctx.store["plan"] = result
    ctx.record.emit("plan", "status", status="ready" if result else "invalid")
    if result is None and ctx.store.get("plan_behavior_conflicts"):
        return state.update(
            plan_ready=False, action="finish", status="stopped",
            stop_reason="plan_behavior_conflict",
        )
    return state.update(plan_ready=result is not None)


@node(
    "revise_plan",
    reads=["feedback", "round", "max_rounds", "target_id"],
    writes=["action", "stop_reason", "status"],
)
def revise(ctx: Ctx, state: State) -> State:
    # Keep the check at this public node boundary as well as the diagnosis route.
    if reason := rtl_repair_blocker(ctx, state, origin="revise_plan"):
        return stop(state, reason)
    revised = Planner(**ctx.store["plan_options"])._plan(
        ctx, ctx.store["plan"], state.get("feedback", "")
    )
    if revised is None:
        if ctx.store.get("plan_behavior_conflicts"):
            return stop(state, "plan_behavior_conflict")
        return state.update(action="finish", stop_reason="plan_revision_invalid")
    ctx.store["plan"] = revised
    return state.update(action="generate")
