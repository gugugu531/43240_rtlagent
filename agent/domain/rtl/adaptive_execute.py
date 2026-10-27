"""Use the same neutral observations for independent behavior-model comparison."""

from __future__ import annotations

from .identity import suite_hash
from .observation import sampling_plan_from_suite, validate_trace
from .suite.schema import validate_suite
from .suite.semantics import SuiteError
from .suite.testbench import compare_trace_rows


def evaluate_model(suite, trace):
    """Compare post-edge ports without exposing DUT observations to the expected model.

    The existing comparator computes expectations exclusively from the suite's
    inputs and model state. Structured bit values preserve every unknown bit;
    the old executable testbench is never run by this adapter.
    """
    suite = validate_suite(suite)
    if suite["mode"] != "behavior":
        raise SuiteError("adaptive model comparison requires behavior mode")
    plan = sampling_plan_from_suite(suite)
    validate_trace(trace, plan)
    outputs = sorted(name for name, port in suite["ports"].items() if port["direction"] == "output")
    rows = {
        (row["case_index"], row["step"]): {
            name: (row["values"][name]["bits"], row["values"][name]["known"])
            for name in outputs
        }
        for row in trace.rows if row["phase"] == "post"
    }
    details = compare_trace_rows(rows, suite)
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
