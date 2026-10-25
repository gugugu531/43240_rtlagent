"""One combined attribution/complete-RTL response; never a format retry."""

import json
import re
from copy import deepcopy
from pathlib import PurePosixPath
from agent.llm.structured import strict_json
from agent.rtl.adaptive_check import _review_preflight
from agent.rtl.extract import extract_result


def _source_location(text):
    """Shorten only our temporary candidate path; keep its filename and line."""
    return re.sub(
        r"(?<=\[)/[^\]\n]*/rtla_(?:lint|synth|functional)_[^/\]\n]+/"
        r"(solution\.sv)(?=:\d+\])", r"\1", text,
    )


def _diagnostic_key(item):
    return tuple(item.get(name) for name in ("code", "severity", "message"))


def _failure_context(failure):
    """Make a prompt view without changing the bound check or its saved trace."""
    result = deepcopy(failure)
    details = result.get("details", {})
    sources = {name: details.pop(name) for name in
               ("knowledge_diagnostics", "repair_diagnostics") if name in details}
    commands = {command.get("command_index"): command for command in details.get("knowledge_commands", [])}
    items, seen = [], set()
    for source_name, source in sources.items():
        for original in source.get("items", []):
            key = _diagnostic_key(original)
            if source_name == "repair_diagnostics" and key in seen:
                continue
            seen.add(key)
            item = deepcopy(original)
            # The command table carries version provenance once per invocation.
            command = commands.get(item.get("command_index"), {})
            for name in ("tool", "version", "version_source", "version_probe_id"):
                if name in command and item.get(name) == command[name]:
                    item.pop(name, None)
            item["message"] = _source_location(item["message"])
            items.append(item)
    if sources:
        result["diagnostics"] = {
            "items": items,
            "source_limits": {name: {key: value for key, value in source.items() if key != "items"}
                              for name, source in sources.items()},
        }
    # Drop only excerpt lines already represented exactly by a structured item.
    remaining = []
    for line in result.get("excerpt", "").splitlines():
        match = re.fullmatch(r"(ERROR|WARNING):\s*\[([^\]]+)\]\s*(.*)", line, re.I)
        if match and (match[2], match[1].lower(), match[3]) in seen:
            continue
        remaining.append(_source_location(line))
    result["excerpt"] = "\n".join(remaining)
    if not result["excerpt"]:
        result.pop("excerpt")
    result.pop("elapsed_s", None)
    result.pop("log_paths", None)
    if "command" in result:
        result["command"] = [[PurePosixPath(command[0]).name, *command[1:]]
                             for command in result["command"]]
    details.pop("knowledge_version_probes", None)
    for command in details.get("knowledge_commands", []):
        command.pop("version_probe_id", None)
    return result


def _evidence_context(evidence):
    result = deepcopy(evidence)
    if isinstance(result.get("failure"), dict):
        result["failure"] = _failure_context(result["failure"])
    observations = result.get("observations")
    if isinstance(observations, dict):
        observations.pop("complete_history_artifact", None)
    return result


def _checker_context(checker):
    if checker is None:
        return None
    result = checker.public_dict()
    # Preserve the full model/properties and the summary counts, not the derived
    # event table already encoded by the model and cases. The frozen data stays intact.
    result["preflight"] = _review_preflight(checker)
    return result


def repair_request(task, parent, evidence, checker=None):
    public = {"prompt": task.prompt, "interface": task.interface, "top": task.top}
    return [
        {"role": "system", "content": (
            "You are a digital frontend engineer. Attribute the failure and perform any necessary repair in one response, "
            "using the complete public task, current RTL, and actual tool evidence. "
            "The checker may also be wrong: do not change task semantics merely to satisfy it. "
            "Repair only clearly identified RTL errors and preserve correct behavior. "
            "Output one fenced json block with exactly the fields decision and reason. "
            "decision must be rtl_error, checker_suspect, or spec_unclear; reason must identify the concrete root cause. "
            "Only for rtl_error, follow it with one fenced verilog block containing the complete synthesizable file. "
            "Do not output other prose, testbenches, patches, or omitted code. Do not introduce unspecified reset behavior or interfaces. "
            "Use nonblocking assignments for sequential logic and defaults for combinational logic. "
            "Strictly preserve clocks, resets, priorities, widths, signedness, and cycle behavior. "
            "For compilation or synthesis errors, inspect every independent root cause and writer; do not merely suppress log messages."
        )},
        {"role": "user", "content": json.dumps({
            "public_task": public, "candidate": {"id": parent.id, "hash": parent.code_hash, "rtl": parent.code},
            "evidence": _evidence_context(evidence),
            "checker": _checker_context(checker),
        }, ensure_ascii=False, separators=(",", ":"))},
    ]


def parse_repair(text, top, *, finish_reason=None):
    if finish_reason == "length":
        raise ValueError("combined repair response was truncated")
    if not isinstance(text, str) or len(text.encode()) > 524288:
        raise ValueError("invalid combined repair response size")
    envelope_error = "repair requires one JSON decision and an optional complete RTL block"
    body = text.strip()
    header = re.match(r"```json[ \t]*\r?\n", body)
    if body.startswith("```") and header is None:
        raise ValueError(envelope_error)
    if header:
        body = body[header.end():].lstrip(" \t\r\n")
    try:
        # raw_decode locates the exact JSON boundary, including escaped quotes and
        # braces in strings. strict_json still enforces the decision's full rules.
        _, end = json.JSONDecoder().raw_decode(body)
        decision = strict_json(body[:end])
    except RecursionError as error:
        raise ValueError("repair decision JSON nesting exceeds the parser limit") from error
    remainder = body[end:]
    if header:
        closing = re.match(r"[ \t\r\n]*\n```[ \t]*(?:\r?\n|$)", remainder)
        if closing is None:
            raise ValueError(envelope_error)
        remainder = remainder[closing.end():]
    elif remainder.strip() and re.match(r"[ \t]*\r?\n", remainder) is None:
        raise ValueError(envelope_error)
    remainder = remainder.strip()
    code = None
    if remainder:
        match = re.fullmatch(
            r"```(?:verilog|systemverilog|sv)[ \t]*\r?\n(.*?)\r?\n```",
            remainder, re.DOTALL,
        )
        if match is None or "```" in match.group(1):
            raise ValueError(envelope_error)
        code = match.group(1)
    if (not isinstance(decision, dict) or set(decision) != {"decision", "reason"}
            or not isinstance(decision["decision"], str)
            or decision["decision"] not in {"rtl_error", "checker_suspect", "spec_unclear"}
            or not isinstance(decision["reason"], str) or not decision["reason"].strip()):
        raise ValueError("invalid repair attribution")
    if (decision["decision"] == "rtl_error") != (code is not None):
        raise ValueError("only attributed RTL errors may contain a replacement")
    extraction = extract_result(f"```verilog\n{code}\n```", top) if code is not None else None
    if extraction and (extraction.status != "ok" or not extraction.complete or not extraction.target_module_found):
        raise ValueError("repair did not contain one complete target implementation")
    return decision, extraction
