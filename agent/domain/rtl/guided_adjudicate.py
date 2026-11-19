"""Flat attribution output for guided_verify."""

from __future__ import annotations

from dataclasses import dataclass

from .guided_author import _format_interface, _format_kv_summary, _strip_internal_hashes


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


def _format_failures(failures):
    clean = _strip_internal_hashes(failures)
    if isinstance(clean, list) and clean:
        lines = []
        for idx, item in enumerate(clean, 1):
            if isinstance(item, dict):
                summary = ", ".join(f"{k}={v}" for k, v in item.items() if v is not None)
                lines.append(f"  {idx}. {summary}")
            else:
                lines.append(f"  {idx}. {item}")
        return "\n".join(lines)
    if isinstance(clean, dict):
        return _format_kv_summary(clean)
    return str(clean) if clean else "  (none)"


def adjudicate_request(task, candidate, checker, failures, *, execution=None):
    clean_exec = _strip_internal_hashes(execution)
    exec_text = _format_kv_summary(clean_exec) if isinstance(clean_exec, dict) else str(clean_exec or "(none)")
    user = (
        "Public task:\n"
        + task.prompt
        + "\n\nResolved interface:\n"
        + _format_interface(task.expected_interface.public_dict())
        + "\n\nCandidate implementation:\n```verilog\n"
        + candidate.code
        + "\n```\n\nChecker table:\n"
        + checker
        + "\n\nHost execution contract and expanded sampling plan:\n"
        + exec_text
        + "\n\nObserved failures:\n"
        + _format_failures(failures)
        + "\n\nDecide whether the candidate or the checker is wrong. "
        "Return only flat key=value lines: decision, reason, failed_cases. "
        "decision is checker_error, solution_error, mixed or spec_unclear. "
        "Use mixed when both the candidate and the checker need changes. "
        "Use spec_unclear when the public specification does not decide the issue. "
        "List every observed failed or unknown case id exactly once in failed_cases. "
        "Use comma-separated case ids. Do not add prose."
    )
    return [
        {
            "role": "system",
            "content": (
                "You are diagnosing a mismatch between a public RTL specification and a "
                "small hand-written checker table. The checker may be wrong. "
                "Use only the public task, candidate, checker table, host execution mechanics and recorded failures. "
                "Failure step indices refer to expanded sampling events, not table lines. "
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
    if decision not in ("checker_error", "solution_error", "mixed", "spec_unclear"):
        raise AdjudicationError("invalid adjudication decision")
    reason = values.get("reason", "")
    if not reason or len(reason) > max_reason:
        raise AdjudicationError("adjudication reason missing or too long")
    failed = tuple(item.strip() for item in values.get("failed_cases", "").split(","))
    if not all(failed) or len(failed) != len(set(failed)) or set(failed) != set(case_ids):
        raise AdjudicationError("failed_cases must name each observed failed or unknown case exactly once")
    return Adjudication(decision, reason, failed)
