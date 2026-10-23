"""Repair only extraction failures and attributed RTL defects."""

from agent.kit import workflow, when, default


@workflow(
    "repair_loop",
    params={"max_rounds": 2},
    tools={
        "interface": {"use": "interface_check"},
        "lint": {"use": "vivado_lint"},
        "synth": {"use": "vivado_synth"},
    },
    nodes={
        "generate": {"use": "rtl_generate"},
        "extract": {"use": "rtl_extract"},
        "check": {"use": "rtl_checks"},
        "decide": {"use": "repair_decide"},
        "finish": {"use": "finish"},
    },
    state={
        "feedback": "",
        "target_id": None,
        "reply_id": None,
        "round": 0,
        "has_candidate": False,
        "failure_kind": "",
        "check_passed": False,
        "action": "",
        "stop_reason": "",
        "status": "stopped",
    },
)
def build(g, p):
    if type(p.max_rounds) is not int or not 1 <= p.max_rounds <= 20:
        raise ValueError("max_rounds must be in 1..20")
    return (
        g.with_state(max_rounds=p.max_rounds)
        .with_transitions(
            ("generate", "extract"),
            ("extract", "check", when(has_candidate=True)),
            ("extract", "decide", default),
            ("check", "decide"),
            ("decide", "generate", when(action="repair")),
            ("decide", "finish", default),
        )
        .with_entrypoint("generate")
    )
