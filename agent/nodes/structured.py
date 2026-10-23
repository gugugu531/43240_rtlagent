"""Small typed envelopes for independent design and checking requests."""

from dataclasses import dataclass, field
import hashlib
import json
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from agent.llm.structured import StructuredError
from agent.llm.client import ModelError
from agent.rtl.suite.model import SuiteModel


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


class PlanReview(Envelope):
    decision: Literal["accept", "revise", "reject"]
    reason: str = Field(min_length=1)
    requirements: list[Requirement] | None = None
    plan: list[str] | None = None
    uncertain: list[str] | None = None


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
}


def request(ctx, instruction, purpose, context, max_tokens=8192, *, reserve_s=120):
    if ctx.budget.remaining() <= reserve_s:
        ctx.record.emit(
            "structured", "skipped", purpose=purpose, reason="reserved_rtl_budget"
        )
        return JsonResult(
            "invalid", reason="auxiliary time reserved for RTL and checks"
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
        from agent.rtl.specification import normalize_requirements, resolve_requirement
        from agent.rtl.suite.model import validate_suite

        data = result.model_dump(exclude_unset=True)
        task_text = ctx.task.prompt + "\n" + ctx.task.interface
        if purpose == "design_plan":
            normalize_requirements(data["requirements"], task_text)
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
        available = ctx.budget.remaining() - reserve_s
        if available <= 0:
            ctx.record.emit(
                "structured", "skipped", purpose=purpose, reason="reserved_rtl_budget"
            )
            return JsonResult(
                "invalid", reason="auxiliary time reserved for RTL and checks"
            )
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
                reason="auxiliary timeout at reserved RTL boundary",
                failure_kind="timeout",
            )
            return JsonResult(
                "invalid",
                call_id=error.call_id,
                reason="auxiliary timeout at reserved RTL boundary",
            )
        else:
            call_id = next(reversed(ctx.llm.replies), None)
            return JsonResult("ready", result.model_dump(exclude_unset=True), call_id)
