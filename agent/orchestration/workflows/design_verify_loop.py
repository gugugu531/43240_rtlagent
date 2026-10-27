"""Independent construction, checking, attribution and bounded repair as Burr transitions."""

from agent.kit import workflow, when, default


@workflow(
    "design_verify_loop",
    params={"max_rounds": 3, "checker_revisions": 1, "unchanged_retries": 1},
    tools={
        "interface": {"use": "interface_check"},
        "lint": {"use": "vivado_lint"},
        "synth": {"use": "vivado_synth"},
        "functional": {"use": "functional_sim"},
    },
    nodes={
        "plan": {"use": "design_plan"},
        "build_suite": {"use": "build_suite"},
        "generate": {"use": "rtl_generate"},
        "extract": {"use": "rtl_extract"},
        "dedupe": {"use": "design_dedupe"},
        "structure": {"use": "design_structure"},
        "functional": {"use": "design_functional"},
        "diagnose": {"use": "design_diagnose"},
        "revise_suite": {"use": "revise_suite"},
        "revise_plan": {"use": "revise_plan"},
        "acceptance": {"use": "design_acceptance"},
        "final_synth": {"use": "design_synth"},
        "synth_only": {"use": "design_synth", "params": {"structure_only": True}},
        "next_round": {"use": "design_next_round"},
        "finish": {"use": "finish"},
    },
    state={
        "feedback": "",
        "target_id": None,
        "reply_id": None,
        "round": 0,
        "has_candidate": False,
        "failure_kind": "",
        "action": "",
        "stop_reason": "",
        "status": "stopped",
        "plan_ready": False,
        "suite_status": "invalid",
        "unchanged_attempts": 0,
        "revisions": 0,
        "acceptance_attempted": False,
        "acceptance_outcome": "",
        "verification_actions": 0,
        "checker_unknown": False,
    },
)
def build(g, p):
    for name, lo, hi in [
        ("max_rounds", 1, 20),
        ("checker_revisions", 0, 5),
        ("unchanged_retries", 0, 2),
    ]:
        value = getattr(p, name)
        if type(value) is not int or not lo <= value <= hi:
            raise ValueError(f"{name} must be in {lo}..{hi}")
    transitions = [
        ("plan", "finish", when(action="finish")),
        ("plan", "build_suite", default),
        ("build_suite", "generate"),
        ("generate", "extract"),
        ("extract", "dedupe", when(has_candidate=True)),
        ("extract", "next_round", default),
    ]
    routes = {
        "dedupe": ["structure", "generate"],
        "structure": ["functional", "synth_only", "generate"],
        "functional": ["diagnose", "acceptance", "final_synth", "generate"],
        "diagnose": ["revise_suite", "revise_plan", "generate"],
        "revise_suite": ["functional"],
        "revise_plan": ["generate"],
        "acceptance": ["functional", "final_synth"],
        "final_synth": ["generate"],
        "synth_only": ["generate"],
        "next_round": ["generate"],
    }
    for source, targets in routes.items():
        for target in targets:
            destination = (
                "next_round"
                if target == "generate" and source != "next_round"
                else target
            )
            transitions.append((source, destination, when(action=target)))
        transitions.append((source, "finish", default))
    return (
        g.with_state(
            max_rounds=p.max_rounds,
            checker_revisions=p.checker_revisions,
            unchanged_retries=p.unchanged_retries,
        )
        .with_transitions(*transitions)
        .with_entrypoint("plan")
    )
