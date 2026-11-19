"""Isolated strategy, RTL author and checker sharing one completion budget."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent.kit import workflow, when, default


class StageLimit(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    timeout_s: float = Field(gt=0)
    max_tokens: int | None = Field(gt=0)


class GuidedParameters(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    planner: StageLimit = StageLimit(timeout_s=90, max_tokens=4096)
    solve: StageLimit = StageLimit(timeout_s=300, max_tokens=16384)
    checker: StageLimit = StageLimit(timeout_s=180, max_tokens=8192)
    solve_minimum_s: float = Field(default=120, ge=0)
    max_cases: int = Field(default=4, ge=1, le=8)
    max_steps_per_case: int = Field(default=8, ge=1, le=16)
    init_cycles: int = Field(default=2, ge=1, le=8)
    knowledge_candidates: int = Field(default=5, ge=1, le=16)
    knowledge_select: int = Field(default=3, ge=0, le=5)
    max_calls: int | None = Field(default=8, ge=1)
    max_output_tokens: int | None = Field(default=65536, gt=0)
    minimum_request_s: float = Field(default=20, ge=0)
    first_tools_s: float = Field(default=120, ge=0)
    recheck_tools_s: float = Field(default=120, ge=0)
    retrieval_mode: Literal["off", "legacy", "rag", "all"] = "off"
    retrieval_strategy: Literal["bm25", "dense"] = "bm25"
    embedding_url: str = ""
    embedding_timeout_s: float = Field(default=2.0, gt=0, le=10)
    temperature: float = Field(default=0.0, ge=0, le=2)
    top_p: float = Field(default=1.0, gt=0, le=1)

    @model_validator(mode="after")
    def dense_requires_endpoint(self):
        if self.retrieval_strategy == "dense" and self.retrieval_mode != "off" and not self.embedding_url:
            raise ValueError("dense_retrieval_requires_embedding_url")
        return self


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
        "author_decision": "guided_author_decision",
        "checker_review": "guided_checker_review",
        "finish": "guided_finish",
    },
    state={
        "settings": {},
        "method": "structural",
        "target_id": None,
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
        ("structure", "author_decision", when(action="author_decision")),
        ("structure", "finish", default),
        ("repair_structure", "repair_structure", when(action="retry")),
        ("repair_structure", "finish", when(action="finish")),
        ("repair_structure", "structure", default),
        ("build_checker", "run_checker", when(checker_status="valid")),
        ("build_checker", "author_decision", default),
        ("run_checker", "author_decision"),
        ("author_decision", "structure", when(action="revise")),
        ("author_decision", "checker_review", when(action="review")),
        ("author_decision", "author_decision", when(action="retry")),
        ("author_decision", "finish", default),
        ("checker_review", "run_checker", when(action="run_checker")),
        ("checker_review", "author_decision", default),
    ).with_entrypoint("initialize")
