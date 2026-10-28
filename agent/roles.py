"""Single source for stage roles and role → model-profile mapping.

Both the runtime stage table and the LLM gateway import this module, so a
stage's declared role and the profile used for its requests cannot drift.
No runtime or domain imports here.
"""

ROLE_PROFILES = {
    "analyst": "small",
    "author": "large",
    "builder": "large",
    "reviewer": "large",
    "attributor": "large",
}

# Node aliases, request-stage labels, and tool-loop suffixes all resolve here.
_STAGE_ROLES = {
    # node names
    "initialize": "host",
    "analyze": "analyst",
    "generate": "author",
    "rescue": "author",
    "build_checker": "builder",
    "correct_checker_format": "host",
    "review_checker": "reviewer",
    "revise_checker": "builder",
    "rereview_checker": "reviewer",
    "check": "executor",
    "decide": "host",
    "repair": "attributor",
    "recheck": "executor",
    "select": "host",
    "finish": "host",
    # request labels used by _request
    "profile": "analyst",
    "draft": "author",
    "construction": "builder",
    "review": "reviewer",
    "review_retry": "reviewer",
    "revision": "builder",
    "rereview": "reviewer",
    # guided_verify request labels
    "plan": "analyst",
    "solve": "author",
    "checker": "builder",
    "adjudicate": "attributor",
    "repair_structure": "author",
    "repair_behavior": "author",
    "guided_plan": "analyst",
    "guided_solve": "author",
    "guided_build_checker": "builder",
    "guided_adjudicate": "attributor",
    "guided_repair_structure": "author",
    "guided_repair_behavior": "author",
    "checker_rebuild": "builder",
}


def role_for_stage(stage):
    """Resolve `draft_tool_2` back to the authoring role."""
    if not isinstance(stage, str) or not stage:
        return ""
    base = stage.split("_tool_", 1)[0]
    role = _STAGE_ROLES.get(base, "")
    if not role and "_" in base:
        role = _STAGE_ROLES.get(base.rsplit("_", 1)[0], "")
    return role


def profile_for_stage(stage):
    return ROLE_PROFILES.get(role_for_stage(stage), "")
