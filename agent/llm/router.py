"""Deterministic role → model-profile mapping.

Profiles are declared in configuration and only switch the model name and
optional endpoint/timeout. Thinking settings and generation metadata still
come from the manifest, so a profile cannot silently change the evaluation
protocol.
"""

ROLE_PROFILES = {
    "analyst": "small",
    "author": "large",
    "builder": "large",
    "reviewer": "large",
    "attributor": "large",
}

# Stage labels that are not node names, plus the internal tool-loop suffixes.
_STAGE_ROLES = {
    "profile": "analyst",
    "analyze": "analyst",
    "draft": "author",
    "generate": "author",
    "rescue": "author",
    "construction": "builder",
    "build_checker": "builder",
    "revision": "builder",
    "revise_checker": "builder",
    "review": "reviewer",
    "review_retry": "reviewer",
    "review_checker": "reviewer",
    "rereview": "reviewer",
    "rereview_checker": "reviewer",
    "repair": "attributor",
}


def role_for_stage(stage):
    """Resolve `draft_tool_2` back to the authoring role."""
    if not isinstance(stage, str) or not stage:
        return ""
    base = stage.split("_tool_", 1)[0]
    return _STAGE_ROLES.get(base, "")


def profile_for_stage(stage):
    return ROLE_PROFILES.get(role_for_stage(stage), "")
