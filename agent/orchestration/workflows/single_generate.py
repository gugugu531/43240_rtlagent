"""One baseline-equivalent generation, then official extraction and selection."""

from agent.kit import workflow


@workflow(
    "single_generate",
    nodes={
        "generate": {"use": "baseline_generate"},
        "extract": {"use": "baseline_extract"},
        "select": {"use": "select"},
        "finish": {"use": "finish"},
    },
    state={
        "round": 0,
        "target_id": None,
        "reply_id": None,
        "has_candidate": False,
        "stop_reason": "",
        "status": "completed",
    },
)
def build(g, p):
    return g.with_transitions(
        ("generate", "extract"), ("extract", "select"), ("select", "finish")
    ).with_entrypoint("generate")
