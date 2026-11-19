"""Single source for stage roles and role → model-profile mapping.

Both the runtime stage table and the LLM gateway import this module, so a
stage's declared role and the profile used for its requests cannot drift.
No runtime or domain imports here.
"""

# Profile names are compatibility labels, not model-size requirements. Disabled
# profiles use the primary model; each stage builds its own request messages.
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
    "solve_recovery": "author",
    "checker": "builder",
    "checker_recovery": "builder",
    "checker_format_repair": "builder",
    "checker_review": "builder",
    "author_decision": "author",
    "adjudicate": "attributor",
    "repair_structure": "author",
    "repair_behavior": "author",
    "checker_rebuild": "builder",
}


def role_for_stage(stage):
    """Resolve a node, request, or numbered attempt to its configured role."""
    if not isinstance(stage, str) or not stage:
        return ""
    base = stage.split("_tool_", 1)[0]
    base = base.removeprefix("guided_")
    label, separator, attempt = base.rpartition("_")
    if separator and attempt.isascii() and attempt.isdecimal():
        base = label
    return _STAGE_ROLES.get(base, "")


def profile_for_stage(stage):
    return ROLE_PROFILES.get(role_for_stage(stage), "")
