"""First draft, one bounded checker recovery, and one evidenced RTL repair."""

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from agent.kit import workflow, when, default
from agent.knowledge.policy import RetrievalOptions, modes
from agent.knowledge.release import validate_options


class StageLimit(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    timeout_s: float = Field(gt=0)
    max_tokens: int = Field(gt=0)


class AdaptiveParameters(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    profile: StageLimit = StageLimit(timeout_s=180, max_tokens=4096)
    draft: StageLimit = StageLimit(timeout_s=1200, max_tokens=32768)
    construction: StageLimit = StageLimit(timeout_s=1200, max_tokens=32768)
    review: StageLimit = StageLimit(timeout_s=1200, max_tokens=32768)
    revision: StageLimit = StageLimit(timeout_s=1200, max_tokens=32768)
    rereview: StageLimit = StageLimit(timeout_s=1200, max_tokens=32768)
    repair: StageLimit = StageLimit(timeout_s=1200, max_tokens=32768)
    first_tools_s: float = Field(default=300, gt=0)
    recheck_tools_s: float = Field(default=600, gt=0)
    max_calls: int = Field(default=7, gt=0, le=7)
    max_output_tokens: int = Field(default=200704, gt=0)
    knowledge_max_tokens: int = Field(default=8192, ge=0, le=8192)
    sequential_skill: Literal["rtl-sequential-state-update", "rtl-sequential-state-update-v3"] = "rtl-sequential-state-update"
    rag: bool = False
    skill_mode: Literal['off', 'shadow', 'on'] = 'on'
    rag_mode: Literal['off', 'shadow', 'on'] | None = None
    retrieval: RetrievalOptions = Field(default_factory=RetrievalOptions)
    temperature: float = Field(default=0.0, ge=0, le=2)
    top_p: float = Field(default=1.0, gt=0, le=1)


@workflow(
    "adaptive_verify", param_model=AdaptiveParameters,
    tools={"interface": "interface_check", "lint": "vivado_lint", "synth": "vivado_synth"},
    nodes={
        "initialize": "adaptive_initialize", "analyze": "adaptive_analyze",
        "generate": "adaptive_generate", "rescue": "adaptive_rescue",
        "build_checker": "adaptive_build_checker", "review_checker": "adaptive_review_checker",
        "correct_checker_format": "adaptive_correct_checker_format",
        "revise_checker": "adaptive_revise_checker", "rereview_checker": "adaptive_rereview_checker",
        "check": "adaptive_check", "decide": "adaptive_decide",
        "repair": "adaptive_repair", "recheck": "adaptive_recheck",
        "select": "adaptive_select", "finish": "adaptive_finish",
    },
    state={"settings": {}, "route": "structural", "target_id": None,
           "parent_id": None, "has_candidate": False, "action": "",
           "checker_status": "not_built", "stop_reason": "", "status": "stopped"},
)
def build(g, p):
    _, rag_mode = modes(p.skill_mode, p.rag_mode, rag=p.rag)
    if rag_mode != 'off':
        validate_options(p.retrieval)
    return g.with_state(settings=p.model_dump(mode="json")).with_transitions(
        ("initialize", "analyze"), ("analyze", "generate"),
        ("generate", "build_checker", when(has_candidate=True)),
        ("generate", "rescue", default),
        ("rescue", "check", when(has_candidate=True)), ("rescue", "finish", default),
        ("build_checker", "review_checker", when(checker_status="ready")),
        ("build_checker", "correct_checker_format", when(checker_status="format_invalid")),
        ("build_checker", "check", default),
        ("correct_checker_format", "review_checker", when(checker_status="ready")),
        ("correct_checker_format", "check", default),
        ("review_checker", "revise_checker", when(checker_status="rejected")),
        ("review_checker", "check", default),
        ("revise_checker", "rereview_checker", when(checker_status="ready")),
        ("revise_checker", "check", default), ("rereview_checker", "check"),
        ("check", "decide"), ("decide", "repair", when(action="repair")),
        ("decide", "finish", default),
        ("repair", "recheck", when(action="recheck")), ("repair", "finish", default),
        ("recheck", "select"), ("select", "finish"),
    ).with_entrypoint("initialize")
