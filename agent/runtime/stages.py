"""Explicit stage descriptions for the adaptive workflow.

A stage names its role, its model-callable tools, and the maximum tool-loop
steps. The workflow graph still owns transitions; this table only bounds what
one node may do and which profile the LLM gateway should use.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class StageSpec:
    role: str
    tools: tuple[str, ...] = ()
    max_steps: int = 1

    def public_dict(self):
        return {"role": self.role, "tools": list(self.tools), "max_steps": self.max_steps}


ADAPTIVE_STAGES = {
    "initialize": StageSpec("host", max_steps=0),
    "analyze": StageSpec("analyst"),
    "generate": StageSpec("author", ("submit_answer", "finish_task"), max_steps=3),
    "rescue": StageSpec("author", ("submit_answer", "finish_task"), max_steps=3),
    "build_checker": StageSpec("builder"),
    "correct_checker_format": StageSpec("host", max_steps=0),
    "review_checker": StageSpec("reviewer"),
    "revise_checker": StageSpec("builder"),
    "rereview_checker": StageSpec("reviewer"),
    "check": StageSpec("executor", max_steps=0),
    "decide": StageSpec("host", max_steps=0),
    "repair": StageSpec("attributor"),
    "recheck": StageSpec("executor", max_steps=0),
    "select": StageSpec("host", max_steps=0),
    "finish": StageSpec("host", max_steps=0),
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
