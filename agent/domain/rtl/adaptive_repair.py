"""One combined attribution/complete-RTL response; never a format retry.

The repair stage records only conclusions that can be traced back to the request
and the saved check evidence. Candidate correctness is never claimed here.
"""

import json
import re
from copy import deepcopy
from pathlib import PurePosixPath
from agent.llm.structured import strict_json
from agent.domain.rtl.adaptive_check import _review_preflight
from agent.domain.rtl.extract import extract_result

ATTRIBUTION_CONTRACT_VERSION = 2
_DECISIONS = ("rtl_error", "checker_suspect", "spec_unclear")
_MODEL_BINDING_KEYS = ("case_id", "step", "signal", "expected_value", "actual_value")
_PROPERTY_BINDING_KEYS = ("property_id", "case_id", "trigger_step",
                          "expected_holds", "observed_holds")
_PUBLIC_NOTE = ("Missing interface declarations remain unresolved; "
                "the original public task takes precedence.")


_SYSTEM = (
    "You are a digital frontend engineer. Attribute the observed failure and perform any necessary repair "
    "in one response, using the complete public task, expected public interface, current RTL, and actual tool evidence. "
    "The approved checker is not ground truth: first re-derive the expected behavior from the public requirement "
    "quotation and the original task, then compare that derivation with the checker and with the actual result. "
    "A checker_suspect decision does not prove the candidate RTL is correct; this stage can never claim the candidate "
    "is correct, verified, or passing. "
    "Output one fenced json block whose object contains these fields: attribution_contract_version (must be 2), decision, "
    "reason, candidate_conclusion (must be unverified), failure_binding, additional_recorded_mismatches, checker_defect, "
    "rtl_defect, requirement_id, public_quote. "
    "decision must be rtl_error, checker_suspect, or spec_unclear; reason must identify the concrete root cause. "
    "For behavior evidence, failure_binding must echo the recorded counterexample: model route case_id, step, signal, "
    "expected_value, actual_value; properties route property_id, case_id, trigger_step, expected_holds, observed_holds. "
    "failure_binding.public_expectation must be the value you re-derived from the public task: for rtl_error it must equal "
    "the checker expected value and differ from the recorded actual value; for checker_suspect it must equal the recorded "
    "actual value and differ from the checker expected value; spec_unclear may use null. "
    "requirement_id must name an existing checker requirement; public_quote must be copied verbatim from the public prompt "
    "or explicit interface text. additional_recorded_mismatches is optional and may only contain rows already present in "
    "the evidence. "
    "For checker_suspect, checker_defect must be an object with path (an existing JSON Pointer into the checker payload) "
    "and a nonempty claim. For rtl_error, rtl_defect must be an object with nonempty locations and optional diagnostics "
    "codes; for structural evidence every cited diagnostic code must appear in the tool evidence. spec_unclear never "
    "includes a replacement RTL block. "
    "Only for rtl_error, follow the json block with one fenced verilog block containing the complete synthesizable file. "
    "Do not output other prose, testbenches, patches, or omitted code. Do not introduce unspecified reset behavior or interfaces. "
    "Use nonblocking assignments for sequential logic and defaults for combinational logic. "
    "Strictly preserve clocks, resets, priorities, widths, signedness, and cycle behavior. "
    "For compilation or synthesis errors, inspect every independent root cause and writer; do not merely suppress log messages."
)


def _source_location(text):
    """Shorten only our temporary candidate path; keep its filename and line."""
    return re.sub(
        r"(?<=\[)/[^\]\n]*/rtla_(?:lint|synth|functional)_[^/\]\n]+/"
        r"(solution\.sv)(?=:\d+\])", r"\1", text,
    )


def _diagnostic_key(item):
    return tuple(item.get(name) for name in ("code", "severity", "message"))


def _solver_provenance(item):
    # Optional retrieval probes belong to the RAG evidence, not the base prompt.
    # Retain versions printed by the actual source-check command.
    if item.get("version_source") == "version_probe":
        item["version"] = None
        item["version_source"] = None
    item.pop("version_probe_id", None)


def _failure_context(failure):
    """Make a prompt view without changing the bound check or its saved trace."""
    result = deepcopy(failure)
    details = result.get("details", {})
    sources = {name: details.pop(name) for name in
               ("knowledge_diagnostics", "repair_diagnostics") if name in details}
    commands = {command.get("command_index"): command for command in details.get("knowledge_commands", [])}
    for command in commands.values():
        _solver_provenance(command)
    items, seen = [], set()
    for source_name, source in sources.items():
        for original in source.get("items", []):
            key = _diagnostic_key(original)
            if source_name == "repair_diagnostics" and key in seen:
                continue
            seen.add(key)
            item = deepcopy(original)
            _solver_provenance(item)
            # The command table carries version provenance once per invocation.
            command = commands.get(item.get("command_index"), {})
            for name in ("tool", "version", "version_source"):
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


def diagnostic_codes(details):
    """Collect real tool diagnostic codes from one check's saved details, in source order."""
    codes = []
    for name in ("repair_diagnostics", "knowledge_diagnostics", "diagnostics"):
        container = details.get(name) if isinstance(details, dict) else None
        if not isinstance(container, dict):
            continue
        for item in container.get("items") or []:
            code = item.get("code") if isinstance(item, dict) else None
            if isinstance(code, str) and code and code not in codes:
                codes.append(code)
    return codes


def repair_request(task, parent, evidence, checker=None):
    expected = getattr(task, "expected_interface", None)
    public = {
        "prompt": task.prompt,
        "interface": task.interface or "",
        "top": task.top,
        "expected_interface": (expected.public_dict()
                               if expected is not None and hasattr(expected, "public_dict")
                               else None),
        "interface_note": _PUBLIC_NOTE,
    }
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": json.dumps({
            "public_task": public, "candidate": {"id": parent.id, "hash": parent.code_hash, "rtl": parent.code},
            "evidence": _evidence_context(evidence),
            "checker": _checker_context(checker),
        }, ensure_ascii=False, separators=(",", ":"))},
    ]


def _normalized(text):
    return re.sub(r"\s+", " ", text).strip() if isinstance(text, str) else ""


def _public_text(task):
    if task is None:
        return None
    return (getattr(task, "prompt", "") or "") + "\n" + (getattr(task, "interface", "") or "")


def _resolve_pointer(payload, path):
    """Resolve a JSON Pointer into the frozen payload; missing nodes are errors."""
    if not isinstance(path, str) or not path.startswith("/"):
        raise ValueError("A-06 checker_defect.path must be a JSON Pointer")
    node = payload
    for part in path.split("/")[1:]:
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(node, list):
            if not re.fullmatch(r"(?:0|[1-9][0-9]*)", part) or int(part) >= len(node):
                raise ValueError("A-06 checker_defect.path does not exist")
            node = node[int(part)]
        elif isinstance(node, dict):
            if part not in node:
                raise ValueError("A-06 checker_defect.path does not exist")
            node = node[part]
        else:
            raise ValueError("A-06 checker_defect.path does not exist")
    return node


def _counterexample_binding(route, counterexample):
    """Return (echoed binding, checker expected, recorded actual) for saved evidence."""
    if not isinstance(counterexample, dict):
        raise ValueError("behavior attribution requires the recorded counterexample")
    if route == "properties" or "property_id" in counterexample:
        observations = counterexample.get("observations")
        observed = None
        if isinstance(observations, list) and observations and isinstance(observations[-1], dict):
            observed = observations[-1].get("value")
        binding = {
            "property_id": counterexample.get("property_id"),
            "case_id": counterexample.get("case_id"),
            "trigger_step": counterexample.get("trigger_step", counterexample.get("step")),
            "expected_holds": True,
            "observed_holds": observed,
        }
        return binding, True, observed
    binding = {
        "case_id": counterexample.get("case_id"),
        "step": counterexample.get("step"),
        "signal": counterexample.get("signal"),
        "expected_value": counterexample.get("expected_bits_value"),
        "actual_value": counterexample.get("actual_bits_value"),
    }
    return binding, binding["expected_value"], binding["actual_value"]


def _check_rtl_defect(value, *, structural, evidence_codes):
    defect = value.get("rtl_defect")
    if not isinstance(defect, dict):
        raise ValueError("A-07 rtl_error requires an rtl_defect object")
    locations = defect.get("locations")
    if (not isinstance(locations, list) or not locations or len(locations) > 16
            or any(not isinstance(item, str) or not item.strip() for item in locations)):
        raise ValueError("A-07 rtl_defect requires bounded nonempty locations")
    diagnostics = defect.get("diagnostics")
    if diagnostics is None:
        return
    if not isinstance(diagnostics, list) or len(diagnostics) > 16:
        raise ValueError("A-07 rtl_defect diagnostics exceed their bound")
    cited = []
    for item in diagnostics:
        code = item.get("code") if isinstance(item, dict) else None
        if not isinstance(code, str) or not code.strip():
            raise ValueError("A-07 rtl_defect diagnostics need nonempty codes")
        cited.append(code)
    if structural and not set(cited) <= set(evidence_codes or ()):
        raise ValueError("A-08 cited diagnostic code is absent from the tool evidence")


def _check_additional(value, evidence, route):
    extra = value.get("additional_recorded_mismatches")
    if extra is None:
        return
    if not isinstance(extra, list) or len(extra) > 32:
        raise ValueError("A-03b additional_recorded_mismatches is invalid or oversized")
    recorded = evidence.get("failed_mismatches") if isinstance(evidence, dict) else None
    recorded = recorded if isinstance(recorded, list) else []
    keys = ("property_id", "case_id", "trigger_step") if route == "properties" else (
        "case_id", "step", "signal")
    for item in extra:
        if not isinstance(item, dict):
            raise ValueError("A-03b additional_recorded_mismatches items must be objects")
        matches = [row for row in recorded
                   if isinstance(row, dict) and all(item.get(key) == row.get(key) for key in keys)]
        if route == "model" and item.get("bit") is not None:
            matches = [row for row in matches if row.get("bit") == item.get("bit")]
        if not matches:
            raise ValueError("A-03b additional recorded mismatch is absent from the saved evidence")


def _requirement_ids(checker_payload, evidence):
    if isinstance(checker_payload, dict):
        return [item.get("id") for item in checker_payload.get("requirements") or []
                if isinstance(item, dict)]
    ids = evidence.get("requirement_ids") if isinstance(evidence, dict) else None
    return [item for item in ids or [] if isinstance(item, str)]


def _validate_attribution(value, top, task, evidence, checker_payload):
    if not isinstance(value, dict):
        raise ValueError("repair attribution must be one JSON object")
    missing = [key for key in ("attribution_contract_version", "decision", "reason",
                               "candidate_conclusion") if key not in value]
    if missing:
        raise ValueError("A-01 missing attribution fields: " + ", ".join(missing))
    if type(value["attribution_contract_version"]) is not int or value["attribution_contract_version"] != 2:
        raise ValueError("A-01 attribution_contract_version must be 2")
    decision = value["decision"]
    if not isinstance(decision, str) or decision not in _DECISIONS:
        raise ValueError("A-02 decision must be rtl_error, checker_suspect, or spec_unclear")
    if not isinstance(value["reason"], str) or not value["reason"].strip():
        raise ValueError("A-02 attribution needs a nonempty reason")
    if value["candidate_conclusion"] != "unverified":
        raise ValueError("A-02 candidate_conclusion must be unverified; this stage cannot claim correctness")
    kind = evidence.get("kind") if isinstance(evidence, dict) else "structure"
    if kind == "behavior":
        _validate_behavior(value, decision, task, evidence, checker_payload)
    else:
        _validate_structure(value, decision, task, evidence, checker_payload)


def _validate_behavior(value, decision, task, evidence, checker_payload):
    if not isinstance(checker_payload, dict):
        raise ValueError("behavior attribution requires the frozen checker payload")
    route = evidence.get("route") or checker_payload.get("route")
    if route not in ("model", "properties"):
        raise ValueError("behavior attribution requires a model or properties route")
    binding = value.get("failure_binding")
    if not isinstance(binding, dict):
        raise ValueError("A-03 behavior attribution requires failure_binding")
    canonical, expected, actual = _counterexample_binding(route, evidence.get("counterexample"))
    keys = _PROPERTY_BINDING_KEYS if route == "properties" else _MODEL_BINDING_KEYS
    for key in keys:
        if binding.get(key) != canonical.get(key):
            raise ValueError("A-03 failure_binding differs from the recorded counterexample")
    if decision in ("rtl_error", "checker_suspect") and "public_expectation" not in binding:
        raise ValueError("A-04 failure_binding needs public_expectation")
    public = binding.get("public_expectation")
    if decision == "rtl_error":
        if public != expected or public == actual:
            raise ValueError("A-04 rtl_error requires public_expectation equal to the checker expected value")
    elif decision == "checker_suspect":
        if public != actual or public == expected:
            raise ValueError("A-04 checker_suspect requires public_expectation equal to the recorded actual value")
    requirement = value.get("requirement_id")
    requirement_ids = _requirement_ids(checker_payload, evidence)
    if not isinstance(requirement, str) or requirement not in requirement_ids:
        raise ValueError("A-05 requirement_id must name an existing checker requirement")
    public_text = _public_text(task)
    quote = value.get("public_quote")
    if (public_text is None or not isinstance(quote, str) or not _normalized(quote)
            or _normalized(quote) not in _normalized(public_text)):
        raise ValueError("A-05 public_quote must be copied verbatim from the public task")
    if decision == "checker_suspect":
        defect = value.get("checker_defect")
        if not isinstance(defect, dict):
            raise ValueError("A-06 checker_suspect requires checker_defect")
        path, claim = defect.get("path"), defect.get("claim")
        if not isinstance(path, str) or not path:
            raise ValueError("A-06 checker_defect.path is required")
        if not isinstance(claim, str) or not claim.strip():
            raise ValueError("A-06 checker_defect.claim is required")
        _resolve_pointer(checker_payload, path)
    if decision == "rtl_error":
        _check_rtl_defect(value, structural=False, evidence_codes=None)
    _check_additional(value, evidence, route)


def _validate_structure(value, decision, task, evidence, checker_payload):
    if decision != "rtl_error":
        raise ValueError("A-08 structural evidence may only attribute rtl_error")
    codes = evidence.get("diagnostic_codes") if isinstance(evidence, dict) else None
    codes = [item for item in codes or [] if isinstance(item, str)]
    _check_rtl_defect(value, structural=True, evidence_codes=codes)
    requirement = value.get("requirement_id")
    if requirement is not None:
        requirement_ids = _requirement_ids(checker_payload, evidence)
        if (not isinstance(requirement, str) or not requirement
                or (requirement_ids and requirement not in requirement_ids)):
            raise ValueError("A-05 requirement_id must name an existing checker requirement")
    quote = value.get("public_quote")
    if quote is not None:
        public_text = _public_text(task)
        if (public_text is None or not isinstance(quote, str) or not _normalized(quote)
                or _normalized(quote) not in _normalized(public_text)):
            raise ValueError("A-05 public_quote must be copied verbatim from the public task")


def parse_repair(text, top, *, task=None, evidence=None, checker_payload=None,
                 finish_reason=None):
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
    if not isinstance(decision, dict):
        raise ValueError(envelope_error)
    if (decision.get("decision") == "rtl_error") != (code is not None):
        raise ValueError("only attributed RTL errors may contain a replacement")
    _validate_attribution(decision, top, task, evidence, checker_payload)
    extraction = extract_result(f"```verilog\n{code}\n```", top) if code is not None else None
    if extraction and (extraction.status != "ok" or not extraction.complete
                       or not extraction.target_module_found):
        raise ValueError("repair did not contain one complete target implementation")
    return decision, extraction
