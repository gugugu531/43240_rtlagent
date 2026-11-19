"""Public inputs, decision memory and reply grammar for the guided RTL author."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re

from .extract import ExtractionResult, extract_result


class AuthorDecisionError(ValueError):
    """The reply did not express a single executable decision."""


@dataclass(frozen=True)
class AuthorDecision:
    action: str
    reason: str
    case_id: str | None = None
    extraction: ExtractionResult | None = None

    def public_dict(self):
        """Keep the decision in history without copying a full RTL draft."""
        entry = {"action": self.action, "reason": self.reason}
        if self.case_id is not None:
            entry["case_id"] = self.case_id
        return entry


_HISTORY_FIELDS = {
    "round", "stage", "role", "action", "reason", "case_id", "candidate_id",
    "child_id", "source_call_id", "review_action", "review_reason",
    "status", "outcome", "changed", "checked",
}

_INTERNAL_ID_KEYS = {
    "candidate_hash", "code_hash", "child_hash", "checker_hash",
    "reviewed_checker_hash", "sampling_plan_hash", "plan_hash",
    "checker_version", "execution_id",
}


def _strip_internal_hashes(value):
    """Drop internal host-binding hashes from prompt-facing views without mutating inputs."""
    if isinstance(value, dict):
        return {
            key: _strip_internal_hashes(item)
            for key, item in value.items()
            if key not in _INTERNAL_ID_KEYS and not key.endswith("_hash")
        }
    if isinstance(value, list):
        return [_strip_internal_hashes(item) for item in value]
    return value


def _format_interface(interface_dict):
    if not isinstance(interface_dict, dict):
        return str(interface_dict)
    lines = []
    if interface_dict.get("top"):
        lines.append(f"- Top module: {interface_dict['top']}")
    ports = interface_dict.get("ports")
    if isinstance(ports, list) and ports:
        port_parts = []
        for port in ports:
            if not isinstance(port, dict):
                port_parts.append(str(port))
                continue
            direction = port.get("direction", "")
            width = port.get("width")
            signed = " signed" if port.get("signed") else ""
            width_str = f"[{width - 1}:0]" if isinstance(width, int) and width > 1 else ""
            name = port.get("name", "?")
            port_parts.append(" ".join(part for part in (direction + signed, width_str, name) if part))
        lines.append("- Ports: " + ", ".join(port_parts))
    return "\n".join(lines) if lines else "(none)"


def _format_kv_summary(data, indent="  "):
    if not isinstance(data, dict) or not data:
        return indent + "(none)"
    lines = []
    for key, value in data.items():
        if value is None or value == [] or value == {}:
            continue
        if isinstance(value, dict):
            lines.append(f"{indent}- {key}:")
            lines.append(_format_kv_summary(value, indent + "  "))
        elif isinstance(value, list):
            if all(not isinstance(item, (dict, list)) for item in value):
                lines.append(f"{indent}- {key}: {', '.join(str(item) for item in value)}")
            else:
                lines.append(f"{indent}- {key}:")
                for item in value:
                    if isinstance(item, dict):
                        summary = ", ".join(f"{k}={v}" for k, v in item.items() if v is not None)
                        lines.append(f"{indent}  * {summary}")
                    else:
                        lines.append(f"{indent}  * {item}")
        else:
            lines.append(f"{indent}- {key}: {value}")
    return "\n".join(lines) if lines else indent + "(none)"


def _format_history(entries):
    if not entries:
        return "  (no prior decisions)"
    lines = []
    for idx, note in enumerate(entries, 1):
        parts = []
        if "round" in note:
            parts.append(f"round {note['round']}")
        if note.get("role"):
            parts.append(str(note["role"]))
        if note.get("stage"):
            parts.append(f"[{note['stage']}]")
        if note.get("action"):
            parts.append(f"action: {note['action']}")
        if note.get("review_action"):
            parts.append(f"review_action: {note['review_action']}")
        if note.get("case_id"):
            parts.append(f"case: {note['case_id']}")
        if note.get("candidate_id"):
            cand = str(note["candidate_id"])
            if note.get("child_id"):
                cand += f" -> {note['child_id']}"
            parts.append(f"candidate: {cand}")
        if "changed" in note:
            parts.append("changed: yes" if note["changed"] else "changed: no")
        if "checked" in note:
            parts.append("checked: yes" if note["checked"] else "checked: no")
        if note.get("status"):
            parts.append(f"status: {note['status']}")
        if note.get("outcome"):
            parts.append(f"outcome: {note['outcome']}")
        reason = note.get("review_reason") or note.get("reason")
        line = f"  {idx}. " + ", ".join(parts)
        if reason:
            line += f" — {reason}"
        lines.append(line)
    return "\n".join(lines)


def _format_author_evidence(task, candidate, *, structure, behavior, checker_status,
                            active, history, budget, execution):
    clean_structure = _strip_internal_hashes(structure)
    clean_behavior = _strip_internal_hashes(behavior)
    clean_execution = _strip_internal_hashes(execution)
    clean_budget = _strip_internal_hashes(budget)
    clean_checker_status = _strip_internal_hashes(checker_status)
    if isinstance(clean_checker_status, dict):
        checker_block = "Checker status:\n" + _format_kv_summary(clean_checker_status)
    else:
        checker_block = f"Checker status: {clean_checker_status}"
    checker_block += "\nActive case IDs: " + (", ".join(active) if active else "(none)")
    sections = [
        f"Candidate: {candidate.id} (top module: {task.top})",
        "Resolved interface:\n" + _format_interface(task.expected_interface.public_dict()),
        "Structural checks:\n" + _format_kv_summary(clean_structure),
        checker_block,
        "Behavior verification:\n" + _format_kv_summary(clean_behavior),
    ]
    if clean_execution:
        sections.append("Execution contract:\n" + _format_kv_summary(clean_execution))
    sections.append("Decision history:\n" + _format_history(author_history(history)))
    sections.append("Shared budget:\n" + _format_kv_summary(clean_budget))
    return "\n\n".join(sections)

# A reason can discuss both 'module' and 'endmodule' in ordinary prose. Look
# for a declaration with a terminated header before treating it as embedded RTL.
_MODULE_DEFINITION = re.compile(
    r"\b(?:module|macromodule)\s+(?:(?:automatic|static)\s+)?"
    r"(?:[A-Za-z_][\w$]*|\\\S+\s)"
    r"(?:\s+import\s+[^;]+;)*"
    r"(?:\s*#\s*\(.*?\))?(?:\s*\(.*?\))?\s*;.*?\bendmodule\b"
)


def author_history(history):
    """Project all notes in order onto the decision fields shared with the author."""
    return [
        {key: value for key, value in note.items()
         if key in _HISTORY_FIELDS and isinstance(value, (str, int))}
        for note in history
    ]


def author_decision_request(task, candidate, *, structure, behavior, checker_text, checker_status,
                            case_ids, history, budget, execution=None):
    """Build fresh author messages from the current candidate and its host-bound evidence."""
    for report in (structure, behavior):
        if report and (report.get("candidate_id") not in (None, candidate.id)
                       or report.get("candidate_hash") not in (None, candidate.code_hash)):
            raise ValueError("author decision evidence belongs to a different candidate")

    active = list(case_ids)
    report_text = _format_author_evidence(
        task, candidate, structure=structure, behavior=behavior,
        checker_status=checker_status, active=active, history=history,
        budget=budget, execution=execution,
    )
    system = (
        "You are the RTL author. Decide whether to submit this exact candidate, revise its "
        "complete implementation, or ask the independent checker to review one active test "
        "point. Use the public specification and the supplied evidence. Test expectations "
        "can be mistaken. A pass covers only the comparisons actually made. Unavailable "
        "checks, unknown bits and omitted outputs remain unverified. You can submit with "
        "an outstanding disagreement or incomplete verification. Explain your choice briefly. "
        "Consider the replies to earlier review requests and the shared budget."
    )
    user = (
        "Public task:\n" + task.prompt
        + "\n\nPublic interface text:\n" + task.interface
        + "\n\nCurrent candidate RTL:\n```verilog\n" + candidate.code.rstrip() + "\n```"
        + "\n\nActive checker table with test-point explanations:\n" + (checker_text or "(none)")
        + "\n\nHost report and decision history:\n"
        + report_text
        + "\n\nReturn exactly one action using plain key=value header lines. "
          "Keep reason to one line of at most 400 characters.\n"
          "Submit the current candidate:\naction=submit\nreason=<brief reason>\n\n"
          "Revise this candidate in the same reply:\naction=revise\nreason=<brief reason>\n"
          "```systemverilog\n<complete replacement RTL including the required top>\n```"
    )
    if active:
        user += (
            "\n\nRequest independent review of one active test point:\naction=review\n"
            "reason=<brief reason for questioning this point>\ncase_id=<one active case id>"
        )
    else:
        user += "\n\nNo active test point is available for review. Choose submit or revise."
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def parse_author_decision(text, *, top, case_ids):
    """Accept one header and, for a revision, exactly one complete, labelled RTL block."""
    if not isinstance(text, str) or not text.strip():
        raise AuthorDecisionError("author decision is empty")
    lines = text.strip().splitlines()
    first_fence = next((i for i, line in enumerate(lines) if line.strip().startswith("```")), len(lines))
    fields = {}
    for line in lines[:first_fence]:
        if not line.strip():
            continue
        key, separator, value = line.partition("=")
        key = key.strip()
        if not separator or key not in ("action", "reason", "case_id") or key in fields:
            raise AuthorDecisionError("expected unique action, reason and optional case_id header lines")
        fields[key] = value.strip()

    action, reason = fields.get("action"), fields.get("reason", "")
    if action not in ("submit", "revise", "review"):
        raise AuthorDecisionError("choose one action: submit, revise or review")
    if (not reason or len(reason) > 400 or "```" in reason
            or _MODULE_DEFINITION.search(re.sub(r"/\*.*?\*/", " ", reason))):
        raise AuthorDecisionError("reason must be a short line of text without an RTL draft")
    case_id = fields.get("case_id")
    if action == "review":
        if not case_id or case_id not in set(case_ids):
            raise AuthorDecisionError("review requires one active case_id")
    elif case_id is not None:
        raise AuthorDecisionError("case_id belongs only to a review")

    extraction = None
    if action == "revise":
        block = lines[first_fence:]
        if (len(block) < 3 or block[0].strip().lower() not in ("```verilog", "```systemverilog")
                or block[-1].strip() != "```" or any("```" in line for line in block[1:-1])):
            raise AuthorDecisionError("revise requires exactly one closed verilog or systemverilog fence")
        extraction = extract_result("\n".join(block), top)
        if (extraction.status != "ok" or not extraction.complete or not extraction.target_module_found
                or extraction.suspected_truncation):
            raise AuthorDecisionError(f"revision must contain the complete {top} RTL: {extraction.status}")
    elif first_fence != len(lines):
        raise AuthorDecisionError("only revise may include an RTL block")
    return AuthorDecision(action, reason, case_id, extraction)
