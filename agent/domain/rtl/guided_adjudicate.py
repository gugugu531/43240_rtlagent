"""Flat attribution output for guided_verify."""

from __future__ import annotations

from dataclasses import dataclass
import json


class AdjudicationError(ValueError):
    pass


@dataclass(frozen=True)
class Adjudication:
    decision: str
    reason: str
    failed_cases: tuple[str, ...]

    def public_dict(self):
        return {
            "decision": self.decision,
            "reason": self.reason,
            "failed_cases": list(self.failed_cases),
        }


def adjudicate_request(task, candidate, checker, failures):
    user = (
        "Public task:\n"
        + task.prompt
        + "\n\nResolved interface:\n"
        + json.dumps(task.expected_interface.public_dict(), ensure_ascii=False)
        + "\n\nCandidate implementation:\n```verilog\n"
        + candidate.code
        + "\n```\n\nChecker table:\n"
        + checker
        + "\n\nObserved failures:\n"
        + json.dumps(failures, ensure_ascii=False, separators=(",", ":"))
        + "\n\nDecide whether the candidate or the checker is wrong. "
        "Return only flat key=value lines: decision, reason, failed_cases. "
        "decision is checker_error, solution_error or spec_unclear. "
        "Failed cases are comma-separated case ids. Do not add prose."
    )
    return [
        {
            "role": "system",
            "content": (
                "You are diagnosing a mismatch between a public RTL specification and a "
                "small hand-written checker table. The checker may be wrong. "
                "Use only the public task, the candidate and the recorded failures. "
                "Do not invent requirements or expected values."
            ),
        },
        {"role": "user", "content": user},
    ]


def parse_adjudication(text, *, case_ids, max_reason=1000):
    text = text.strip()
    if text.startswith("```") and text.endswith("```"):
        text = "\n".join(text.splitlines()[1:-1]).strip()
    if not text or len(text) > 8192:
        raise AdjudicationError("adjudication output missing or too large")
    values, seen = {}, set()
    for raw in text.strip().splitlines():
        line = raw.strip()
        if not line:
            continue
        if "=" not in line:
            raise AdjudicationError("adjudication lines must be key=value")
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if key not in {"decision", "reason", "failed_cases"}:
            raise AdjudicationError("unknown adjudication key")
        if key in seen:
            raise AdjudicationError("duplicate adjudication key")
        seen.add(key)
        values[key] = value
    decision = values.get("decision")
    if decision not in ("checker_error", "solution_error", "spec_unclear"):
        raise AdjudicationError("invalid adjudication decision")
    reason = values.get("reason", "")
    if not reason or len(reason) > max_reason:
        raise AdjudicationError("adjudication reason missing or too long")
    failed = tuple(
        item.strip() for item in values.get("failed_cases", "").split(",")
        if item.strip()
    )
    if set(failed) - set(case_ids):
        raise AdjudicationError("unknown failed case id")
    return Adjudication(decision, reason, failed)
