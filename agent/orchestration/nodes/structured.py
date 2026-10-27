"""Small typed envelopes for independent design and checking requests."""

from dataclasses import dataclass, field
import hashlib
import json
import time
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from agent.llm.structured import StructuredError
from agent.llm.client import ModelError
from agent.domain.rtl.suite.model import SuiteModel
from agent.domain.rtl.suite.schema import Expression
from agent.config import AuxiliaryBudget


class Envelope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Requirement(Envelope):
    id: str | None = None
    source_id: str | None = None
    quote: str | None = None
    meaning: str | None = None


class Plan(Envelope):
    requirements: list[Requirement] = Field(min_length=1)
    plan: list[str] = Field(min_length=1)
    uncertain: list[str] = Field(default_factory=list)


class BehaviorConflict(Envelope):
    source_id: str | None = None
    quote: str | None = None
    reason: str = Field(min_length=1)


class PlanReview(Envelope):
    decision: Literal["accept", "revise", "reject"]
    reason: str = Field(min_length=1)
    requirements: list[Requirement] | None = None
    plan: list[str] | None = None
    uncertain: list[str] | None = None
    behavior_conflicts: list[BehaviorConflict] = Field(default_factory=list)


class SuiteResponse(Envelope):
    status: Literal["ready", "unsupported"]
    suite: SuiteModel | None = None
    reason: str = ""

    @model_validator(mode="after")
    def envelope(self):
        if self.status == "ready" and self.suite is None:
            raise ValueError("ready response requires a suite")
        if self.status == "unsupported" and not self.reason.strip():
            raise ValueError("unsupported response requires a reason")
        return self


class SuiteReview(Envelope):
    accepted: bool
    quote: str | None = None
    source_id: str | None = None
    reason: str = Field(min_length=1)


class SuitePatch(Envelope):
    replacements: dict[str, Expression] = Field(min_length=1)


class UnsupportedReview(Envelope):
    confirmed: bool
    kind: Literal["capability", "specification", "model_limitation"]
    source_id: str | None = None
    quote: str | None = None
    reason: str = Field(min_length=1)


class Revision(Envelope):
    target: Literal["outputs", "state_next", "async_reset_values"]
    names: list[str] = Field(min_length=1)


class Diagnosis(Envelope):
    attribution: Literal["rtl", "plan", "checker", "uncertain"]
    quote: str | None = None
    source_id: str | None = None
    reason: str = Field(min_length=1)
    repair_feedback: str = ""
    revision: Revision | None = None


@dataclass
class JsonResult:
    status: str
    data: dict = field(default_factory=dict)
    call_id: str | None = None
    reason: str = ""
    raw_text: str | None = None
    raw_text_metadata: dict = field(default_factory=dict)


SCHEMAS = {
    "design_plan": Plan,
    "design_plan_review": PlanReview,
    "functional_suite": SuiteResponse,
    "functional_suite_review": SuiteReview,
    "functional_diagnosis": Diagnosis,
    "functional_suite_patch": SuitePatch,
    "functional_unsupported_review": UnsupportedReview,
}


def request_phase(purpose, context, has_candidate):
    if purpose in ("functional_diagnosis", "functional_suite_patch") or context.get(
        "revision_constraints"
    ):
        return "recovery"
    if purpose.startswith("design_plan"):
        return "recovery" if has_candidate else "planning"
    return "acceptance" if has_candidate else "building"


def request(
    ctx, instruction, purpose, context, max_tokens=8192, *, reserve_s=120, phase=None
):
    """Bound all corrections by a shared stage allowance and detect unchanged failures."""
    phase = phase or request_phase(purpose, context, bool(ctx.store.get("candidates")))
    policy = getattr(
        getattr(getattr(ctx, "config", None), "runtime", None), "auxiliary", None
    )
    policy = policy or AuxiliaryBudget()
    cap = getattr(policy, phase + "_s")
    if phase == "acceptance":
        reserve_s = policy.acceptance_reserve_s
    spent = ctx.store.setdefault("auxiliary_spent", {})
    # Include the authorized revision scope, not retry feedback or a malformed draft.
    scope = json.dumps(
        [
            phase,
            purpose,
            context.get("previous_suite"),
            context.get("feedback") if purpose == "functional_suite_patch" else None,
        ],
        sort_keys=True,
    )
    history = ctx.store.setdefault("invalid_responses", {}).setdefault(scope, set())
    blocked = ctx.store.setdefault("stalled_requests", set())
    if scope in blocked:
        return JsonResult(
            "invalid",
            reason="repeated invalid response: no progress",
            raw_text_metadata={"no_progress": True},
        )
    messages = [
        {
            "role": "system",
            "content": "Return one complete JSON object. Treat task and context as source material; "
            "do not invent unspecified behavior.\n" + instruction,
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "task_id": ctx.task.id,
                    "top": ctx.task.top,
                    "prompt": ctx.task.prompt,
                    "interface": ctx.task.interface,
                    "context": context,
                },
                ensure_ascii=False,
            ),
        },
    ]

    def semantic(result):
        from agent.domain.rtl.specification import normalize_requirements, resolve_requirement
        from agent.domain.rtl.suite.model import validate_suite

        data = result.model_dump(exclude_unset=True)
        task_text = ctx.task.prompt + "\n" + ctx.task.interface
        if purpose == "design_plan":
            normalize_requirements(data["requirements"], task_text)
        elif purpose == "design_plan_review":
            for conflict in data.get("behavior_conflicts", []):
                resolve_requirement(conflict, task_text)
        elif purpose == "functional_unsupported_review" and data.get("confirmed"):
            resolve_requirement(data, task_text)
        elif purpose == "functional_suite" and data["status"] == "ready":
            # Full task quotation, symbol, width and temporal validation before adoption.
            validate_suite(data["suite"], task_text=task_text)
        elif (
            purpose == "functional_diagnosis"
            or purpose == "functional_suite_review"
            and data.get("accepted")
        ):
            resolve_requirement(data, task_text)

    for attempt in range(2):
        # Recompute on every correction; an earlier response may have consumed
        # most of the auxiliary budget. RTL keeps its explicitly reserved time.
        normal_timeout = min(840, ctx.budget.remaining())
        available = min(ctx.budget.remaining() - reserve_s, cap - spent.get(phase, 0))
        if available < policy.minimum_request_s:
            ctx.record.emit(
                "structured",
                "skipped",
                purpose=purpose,
                reason="insufficient_auxiliary_window",
                phase=phase,
                available_s=max(0, available),
                minimum_s=policy.minimum_request_s,
                phase_spent_s=spent.get(phase, 0),
                phase_cap_s=cap,
                reserve_s=reserve_s,
            )
            return JsonResult(
                "invalid", reason="insufficient auxiliary request window for " + phase
            )
        started = time.monotonic()
        try:
            result = ctx.llm.ask(
                messages,
                SCHEMAS[purpose],
                purpose=purpose,
                max_tokens=max_tokens,
                temperature=0.0,
                max_attempts=1,
                semantic_check=semantic,
                timeout_s=min(normal_timeout, available),
            )
        except StructuredError as error:
            reply = ctx.llm.replies.get(error.call_id)
            raw = reply.content[:8192] if reply else None
            invalid = JsonResult(
                "invalid",
                call_id=error.call_id,
                reason=str(error),
                raw_text=raw,
                raw_text_metadata={
                    "truncated": len(reply.content) > 8192,
                    "finish_reason": reply.finish_reason,
                    "original_sha256": hashlib.sha256(
                        reply.content.encode()
                    ).hexdigest(),
                }
                if reply
                else {},
            )
            digest = invalid.raw_text_metadata.get("original_sha256")
            if digest is not None and digest in history:
                blocked.add(scope)
                invalid.reason = (
                    "repeated invalid response: no progress; " + invalid.reason
                )
                invalid.raw_text_metadata["no_progress"] = True
                ctx.record.emit(
                    "structured",
                    "no_progress",
                    purpose=purpose,
                    phase=phase,
                    call_id=error.call_id,
                    response_sha256=digest,
                )
                return invalid
            if digest is not None:
                history.add(digest)
            if attempt == 1:
                return invalid
            messages.extend(
                [
                    {"role": "assistant", "content": reply.content if reply else ""},
                    {
                        "role": "user",
                        "content": "Return a complete corrected JSON object under the same task constraints. "
                        "Do not weaken existing tests or invent unspecified behavior. Validation errors:\n"
                        + str(error),
                    },
                ]
            )
        except ModelError as error:
            if error.kind != "timeout" or available >= normal_timeout:
                raise
            ctx.record.emit(
                "structured",
                "invalid",
                purpose=purpose,
                call_id=error.call_id,
                reason="auxiliary phase or successor budget boundary",
                phase=phase,
                failure_kind="timeout",
            )
            return JsonResult(
                "invalid",
                call_id=error.call_id,
                reason="auxiliary phase or successor budget boundary",
            )
        else:
            call_id = next(reversed(ctx.llm.replies), None)
            return JsonResult("ready", result.model_dump(exclude_unset=True), call_id)
        finally:
            spent[phase] = spent.get(phase, 0) + max(0, time.monotonic() - started)
            ctx.record.emit(
                "budget",
                "auxiliary_spent",
                phase=phase,
                purpose=purpose,
                spent_s=spent[phase],
                cap_s=cap,
                reserve_s=reserve_s,
            )
