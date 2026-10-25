"""Bounded public-task analysis and deterministic knowledge/route selection."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent.llm.structured import strict_json
from agent.rtl.specification import resolve_quote

ShortText = Annotated[str, Field(min_length=1, max_length=1200)]
Risk = Literal["width", "signed", "state_update", "priority", "completeness", "handshake", "latency", "reset"]


class TaskAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    kind: Literal["combinational", "arithmetic", "sequential", "fsm", "protocol", "unknown"]
    route: Literal["model", "properties", "structural"]
    model_cost: Literal["small", "large", "unknown"]
    clocks: Annotated[list[str], Field(max_length=8)]
    risks: Annotated[list[Risk], Field(max_length=8)]
    requirements: Annotated[list[ShortText], Field(max_length=12)]
    ambiguities: Annotated[list[ShortText], Field(max_length=12)]
    rationale: ShortText

    @model_validator(mode="after")
    def unique(self):
        for name in ("clocks", "risks", "requirements"):
            values = getattr(self, name)
            if len(set(values)) != len(values):
                raise ValueError(name + " must contain distinct entries")
        return self


def analysis_request(task):
    return [
        {"role": "system", "content": "Analyze only the public RTL task. Return one strict JSON object, without Markdown. This is routing advice, not a behavioral oracle. Do not solve the task or invent unspecified semantics."},
        {"role": "user", "content": (
            "Public task:\n" + task.prompt + "\n\nPublic interface:\n" + task.interface
            + "\n\nChoose model only for a compact combinational or small state model; properties for clearly stated local relationships; structural when neither is supported. "
            "Properties support combinational/single-clock fixed stimuli and at most 16 edges of history/wait; no dynamic transactions or cross-clock history. "
            "A small behavioral model has <=8 registers, <=128 expression nodes, <=8 sequences of <=32 events. "
            "List literal public quotations in requirements; do not paraphrase them. List ambiguities separately. "
            "clocks must name actual public input ports, not resets. Select no skill IDs: the host maps kind and risks to packaged methods.\nSchema:\n"
            + json.dumps(TaskAnalysis.model_json_schema(), ensure_ascii=False)
        )},
    ]


def parse_analysis(text, task, *, finish_reason=None):
    if finish_reason == "length":
        raise ValueError("analysis output truncated")
    if not text.strip() or len(text) > 65536:
        raise ValueError("analysis final content missing or too large")
    result = TaskAnalysis.model_validate(strict_json(text), strict=True)
    source = task.prompt + "\n" + task.interface
    for quote in result.requirements:
        resolve_quote(quote, source)
    expected = task.expected_interface
    if expected.complete and expected.parsed:
        inputs = {p.name for p in expected.ports if p.direction == "input" and p.width == 1}
        if set(result.clocks) - inputs:
            raise ValueError("analysis clock must be a known one-bit public input")
    return result


@dataclass(frozen=True)
class RouteDecision:
    route: str
    reason: str
    skill_ids: tuple[str, ...]
    uncovered: tuple[str, ...]

    def public_dict(self):
        return {"route": self.route, "reason": self.reason,
                "skill_ids": list(self.skill_ids), "uncovered": list(self.uncovered)}


def choose_route(task, analysis=None, *, sequential_skill="rtl-sequential-state-update"):
    if sequential_skill not in ("rtl-sequential-state-update", "rtl-sequential-state-update-v3"):
        raise ValueError("unknown sequential Skill version")
    if analysis is None:
        return RouteDecision("structural", "analysis_unavailable", (), ("behavior_not_analyzed",))
    skills = []
    if analysis.kind == "fsm":
        skills.append("rtl-fsm-state-output")
    elif analysis.kind in ("sequential", "protocol"):
        skills.append(sequential_skill)
    elif analysis.kind == "combinational":
        skills.append("rtl-combinational-completeness")
    if analysis.kind == "arithmetic" or set(analysis.risks) & {"width", "signed"}:
        skills.append("rtl-width-signed-arithmetic")
    reason = "analysis_route_with_host_limits"
    route = analysis.route
    uncovered = list(analysis.ambiguities)
    if any(p.direction == "inout" for p in task.expected_interface.ports):
        route, reason = "structural", "inout_not_supported"
    elif len(analysis.clocks) > 1:
        route, reason = "structural", "multiple_clock_domains_not_supported"
    elif not analysis.requirements or analysis.kind == "unknown":
        route, reason = "structural", "no_grounded_check_scope"
    elif route == "model" and analysis.model_cost != "small":
        route, reason = "properties", "full_model_outside_cost_bound"
    if route == "structural":
        uncovered.append("behavior_not_checked")
    return RouteDecision(route, reason, tuple(skills[:2]), tuple(uncovered))
