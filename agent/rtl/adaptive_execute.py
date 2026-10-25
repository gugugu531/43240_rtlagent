"""Use the same neutral observations for independent behavior-model comparison."""

from __future__ import annotations

import hashlib

from .identity import suite_hash
from .observation import sampling_plan_from_suite
from .properties import _validate_trace
from .suite.schema import validate_suite
from .suite.semantics import SuiteError
from .suite.testbench import parse_traces


def evaluate_model(suite, trace):
    """Compare post-edge ports without exposing DUT observations to the expected model.

    The existing comparator computes expectations exclusively from the suite's
    inputs and model state. The intermediate wire format preserves every unknown
    bit; the old executable testbench is never run by this adapter.
    """
    suite = validate_suite(suite)
    if suite["mode"] != "behavior":
        raise SuiteError("adaptive model comparison requires behavior mode")
    plan = sampling_plan_from_suite(suite)
    _validate_trace(trace, plan)
    marker = hashlib.sha256(trace.execution_id.encode()).hexdigest()[:16]
    outputs = sorted(name for name, port in suite["ports"].items() if port["direction"] == "output")
    lines = []
    for row in trace.rows:
        if row["phase"] != "post":
            continue
        values = []
        for name in outputs:
            value = row["values"][name]
            digits = "".join(
                str((value["bits"] >> bit) & 1)
                if value["known"] & (1 << bit)
                else "x"
                for bit in reversed(range(value["width"]))
            )
            values.append("b:" + digits)
        lines.append(f"RTLA_{marker}|{row['case_index']}|{row['step']}|" + "|".join(values))
    details = parse_traces("\n".join(lines), suite, marker, compare_expected=True)
    return {
        **details,
        "kind": "behavior_model",
        "candidate_hash": trace.candidate_hash,
        "execution_id": trace.execution_id,
        "plan_hash": trace.plan_hash,
        "suite_hash": suite_hash(suite),
        "sampling": "neutral_post_edge_or_settle",
        "sampling_version": trace.sampling_version,
        "semantic_coverage_proven": False,
    }
