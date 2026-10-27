"""Explicit stage descriptions for the adaptive workflow.

A stage names its role, its model-callable tools, and the maximum tool-loop
steps. The workflow graph still owns transitions; this table only bounds what
one node may do and which profile the LLM gateway should use.
"""

from dataclasses import dataclass

from agent.roles import role_for_stage


@dataclass(frozen=True)
class StageSpec:
    role: str
    tools: tuple[str, ...] = ()
    max_steps: int = 1

    def public_dict(self):
        return {"role": self.role, "tools": list(self.tools), "max_steps": self.max_steps}


# Roles come from `agent.roles`; this table only declares tools and step caps.
ADAPTIVE_STAGES = {
    "initialize": StageSpec(role_for_stage("initialize"), max_steps=0),
    "analyze": StageSpec(role_for_stage("analyze")),
    "generate": StageSpec(
        role_for_stage("generate"), ("submit_answer", "finish_task"), max_steps=3
    ),
    "rescue": StageSpec(
        role_for_stage("rescue"), ("submit_answer", "finish_task"), max_steps=3
    ),
    "build_checker": StageSpec(role_for_stage("build_checker")),
    "correct_checker_format": StageSpec(role_for_stage("correct_checker_format"), max_steps=0),
    "review_checker": StageSpec(role_for_stage("review_checker")),
    "revise_checker": StageSpec(role_for_stage("revise_checker")),
    "rereview_checker": StageSpec(role_for_stage("rereview_checker")),
    "check": StageSpec(role_for_stage("check"), max_steps=0),
    "decide": StageSpec(role_for_stage("decide"), max_steps=0),
    "repair": StageSpec(role_for_stage("repair")),
    "recheck": StageSpec(role_for_stage("recheck"), max_steps=0),
    "select": StageSpec(role_for_stage("select"), max_steps=0),
    "finish": StageSpec(role_for_stage("finish"), max_steps=0),
}

# Labels used by request helpers that differ from node aliases.
_STAGE_ALIASES = {
    "profile": "analyze",
    "draft": "generate",
    "construction": "build_checker",
    "review": "review_checker",
    "review_retry": "review_checker",
    "revision": "revise_checker",
    "rereview": "rereview_checker",
}


def stage_spec(name):
    """Return the spec for a node alias or a request-stage label."""
    if name in ADAPTIVE_STAGES:
        return ADAPTIVE_STAGES[name]
    base = name.split("_tool_", 1)[0] if isinstance(name, str) else ""
    return ADAPTIVE_STAGES[_STAGE_ALIASES.get(base, base)]
