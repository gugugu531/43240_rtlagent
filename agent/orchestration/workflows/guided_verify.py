"""Small planner, independent key-case checker, bounded repair."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from agent.kit import workflow, when, default


class StageLimit(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    timeout_s: float = Field(gt=0)
    max_tokens: int = Field(gt=0)


class GuidedParameters(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    planner: StageLimit = StageLimit(timeout_s=60, max_tokens=512)
    solve: StageLimit = StageLimit(timeout_s=240, max_tokens=4096)
    checker: StageLimit = StageLimit(timeout_s=180, max_tokens=2048)
    adjudicate: StageLimit = StageLimit(timeout_s=120, max_tokens=1024)
    structure_repair_limit: int = Field(default=1, ge=0, le=5)
    behavior_repair_limit: int = Field(default=1, ge=0, le=5)
    checker_rebuild_limit: int = Field(default=1, ge=0, le=5)
    adjudicate_limit: int = Field(default=2, ge=0, le=5)
    max_cases: int = Field(default=4, ge=1, le=8)
    max_steps_per_case: int = Field(default=8, ge=1, le=16)
    init_cycles: int = Field(default=2, ge=1, le=8)
    knowledge_candidates: int = Field(default=5, ge=1, le=16)
    knowledge_select: int = Field(default=3, ge=0, le=5)
    max_calls: int = Field(default=8, ge=1, le=12)
    max_output_tokens: int = Field(default=65536, gt=0)
    first_tools_s: float = Field(default=120, gt=0)
    recheck_tools_s: float = Field(default=120, gt=0)
    submission_policy: Literal["last_written", "selected"] = "last_written"
    temperature: float = Field(default=0.0, ge=0, le=2)
    top_p: float = Field(default=1.0, gt=0, le=1)


@workflow(
    "guided_verify",
    param_model=GuidedParameters,
    tools={
        "interface": "interface_check",
        "lint": "vivado_lint",
        "synth": "vivado_synth",
    },
    nodes={
        "initialize": "guided_initialize",
        "plan": "guided_plan",
        "solve": "guided_solve",
        "structure": "guided_structure",
        "repair_structure": "guided_repair_structure",
        "build_checker": "guided_build_checker",
        "run_checker": "guided_run_checker",
        "adjudicate": "guided_adjudicate",
        "repair_behavior": "guided_repair_behavior",
        "finish": "guided_finish",
    },
    state={
        "settings": {},
        "method": "structural",
        "target_id": None,
        "parent_id": None,
        "action": "",
        "checker_status": "not_built",
        "stop_reason": "",
        "status": "stopped",
    },
)
def build(g, p):
    return g.with_state(settings=p.model_dump(mode="json")).with_transitions(
        ("initialize", "plan"),
        ("plan", "solve"),
        ("solve", "structure"),
        ("structure", "repair_structure", when(action="repair_structure")),
        ("structure", "build_checker", when(action="build_checker")),
        ("structure", "run_checker", when(action="run_checker")),
        ("structure", "finish", default),
        ("repair_structure", "structure"),
        ("build_checker", "run_checker", when(checker_status="valid")),
        ("build_checker", "finish", default),
        ("run_checker", "adjudicate", when(action="adjudicate")),
        ("run_checker", "finish", default),
        ("adjudicate", "repair_behavior", when(action="repair_behavior")),
        ("adjudicate", "build_checker", when(action="rebuild_checker")),
        ("adjudicate", "finish", default),
        ("repair_behavior", "structure"),
    ).with_entrypoint("initialize")
