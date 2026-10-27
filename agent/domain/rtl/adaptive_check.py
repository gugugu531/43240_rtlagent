"""Public-task-only checker and bounded revision contracts; no calls or candidate access."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import itertools
import json
import math
import re

from agent.llm.structured import strict_json
from agent.context.prompts import PROMPT_DIR
from agent.domain.rtl.adaptive_context import public_context, prompt_schema
from agent.domain.rtl.suite.schema import SuiteModel, validate_suite
from agent.domain.rtl.suite.semantics import _validate_expr
from agent.domain.rtl.suite.evaluate import (
    coverage_summary,
    expected_traces,
    require_comparable_expectations,
    require_requirement_coverage,
)


class CheckerError(ValueError):
    pass


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value):
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _sha_text(text):
    return hashlib.sha256(text.encode()).hexdigest()


def _public_task(task):
    # Deliberately enumerate fields; never serialize a context/store or arbitrary attributes.
    return {
        "task_id": task.id,
        "top": task.top,
        "prompt": task.prompt,
        "interface": task.interface,
        "expected_interface": task.expected_interface.public_dict(),
    }


def _task_hash(task):
    return _digest(_public_task(task))


def _route(route):
    if route not in ("model", "properties"):
        raise CheckerError("checker route must be model or properties")
    return route


def _failure_reason(error):
    # A decoder error can include an invalid key verbatim. Keep its escaped form
    # readable and recordable without accepting or silently dropping characters.
    return str(error).encode("utf-8", errors="backslashreplace").decode("utf-8")[:4000]


def _format_atoms(text):
    """Read unchanged keys/scalars without guessing the malformed container structure."""
    token = re.compile(r'"(?:[^"\\\x00-\x1f]|\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))*"'
                       r'|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?'
                       r'|true|false|null')
    atoms, position = [], 0
    while position < len(text):
        if text[position] in " \t\r\n{}[],:":
            position += 1
            continue
        match = token.match(text, position)
        if match is None:
            raise CheckerError("format correction cannot safely identify the original JSON scalars")
        atoms.append(match.group())
        if len(atoms) > 40000:
            raise CheckerError("format correction exceeds the scalar limit")
        position = match.end()
    return atoms


def _load(text, *, finish_reason=None, max_bytes=524288):
    if finish_reason == "length":
        raise CheckerError("checker response was truncated by the output limit")
    if not isinstance(text, str) or not text.strip():
        raise CheckerError("checker response has no final content")
    if len(text.encode()) > max_bytes:
        raise CheckerError("checker JSON exceeds the byte limit")
    depth, quoted, escaped = 0, False, False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            if depth > 64:
                raise CheckerError("checker JSON nesting exceeds 64")
        elif char in "]}":
            depth -= 1
    value = strict_json(text)
    if not isinstance(value, dict):
        raise CheckerError("checker response must be one JSON object")
    pending, count = [value], 0
    while pending:
        node = pending.pop()
        count += 1
        if count > 20000:
            raise CheckerError("checker JSON exceeds the value count limit")
        if isinstance(node, dict):
            for key in node:
                key.encode("utf-8")
            pending.extend(node.values())
        elif isinstance(node, list):
            pending.extend(node)
        elif isinstance(node, str):
            node.encode("utf-8")
        elif isinstance(node, float) and not math.isfinite(node):
            raise CheckerError("checker JSON contains a non-finite number")
    return value


def _drop_request_echo(value, route):
    """Drop the checker-root echo of the request route.

    Only an exact string echo of the route already supplied by the request is
    redundant. A different value, a non-string value or the same key at another
    path is never normalized and stays a strict contract failure.
    """
    if not isinstance(value, dict) or "route" not in value:
        return value, None
    echo = value["route"]
    if not isinstance(echo, str) or echo != route:
        raise CheckerError("checker route member must echo the requested route exactly")
    dropped = [{"path": ["route"], "value": echo, "request_value": route}]
    cleaned = {key: item for key, item in value.items() if key != "route"}
    return cleaned, {"method": "drop_request_echo", "dropped": dropped}


def _drop_redundant_register_clock(value):
    """Drop per-register clock repeats only for the equivalent legacy clock form.

    The legacy top-level clock already binds every state register, so a register
    that repeats exactly that port name carries no additional information. Any
    mismatch, mixed form or missing information keeps the original structure so
    that the strict schema and semantics validators still reject it.
    """
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        return value, None
    if type(value.get("schema_version")) is not int:
        return value, None
    clock, state = value.get("clock"), value.get("state")
    if (not isinstance(clock, dict) or value.get("clocks") is not None
            or not isinstance(clock.get("port"), str) or not clock["port"]
            or clock.get("edge") not in ("posedge", "negedge")):
        return value, None
    if not isinstance(state, dict) or not state:
        return value, None
    for register in state.values():
        if not isinstance(register, dict) or "clock" not in register:
            return value, None
        if not isinstance(register["clock"], str) or register["clock"] != clock["port"]:
            return value, None
    cleaned_state = {
        name: {key: item for key, item in register.items() if key != "clock"}
        for name, register in state.items()
    }
    dropped = [{"path": ["state", name, "clock"], "value": register["clock"]}
               for name, register in state.items()]
    return {**value, "state": cleaned_state}, {
        "method": "drop_redundant_register_clock", "dropped": dropped,
        "legacy_clock": {"port": clock["port"], "edge": clock["edge"]},
    }


def _normalize_checker(value, response, response_form, route, original_text):
    """Apply the two audited construction normalizations and bind each to a hash."""
    records = []
    original_sha = _sha_text(original_text)
    for method, argument in ((_drop_request_echo, route),
                              (_drop_redundant_register_clock, None)):
        value, binding = (method(value) if argument is None
                          else method(value, argument))
        if binding is None:
            continue
        normalized_response = ({**response, "checker": value}
                               if response_form == "wrapped" else value)
        dropped = binding.pop("dropped")
        if response_form == "wrapped":
            dropped = [{"path": ["checker", *item["path"]], **{key: item[key] for key in item if key != "path"}}
                       for item in dropped]
        record = {
            **binding,
            "model_calls": 0,
            "original_response_sha256": original_sha,
            "normalized_response_sha256": _sha_text(_canonical(normalized_response)),
            "response_form": response_form,
            "dropped": dropped,
            "checker_hash_unchanged_by_design": True,
        }
        records.append(record)
    return value, records


@dataclass(frozen=True)
class CheckerDraft:
    status: str
    route: str
    reason: str
    checker_hash: str
    task_hash: str
    _payload_json: str = "null"
    _preflight_json: str = "{}"

    @property
    def payload(self):
        return json.loads(self._payload_json)

    @property
    def preflight(self):
        return json.loads(self._preflight_json)

    def public_dict(self):
        return {
            "status": self.status, "route": self.route, "reason": self.reason,
            "checker_hash": self.checker_hash, "task_hash": self.task_hash,
            "payload": self.payload, "preflight": self.preflight,
            "source_scope": "public_task_only", "repair_authorized": False,
        }


@dataclass(frozen=True)
class FrozenChecker(CheckerDraft):
    _review_json: str = "{}"
    _retryable: bool = False
    _violations_json: str = "[]"
    _review_record_json: str = "{}"

    @property
    def repair_authorized(self):
        return self.status == "approved"

    @property
    def retryable(self):
        """Contract violation that one controlled retry could plausibly correct."""
        return self._retryable

    @property
    def review(self):
        return json.loads(self._review_json)

    @property
    def violations(self):
        return json.loads(self._violations_json)

    @property
    def review_record(self):
        return json.loads(self._review_record_json)

    def public_dict(self):
        return {**super().public_dict(), "review": self.review,
                "retryable": self.retryable, "violations": self.violations,
                "review_record": self.review_record,
                "repair_authorized": self.repair_authorized}


def _instruction(name):
    return (PROMPT_DIR / name).read_text(encoding="utf-8")


def checker_request(task, route):
    """Build messages using only explicit public TaskSpec fields and DSL capabilities."""
    _route(route)
    if route == "model":
        schema = SuiteModel.model_json_schema()
    else:
        from agent.domain.rtl.properties import PropertySuite

        schema = PropertySuite.model_json_schema()
    common, routes = _instruction("adaptive_checker.j2").split("MODEL ROUTE:\n", 1)
    model, properties = routes.split("PROPERTIES ROUTE:\n", 1)
    instruction = common + ("MODEL ROUTE:\n" + model if route == "model"
                            else "PROPERTIES ROUTE:\n" + properties)
    return [
        {"role": "system", "content": instruction},
        {"role": "user", "content": _canonical({
            "task": public_context(task), "route": route,
            "checker_schema": prompt_schema(schema),
        })},
    ]


def _interface(ports, task):
    expected = task.expected_interface
    if not expected.parsed or not expected.complete or not expected.ports:
        raise CheckerError("public interface is incomplete; checker port binding is unavailable")
    actual = {name: (port.get("direction"), port.get("width"))
              for name, port in ports.items() if isinstance(port, dict)}
    declared = {port.name: (port.direction, port.width) for port in expected.ports}
    if any(direction not in ("input", "output") or width is None
           for direction, width in declared.values()):
        raise CheckerError("public interface has unresolved widths or unsupported ports")
    if actual != declared:
        raise CheckerError("checker ports must exactly match the public interface names, directions and widths")


def _expand_cases(value, *, model=False):
    """Expand only explicit bounded static sequences; never infer missing input values."""
    cases, ports = value.get("cases"), value.get("ports")
    if not isinstance(cases, list) or not 1 <= len(cases) <= 8 or not isinstance(ports, dict):
        raise CheckerError("checker needs 1..8 cases and an explicit port map")
    clocks = value.get("clocks") or value.get("clock")
    state = value.get("state", {}) if model else {}
    expanded = []
    for case in cases:
        if not isinstance(case, dict):
            raise CheckerError("case must be an object")
        modes = set(case).intersection(("steps", "sequence", "exhaustive"))
        if len(modes) != 1 or set(case) - {"id", "requirements", *modes}:
            raise CheckerError("case needs exactly one of steps, sequence, exhaustive and no extra fields")
        mode = next(iter(modes))
        result = {key: item for key, item in case.items() if key != mode}
        if mode == "exhaustive":
            if case[mode] is not True or clocks or state:
                raise CheckerError("exhaustive cases require stateless combinational logic")
            inputs = {name: port for name, port in ports.items()
                      if isinstance(port, dict) and port.get("direction") == "input"}
            widths = [port.get("width") for port in inputs.values()]
            if (not inputs or any(type(width) is not int or width < 1 for width in widths)
                    or sum(widths) > 8):
                raise CheckerError("exhaustive input width must be in 1..8")
            result["steps"] = [
                {"inputs": dict(zip(inputs, values)), "sample": True, "edge": False}
                for values in itertools.product(*(range(1 << width) for width in widths))
            ]
        elif mode == "sequence":
            sequence = case[mode]
            if not isinstance(sequence, list) or not 1 <= len(sequence) <= 32:
                raise CheckerError("static sequence needs 1..32 entries")
            steps = []
            for item in sequence:
                if not isinstance(item, dict) or set(item) - {"inputs", "sample", "edge", "edges", "repeat"}:
                    raise CheckerError("invalid static sequence fields")
                repeat = item.get("repeat", 1)
                if type(repeat) is not int or not 1 <= repeat <= 32:
                    raise CheckerError("sequence repeat must be integer 1..32")
                step = {key: val for key, val in item.items() if key != "repeat"}
                steps.extend([step] * repeat)
                if len(steps) > (32 if clocks or state else 256):
                    raise CheckerError("expanded case exceeds its event limit")
            result["steps"] = steps
        else:
            result["steps"] = case[mode]
        steps = result["steps"]
        if not isinstance(steps, list) or not 1 <= len(steps) <= (32 if clocks or state else 256):
            raise CheckerError("each clocked case needs 1..32 events; combinational case needs 1..256")
        expanded.append(result)
    if sum(len(case["steps"]) for case in expanded) > 256:
        raise CheckerError("checker total event limit is 256")
    return {**value, "cases": expanded}


def _model_preflight(value, task):
    from agent.domain.rtl.observation import sampling_plan_from_suite, sampling_hash

    value = _expand_cases(value, model=True)
    value = validate_suite(value, task_text=task.prompt + "\n" + task.interface)
    if value["mode"] != "behavior":
        raise CheckerError("model route requires a behavior suite, not observation-only stimulus")
    _interface(value["ports"], task)
    state = value["state"]
    if len(state) > 8 or any(not name.startswith("model_") for name in state):
        raise CheckerError("behavior model permits at most 8 state registers, all prefixed model_")
    roots = [register["next"] for register in state.values()]
    for key in ("outputs", "output_valid", "output_masks"):
        roots.extend(value.get(key, {}).values())
    for reset in value.get("async_resets") or ([value["async_reset"]] if value.get("async_reset") else []):
        roots.extend(reset["values"].values())
    pending, count = list(roots), 0
    while pending:
        expression = pending.pop()
        count += 1
        if count > 128:
            raise CheckerError("behavior expressions exceed 128 total AST nodes")
        pending.extend(expression.get("args", []))
    symbols = {name: port["width"] for name, port in value["ports"].items()
               if port["direction"] == "input"}
    symbols.update({name: register["width"] for name, register in state.items()})
    for name, expression in value["outputs"].items():
        if _validate_expr(expression, symbols) != value["ports"][name]["width"]:
            raise CheckerError("model output expression width must exactly match port " + name)
    _async_preflight(value, task.prompt + "\n" + task.interface)
    sampling = sampling_plan_from_suite(value)
    preflight = require_comparable_expectations(value, task_text=task.prompt + "\n" + task.interface)
    coverage = require_requirement_coverage(value)
    return value, {
        "kind": "predicted_behavior_comparisons", "expectations": preflight,
        "coverage": coverage, "expression_nodes": count,
        "expectation_shape": analyze_model_expectation_shape(value),
        "sampling_plan_hash": sampling_hash(sampling),
        "actual_comparisons": 0, "semantic_truth_proven": False,
    }


def _has_positive_async_reset(text):
    """Recognize explicit mentions, excluding local reset negations in English/Chinese.

    This is a conservative preflight, not a semantic review. Keep negation local
    to each mention so a different reset's negative clause cannot hide a positive
    requirement. Apply the same rule to public text and supporting quotations.
    """
    pattern = (
        r"\basync(?:hronous(?:ly)?)?\b(?:[\s-]+(?:active|low|high|level|sensitive))*"
        r"[\s-]+(?:reset|clear)(?:s|ting|ing)?\b|"
        r"\b(?:reset|clear)(?:[\s-]+(?:is|must|be|shall|an|a|signal|input|active|low|high|and))*"
        r"[\s-]+async(?:hronous(?:ly)?)?\b|异步(?:的|低电平|高电平|有效|\s)*(?:复位|清零)|"
        r"(?:复位|清零)(?:为|是|采用|使用|\s)*异步"
    )
    negative_before = (
        r"\b(?:no|without|neither|not|never|[a-z]+n['’]t)\s+"
        r"(?:(?:an?|any|use|uses|using|have|has|need|needs|require|requires|"
        r"support|supports|provide|provides|implement|implements|include|includes)\s+)*$|"
        r"\bnon[-\s]$|\b(?:instead\s+of|rather\s+than)\s+(?:an?\s+)?$|"
        r"(?:没有|无需|不|未|无|非)"
        r"(?:\s*(?:任何|一个|应该|应|需要|要求|支持|采用|使用|提供|实现|包含))*\s*$"
    )
    negative_after = (
        r"^\s*(?:(?:is|are|was|should|must|shall|will|can|may|does|do)\s+)?"
        r"(?:also\s+)?(?:(?:not|(?:is|are|was|were)n['’]t)\s+(?:be\s+)?"
        r"(?:required|needed|supported|used|implemented|provided|"
        r"present|available|exist)|absent|unnecessary)\b|"
        r"^\s*(?:不需要|无需|不支持|不使用|不采用|不存在|未使用|未采用|未实现|不是必需)"
    )
    for match in re.finditer(pattern, text, re.I):
        if not (re.search(negative_before, text[:match.start()], re.I)
                or re.search(negative_after, text[match.end():], re.I)):
            return True
    return False


def _async_preflight(value, task_text):
    """Require an off-edge reset observation when the public text explicitly requires it."""
    if not _has_positive_async_reset(task_text):
        return
    resets = value.get("async_resets") or ([value["async_reset"]] if value.get("async_reset") else [])
    if not resets or not any(_has_positive_async_reset(r["quote"]) for r in value["requirements"]):
        raise CheckerError("explicit asynchronous reset needs a quoted asynchronous reset model")
    clocks = set(value.get("clocks") or {value["clock"]["port"]: value["clock"]})
    for reset in resets:
        affected = ({value["state"][name]["clock"] for name in reset["values"]}
                    if value.get("clocks") else clocks)
        covered = False
        for case in value["cases"]:
            prior_inactive, clocked_inactive = False, set()
            for step in case["steps"]:
                active = step["inputs"][reset["port"]] == reset["active"]
                edges = set(step["edges"]) if value.get("clocks") else (clocks if step.get("edge", True) else set())
                covered |= (active and prior_inactive and affected <= clocked_inactive
                            and not edges.intersection(affected) and step.get("sample", True))
                if not active:
                    clocked_inactive.update(edges)
                prior_inactive = not active
        if not covered:
            raise CheckerError("asynchronous reset needs an off-edge sampled assertion after inactive-reset clocking")


def _properties_preflight(value, task):
    from agent.domain.rtl.properties import validate_properties

    if not isinstance(value.get("sampling"), dict):
        raise CheckerError("properties require an explicit sampling plan")
    value = {**value, "sampling": _expand_cases(value["sampling"])}
    _interface(value["sampling"].get("ports", {}), task)
    value = validate_properties(value, task_text=task.prompt + "\n" + task.interface,
                                expected_interface=task.expected_interface)
    bound = {name for prop in value["properties"]
             for key in ("requirements", "abort_requirements") for name in prop[key]}
    if bound != {item["id"] for item in value["requirements"]}:
        raise CheckerError("every declared requirement must bind to a property or its abort")
    census = analyze_property_trigger_census(value)
    return value, {
        "kind": "property_contract_validation", "properties": len(value["properties"]),
        "trigger_census": {
            "properties": census["properties"],
            "predicted_triggered": census["predicted_triggered"],
            "unknown": census["unknown"],
            "predicted_empty": census["predicted_empty"],
            "determinable_rows": len(census["rows"]),
        },
        "actual_triggers": 0, "actual_comparisons": 0, "semantic_truth_proven": False,
    }


_DISTINCT_VALUE_LIMIT = 16
_REVIEW_TABLE_ROW_LIMIT = 1024
_REVIEW_TABLE_BYTE_LIMIT = 32768
_REVIEW_TRIGGER_ROW_LIMIT = 512
_REVIEW_TRIGGER_BYTE_LIMIT = 16384
_REVIEW_REQUIRED_TRIGGER_LIMIT = 64
_REVIEW_REQUIRED_SLICE_LIMIT = 16
_RESET_WORDS = re.compile(r"(?i)(?<![A-Za-z0-9_])(?:reset|rst|clear)(?![A-Za-z0-9_])")
_ONE_WORDS = re.compile(r"(?i)(?<![A-Za-z0-9_])(?:1|one)(?![A-Za-z0-9_])")


def _expected_value(row, name, suite):
    """One host prediction for a sampled output, or None when not comparable."""
    width = suite["ports"][name]["width"]
    full = (1 << width) - 1
    mask = row["masks"][name]
    if (row["valid"][name] is not True or row["mask_known"][name] != full or not mask
            or (row["expected_known"][name] & mask) != mask):
        return None
    return row["expected_bits"][name] & mask


def _model_suite_rows(payload):
    suite = validate_suite(payload)
    return suite, expected_traces(suite)


def _model_expected_rows(suite, rows):
    """Every sampled event with at least one comparable output, in trace order."""
    table = []
    for row in rows:
        if not row["sample"]:
            continue
        outputs, known, masks, valid, bits = {}, {}, {}, {}, 0
        for name in row["expected"]:
            value = _expected_value(row, name, suite)
            outputs[name] = value if value is not None else "unknown"
            known[name] = row["expected_known"][name]
            masks[name] = row["masks"][name]
            valid[name] = row["valid"][name]
            if value is not None:
                bits += row["masks"][name].bit_count()
        if bits:
            table.append({"case_id": row["case_id"], "step": row["step"],
                          "inputs": dict(row["inputs"]), "expected": outputs,
                          "known": known, "masks": masks, "valid": valid})
    return table


def _documented_requirement_text(requirement):
    return " ".join(filter(None, [requirement.get("quote"), requirement.get("source_id")]))


def _expectation_shape(suite, rows):
    """Pure expectation statistics. They warn a review; they never reject a checker."""
    bindings = {case["id"]: list(case.get("requirements", [])) for case in suite["cases"]}
    case_ids_by_requirement = {item["id"]: [] for item in suite["requirements"]}
    for case_id, bound in bindings.items():
        for name in bound:
            case_ids_by_requirement.setdefault(name, []).append(case_id)
    output_stats = {name: {"compared_bits": 0, "expected_ones": 0, "values": set()}
                    for name in suite["outputs"]}
    requirement_stats = {
        name: {"case_ids": case_ids, "sampled_events": 0, "comparable_bits": 0,
               "expected_ones": 0, "patterns": set()}
        for name, case_ids in case_ids_by_requirement.items()}
    sampled_events = comparable_bits = comparable_values = expected_ones = 0
    for row in rows:
        if not row["sample"]:
            continue
        sampled_events += 1
        pattern, row_bits, row_ones = [], 0, 0
        for name in row["expected"]:
            value = _expected_value(row, name, suite)
            stats = output_stats[name]
            if value is None:
                pattern.append(None)
                continue
            bits, ones = row["masks"][name].bit_count(), value.bit_count()
            stats["compared_bits"] += bits
            stats["expected_ones"] += ones
            if len(stats["values"]) <= _DISTINCT_VALUE_LIMIT:
                stats["values"].add(value)
            pattern.append(value)
            comparable_bits += bits
            expected_ones += ones
            comparable_values += 1
            row_bits += bits
            row_ones += ones
        for name in bindings[row["case_id"]]:
            if name not in requirement_stats:
                continue
            stats = requirement_stats[name]
            stats["sampled_events"] += 1
            stats["comparable_bits"] += row_bits
            stats["expected_ones"] += row_ones
            stats["patterns"].add(tuple(pattern))
    outputs = {}
    for name, stats in output_stats.items():
        distinct = sorted(stats["values"])
        outputs[name] = {
            "compared_bits": stats["compared_bits"],
            "expected_ones": stats["expected_ones"],
            "bit_never_one": stats["compared_bits"] > 0 and stats["expected_ones"] == 0,
            "bit_never_zero": (stats["compared_bits"] > 0
                               and stats["expected_ones"] == stats["compared_bits"]),
            "distinct_expected_values": distinct[:_DISTINCT_VALUE_LIMIT],
            "distinct_expected_values_truncated": len(distinct) > _DISTINCT_VALUE_LIMIT,
        }
    requirement_rows = []
    for requirement in suite["requirements"]:
        identity = requirement["id"]
        stats = requirement_stats.get(identity, {"case_ids": [], "sampled_events": 0,
                                                 "comparable_bits": 0, "expected_ones": 0,
                                                 "patterns": set()})
        text = _documented_requirement_text(requirement)
        requirement_rows.append({
            "requirement_id": identity,
            "case_ids": stats["case_ids"],
            "sampled_events": stats["sampled_events"],
            "comparable_bits": stats["comparable_bits"],
            "expected_ones": stats["expected_ones"],
            "distinct_patterns": len(stats["patterns"]),
            "zero_change": stats["comparable_bits"] > 0 and stats["expected_ones"] == 0,
            "one_sided": (stats["comparable_bits"] > 0
                          and stats["expected_ones"] in (0, stats["comparable_bits"])),
            "quote_mentions_one": bool(_ONE_WORDS.search(text)),
            "quote_mentions_reset": bool(_RESET_WORDS.search(text)),
        })
    warnings = [f"output {name} takes one distinct expected value in every sampled comparison"
                for name in sorted(outputs)
                if len(outputs[name]["distinct_expected_values"]) == 1
                and not outputs[name]["distinct_expected_values_truncated"]]
    return {
        "kind": "model_expectation_shape",
        "sampled_events": sampled_events,
        "comparable_bits": comparable_bits,
        "comparable_values": comparable_values,
        "expected_ones": expected_ones,
        "zero_change": comparable_bits > 0 and expected_ones == 0,
        "one_sided": comparable_bits > 0 and expected_ones in (0, comparable_bits),
        "outputs": outputs,
        "requirements": requirement_rows,
        "warnings": warnings,
        "semantic_truth_proven": False,
    }


def analyze_model_expectation_shape(payload):
    """Public host statistics for a model checker; never a semantic verdict."""
    suite, rows = _model_suite_rows(payload)
    return _expectation_shape(suite, rows)


def _synthetic_property_events(plan):
    """All inputs known, every output unknown: only input-determined triggers count."""
    cases = []
    for case in plan["cases"]:
        events = []
        for index, step in enumerate(case["steps"]):
            if plan.get("clock") and not step.get("edge", True):
                continue
            values = {name: {"bits": 0, "known": 0, "width": port["width"]}
                      for name, port in plan["ports"].items()}
            for name, number in step["inputs"].items():
                width = plan["ports"][name]["width"]
                values[name] = {"bits": number & ((1 << width) - 1),
                                "known": (1 << width) - 1, "width": width}
            if plan.get("clock"):
                clock = plan["clock"]
                values[clock["port"]] = {"bits": int(clock["edge"] == "posedge"),
                                         "known": 1, "width": 1}
            events.append({"case_id": case["id"], "step": index,
                           "pre": {"values": dict(values)},
                           "post": {"values": dict(values)}})
        cases.append(events)
    return cases


def _trigger_census(suite):
    from agent.domain.rtl.properties import _value

    plan = suite["sampling"]
    cases = _synthetic_property_events(plan)
    properties, rows = [], []
    totals = {"predicted_triggered": 0, "unknown": 0}
    for prop in suite["properties"]:
        triggered = unknown = 0
        for events in cases:
            for index, event in enumerate(events):
                trigger = _value(prop["trigger"], events, index, None, plan["ports"])
                if trigger is None:
                    unknown += 1
                    continue
                rows.append({"property_id": prop["id"], "case_id": event["case_id"],
                             "step": event["step"], "trigger": bool(trigger),
                             "determinable": True})
                triggered += int(bool(trigger))
        properties.append({"property_id": prop["id"], "predicted_triggered": triggered,
                           "unknown": unknown, "predicted_empty": triggered == 0,
                           "sample_phase": prop["sample_phase"],
                           "warmup_ticks": prop["warmup_ticks"]})
        totals["predicted_triggered"] += triggered
        totals["unknown"] += unknown
    return {
        "kind": "property_trigger_census", "properties": properties, "rows": rows,
        "predicted_triggered": totals["predicted_triggered"],
        "unknown": totals["unknown"],
        "predicted_empty": totals["predicted_triggered"] == 0,
        "semantic_truth_proven": False,
    }


def analyze_property_trigger_census(payload):
    """Public host trigger prediction for currently input-determined trigger rows."""
    from agent.domain.rtl.properties import validate_properties

    return _trigger_census(validate_properties(payload))


def _expression_refs(node):
    if isinstance(node, dict):
        if "ref" in node:
            yield node["ref"]
        for child in node.get("args", []):
            yield from _expression_refs(child)


def _expression_claims(node, path, claims):
    if not isinstance(node, dict):
        return
    if node.get("op") == "concat":
        claims.append({"kind": "concat_arity", "path": path,
                       "value": len(node.get("args", []))})
    elif node.get("op") == "slice":
        claims.append({"kind": "slice", "path": path,
                       "lsb": node.get("lsb"), "width": node.get("width")})
    for index, child in enumerate(node.get("args", [])):
        _expression_claims(child, path + "/args/" + str(index), claims)


def _required_expression_claims(payload):
    found = []
    for name, expression in (payload.get("outputs") or {}).items():
        _expression_claims(expression, "/outputs/" + name, found)
    for name, register in (payload.get("state") or {}).items():
        _expression_claims(register.get("next"), "/state/" + name + "/next", found)
    concat = [item for item in found if item["kind"] == "concat_arity"]
    slices = [item for item in found if item["kind"] == "slice"]
    return concat + slices[:_REVIEW_REQUIRED_SLICE_LIMIT]


def _required_phase_claims(payload):
    state = payload.get("state") or {}
    claims, seen = [], set()
    for name, expression in (payload.get("outputs") or {}).items():
        for ref in _expression_refs(expression):
            if ref in state and ("outputs", ref) not in seen:
                seen.add(("outputs", ref))
                claims.append({"used_in": "outputs", "register": ref, "phase": "NEW"})
    for name in state:
        for ref in _expression_refs((state[name] or {}).get("next")):
            if ref in state and ("state.next", ref) not in seen:
                seen.add(("state.next", ref))
                claims.append({"used_in": "state.next", "register": ref, "phase": "OLD"})
    return claims


def _init_allowed_sources(payload):
    state = payload.get("state") or {}
    resets = payload.get("async_resets") or (
        [payload["async_reset"]] if payload.get("async_reset") else [])
    reset_registers = {name for reset in resets
                       for name in (reset.get("values") or {})}
    allowed = {}
    for name, register in state.items():
        sources = []
        if isinstance(register, dict) and register.get("initial") is not None:
            sources.append("initial")
        if name in reset_registers:
            sources.append("reset")
        allowed[name] = sorted(sources) or ["unconstrained"]
    return allowed


def _required_initial_claims(payload):
    return [{"register": name, "allowed_sources": sources}
            for name, sources in _init_allowed_sources(payload).items()]


def _degenerate_outputs(suite, rows):
    values = {}
    for row in rows:
        if not row["sample"]:
            continue
        for name in row["expected"]:
            value = _expected_value(row, name, suite)
            if value is not None:
                values.setdefault(name, set()).add(value)
    return sorted(name for name, seen in values.items() if len(seen) == 1)


def _bounded_rows(rows, row_limit, byte_limit, row_bits):
    full_sha = _digest(rows)
    kept, summaries, used, truncated = [], {}, 0, False
    for row in rows:
        cost = len(_canonical(row).encode())
        if len(kept) >= row_limit or used + cost > byte_limit:
            truncated = True
            summary = summaries.setdefault(
                row["case_id"],
                {"case_id": row["case_id"], "rows": 0, "comparable_bits": 0})
            summary["rows"] += 1
            summary["comparable_bits"] += row_bits(row)
            continue
        kept.append(row)
        used += cost
    return kept, full_sha, truncated, list(summaries.values())


def _properties_coverage(payload):
    plan = payload.get("sampling") or {}
    inputs, events = set(), 0
    for case in plan.get("cases", []):
        for step in case.get("steps", []):
            if plan.get("clock") and not step.get("edge", True):
                continue
            events += 1
            inputs.add(json.dumps(step.get("inputs", {}), sort_keys=True))
    return {"unique_inputs": len(inputs), "input_domain_size": None,
            "stateless_exhaustive": False, "sampled_events": events}


def build_review_evidence(draft):
    """Bounded host evidence for one review; reads only the frozen checker payload."""
    _check_integrity(draft)
    payload, route = draft.payload, draft.route
    sources = {"checker_only": True, "candidate_rtl": False, "dut_observations": False}
    if route == "model":
        suite, rows = _model_suite_rows(payload)
        table = _model_expected_rows(suite, rows)
        def row_bits(row):
            return sum(row["masks"][name].bit_count()
                       for name in row["expected"]
                       if isinstance(row["expected"][name], int))
        kept, table_sha, truncated, summaries = _bounded_rows(
            table, _REVIEW_TABLE_ROW_LIMIT, _REVIEW_TABLE_BYTE_LIMIT, row_bits)
        evidence = {
            "review_contract_version": 2, "route": "model",
            "checker_hash": draft.checker_hash,
            "table_kind": "expected_table",
            "expected_table_sha256": table_sha,
            "expected_table": kept,
            "expected_table_truncated": truncated,
            "case_summaries": summaries,
            "predicted_triggers": [],
            "coverage_summary": coverage_summary([payload]),
            "expectation_shape": _expectation_shape(suite, rows),
            "trigger_census": {},
            "required_claims": _required_expression_claims(payload),
            "required_trigger_claims": [],
            "required_trigger_claims_truncated": False,
            "required_phase_claims": _required_phase_claims(payload),
            "required_init_claims": _required_initial_claims(payload),
            "required_degenerate_outputs": [
                {"output": name} for name in _degenerate_outputs(suite, rows)],
            "sources": sources,
        }
    else:
        census = analyze_property_trigger_census(payload)
        rows = census["rows"]
        kept, used, omitted, truncated = [], 0, 0, False
        for row in rows:
            cost = len(_canonical(row).encode())
            if len(kept) >= _REVIEW_TRIGGER_ROW_LIMIT or used + cost > _REVIEW_TRIGGER_BYTE_LIMIT:
                truncated = True
                omitted += 1
                continue
            kept.append(row)
            used += cost
        required = [{"kind": "trigger", "property_id": row["property_id"],
                     "case_id": row["case_id"], "step": row["step"],
                     "value": row["trigger"]}
                    for row in rows[:_REVIEW_REQUIRED_TRIGGER_LIMIT]]
        evidence = {
            "review_contract_version": 2, "route": "properties",
            "checker_hash": draft.checker_hash,
            "table_kind": "predicted_triggers",
            "expected_table_sha256": _digest(rows),
            "expected_table": [],
            "expected_table_truncated": False,
            "case_summaries": [],
            "predicted_triggers": kept,
            "predicted_triggers_truncated": truncated,
            "predicted_triggers_omitted": omitted,
            "coverage_summary": _properties_coverage(payload),
            "expectation_shape": {},
            "trigger_census": {
                "properties": census["properties"],
                "predicted_triggered": census["predicted_triggered"],
                "unknown": census["unknown"],
                "predicted_empty": census["predicted_empty"],
            },
            "required_claims": [],
            "required_trigger_claims": required,
            "required_trigger_claims_truncated": len(rows) > _REVIEW_REQUIRED_TRIGGER_LIMIT,
            "required_phase_claims": [],
            "required_init_claims": [],
            "required_degenerate_outputs": [],
            "sources": sources,
        }
    evidence["evidence_sha256"] = _digest(evidence)
    return evidence


def parse_checker(text, task, route, *, finish_reason=None):
    """Validate without repairing input; classify syntax failures for the workflow."""
    route, task_hash = _route(route), _task_hash(task)
    try:
        response = _load(text, finish_reason=finish_reason)
        if response.get("status") == "unsupported":
            if set(response) != {"status", "reason"} or not isinstance(response["reason"], str) or not response["reason"].strip():
                raise CheckerError("unsupported needs exactly status and a nonempty reason")
            return CheckerDraft("unsupported", route, response["reason"][:4000], "", task_hash,
                                _preflight_json=_canonical({"claim_independently_confirmed": False}))
        if set(response).intersection({"status", "checker", "reason"}):
            if set(response) != {"status", "checker"} or response.get("status") != "ready" or not isinstance(response.get("checker"), dict):
                raise CheckerError("ready response needs exactly status and a checker object")
            value, response_form = response["checker"], "wrapped"
        else:
            # A bare checker is an explicit alternate grammar, never a repaired wrapper.
            required = {"schema_version", "requirements"} | (
                {"mode", "ports", "outputs", "cases"} if route == "model"
                else {"sampling", "properties"}
            )
            if not required.issubset(response):
                raise CheckerError(f"bare {route} checker needs its complete top-level structure")
            value, response_form = response, "bare_checker"
        # Only audited request-echo/redundant-clock members are removed. Every other
        # extra field still reaches, and fails, the strict schema validator.
        value, normalization = _normalize_checker(
            value, response, response_form, route, text)
        payload, preflight = (_model_preflight if route == "model" else _properties_preflight)(value, task)
        preflight = {**preflight, "response_form": response_form}
        if normalization:
            preflight["normalization"] = normalization
        checker_hash = _digest({"task_hash": task_hash, "route": route, "checker": payload})
        return CheckerDraft("ready", route, "schema and preflight passed; semantic review is still required",
                            checker_hash, task_hash, _canonical(payload), _canonical(preflight))
    except json.JSONDecodeError as error:
        # Only a normally completed, bounded JSON object is eligible. Duplicate keys,
        # non-finite values, truncation and contract failures are not syntax recovery.
        eligible = finish_reason == "stop" and text.lstrip().startswith("{")
        try:
            _format_atoms(text)
        except CheckerError:
            eligible = False
        preflight = {"failure_kind": "json_syntax", "format_correction_eligible": eligible,
                     "response_sha256": hashlib.sha256(text.encode()).hexdigest(),
                     "parser_error": {"message": error.msg, "line": error.lineno,
                                      "column": error.colno, "position": error.pos}}
        return CheckerDraft("invalid", route, _failure_reason(error), "", task_hash,
                            _preflight_json=_canonical(preflight))
    except (ValueError, TypeError, KeyError, RecursionError, OverflowError) as error:
        return CheckerDraft("invalid", route, _failure_reason(error), "", task_hash)


def _format_basis(task, draft, text, finish_reason):
    verified = parse_checker(text, task, draft.route, finish_reason=finish_reason)
    if (verified != draft or not draft.preflight.get("format_correction_eligible")
            or draft.status != "invalid"):
        raise CheckerError("format correction requires the original bound JSON syntax failure")


def _recover_json_punctuation(text):
    """Only close unfinished containers or remove a clearly trailing delimiter.

    Existing container boundaries are never moved. A missing key, value, separator,
    or internal mismatched closer is ambiguous and is not repaired.
    """
    if len(text.encode()) > 524288:
        raise CheckerError("format recovery exceeds the byte limit")
    token = re.compile(r'"(?:[^"\\\x00-\x1f]|\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))*"'
                       r'|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?'
                       r'|true|false|null|[{}\[\],:]')
    tokens, position = [], 0
    while position < len(text):
        if text[position] in " \t\r\n":
            position += 1
            continue
        match = token.match(text, position)
        if match is None:
            raise CheckerError("format recovery cannot identify a complete JSON token")
        tokens.append((match.group(), position))
        position = match.end()
        if len(tokens) > 40000:
            raise CheckerError("format recovery exceeds the token limit")
    edits = []

    def edit(offset, old, new):
        if sum(len(e["old"]) + len(e["new"]) for e in edits) + len(old) + len(new) > 8:
            raise CheckerError("format recovery exceeds 8 punctuation edits")
        edits.append({"offset": offset, "old": old, "new": new})

    def value(index, depth=0):
        if depth > 64 or index >= len(tokens):
            raise CheckerError("format recovery cannot supply a missing value or excessive nesting")
        current = tokens[index][0]
        if current not in ("{", "["):
            if current in ("}", "]", ",", ":"):
                raise CheckerError("format recovery requires an existing JSON value")
            return index + 1
        closer = "}" if current == "{" else "]"
        index += 1
        if index < len(tokens) and tokens[index][0] == closer:
            return index + 1
        while True:
            if current == "{":
                if index >= len(tokens) or not tokens[index][0].startswith('"'):
                    raise CheckerError("format recovery cannot supply a missing object key")
                index += 1
                if index >= len(tokens) or tokens[index][0] != ":":
                    raise CheckerError("format recovery cannot supply a missing colon")
                index += 1
            index = value(index, depth + 1)
            if index == len(tokens):
                edit(len(text), "", closer)
                return index
            if tokens[index][0] == closer:
                return index + 1
            if tokens[index][0] != ",":
                raise CheckerError("format recovery refuses an internal boundary or separator change")
            comma = tokens[index][1]
            index += 1
            if index < len(tokens) and tokens[index][0] == closer:
                edit(comma, ",", "")
                return index + 1

    if not tokens or tokens[0][0] != "{":
        raise CheckerError("format recovery requires a JSON object")
    end = value(0)
    for remaining, offset in tokens[end:]:
        if remaining not in ("}", "]"):
            raise CheckerError("format recovery refuses trailing non-delimiter content")
        edit(offset, remaining, "")
    if not edits:
        raise CheckerError("format recovery found no supported punctuation change")
    # Edits refer to original character offsets. Multiple EOF insertions are in
    # inner-to-outer closing order and must retain that order.
    replacements = {e["offset"]: e for e in edits if e["old"]}
    recovered = "".join(char for offset, char in enumerate(text) if offset not in replacements)
    recovered += "".join(e["new"] for e in edits if not e["old"])
    _load(recovered, finish_reason="stop")  # Duplicate keys/nonfinite values stay invalid.
    return recovered, edits


def recover_checker_format(task, draft, original_text, *, finish_reason):
    """Bounded local punctuation recovery; no model call or semantic substitution."""
    binding = {"attempt": 1, "method": "local_punctuation", "model_calls": 0,
               "original_response_sha256": hashlib.sha256(original_text.encode()).hexdigest()}
    try:
        _format_basis(task, draft, original_text, finish_reason)
        recovered, edits = _recover_json_punctuation(original_text)
        binding.update(edits=edits, response_sha256=hashlib.sha256(recovered.encode()).hexdigest(),
                       keys_and_scalars_preserved=True, existing_container_boundaries_preserved=True)
        corrected = parse_checker(recovered, task, draft.route, finish_reason="stop")
        preflight = {**corrected.preflight, "format_correction_eligible": False,
                     "format_correction": binding}
        return CheckerDraft(corrected.status, corrected.route, corrected.reason,
                            corrected.checker_hash, corrected.task_hash,
                            corrected._payload_json, _canonical(preflight))
    except (ValueError, TypeError, KeyError, RecursionError, OverflowError) as error:
        return CheckerDraft("invalid", draft.route, _failure_reason(error), "", _task_hash(task),
                            _preflight_json=_canonical({"format_correction_eligible": False,
                                                       "format_correction": binding}))


def parse_format_correction(text, task, draft, original_text, *, original_finish_reason, finish_reason=None):
    """Compatibility for saved responses, restricted to the local recovery result.

    New workflow execution uses recover_checker_format directly, without a model.
    Matching scalar streams alone never authorizes a change of container structure.
    """
    recovered = recover_checker_format(task, draft, original_text, finish_reason=original_finish_reason)
    if recovered.status != "ready":
        return recovered
    try:
        expected_text, _ = _recover_json_punctuation(original_text)
        expected = _load(expected_text, finish_reason="stop")
        actual = _load(text, finish_reason=finish_reason)
        if _canonical(actual) != _canonical(expected) or _format_atoms(text) != _format_atoms(original_text):
            raise CheckerError("format correction differs from conservative local recovery")
        return recovered
    except (ValueError, TypeError, KeyError, RecursionError, OverflowError) as error:
        return CheckerDraft("invalid", draft.route, _failure_reason(error), "", _task_hash(task))


def _check_integrity(draft):
    if draft.status != "ready" or not isinstance(draft.payload, dict):
        raise CheckerError("semantic review requires a ready checker draft")
    expected = _digest({"task_hash": draft.task_hash, "route": draft.route, "checker": draft.payload})
    if expected != draft.checker_hash:
        raise CheckerError("checker content no longer matches its construction hash")


def _review_preflight(draft):
    """Omit redundant event tables only from the review message, not the saved draft."""
    summary = draft.preflight  # The property returns an independent JSON copy.
    for key in ("sampling_plan_hash", "response_form", "revision",
                "format_correction", "normalization"):
        summary.pop(key, None)
    expectations = summary.get("expectations")
    if isinstance(expectations, dict):
        for key in ("comparison_events", "suite_hash"):
            expectations.pop(key, None)
    coverage = summary.get("coverage")
    if isinstance(coverage, dict):
        coverage.pop("suite_hash", None)
    return summary


class _ReviewViolation(Exception):
    """One deterministic review-contract failure with its host rule id."""

    def __init__(self, rule, detail):
        super().__init__(f"{rule}: {detail}")
        self.rule = rule
        self.detail = detail


_REVIEW_FIELDS = frozenset({
    "review_contract_version", "checker_hash", "expected_table_sha256", "decision",
    "reason", "checked_requirements", "requirement_reviews", "claims",
    "state_phase_claims", "init_claims", "degenerate_outputs", "counterexamples",
})
_CLAIM_FIELDS = {
    "concat_arity": frozenset({"kind", "path", "value"}),
    "slice": frozenset({"kind", "path", "lsb", "width"}),
    "op": frozenset({"kind", "path", "value"}),
    "width": frozenset({"kind", "path", "value"}),
    "const": frozenset({"kind", "path", "value"}),
    "ref": frozenset({"kind", "path", "value"}),
    "trigger": frozenset({"kind", "property_id", "case_id", "step", "value"}),
}


def _require(condition, rule, detail):
    if not condition:
        raise _ReviewViolation(rule, detail)


def _short(value, limit=160):
    text = _canonical(value)
    return text if len(text) <= limit else text[:limit] + "..."


def _pointer(payload, path):
    _require(isinstance(path, str) and path.startswith("/"), "R-07",
             "claim path must be a JSON pointer")
    node = payload
    for part in path.split("/")[1:]:
        token = part.replace("~1", "/").replace("~0", "~")
        if isinstance(node, list):
            _require(re.fullmatch(r"(?:0|[1-9][0-9]*)", token) is not None, "R-07",
                     "claim path uses a non-index token for a list: " + path)
            _require(int(token) < len(node), "R-07", "claim path does not exist: " + path)
            node = node[int(token)]
        elif isinstance(node, dict):
            _require(token in node, "R-07", "claim path does not exist: " + path)
            node = node[token]
        else:
            raise _ReviewViolation("R-07", "claim path crosses a scalar: " + path)
    return node


def _property_event_steps(payload):
    plan = payload.get("sampling") or {}
    result = {}
    for case in plan.get("cases", []):
        indexes = [index for index, step in enumerate(case.get("steps", []))
                   if not plan.get("clock") or step.get("edge", True)]
        result[case.get("id")] = set(indexes)
    return result


def _host_tables(draft):
    payload = draft.payload
    if draft.route == "model":
        suite, rows = _model_suite_rows(payload)
        table = _model_expected_rows(suite, rows)
        return {
            "route": "model", "suite": suite, "rows": rows, "table": table,
            "keyed": {(row["case_id"], row["step"]): row for row in table},
            "table_sha256": _digest(table), "trigger_rows": {},
        }
    census = analyze_property_trigger_census(payload)
    rows = census["rows"]
    return {
        "route": "properties", "suite": None, "rows": rows, "table": rows,
        "keyed": {}, "table_sha256": _digest(rows),
        "trigger_rows": {(row["property_id"], row["case_id"], row["step"]): row["trigger"]
                         for row in rows},
    }


def _witness_model(witness, requirement_id, payload, keyed):
    _require(isinstance(witness, dict) and set(witness) == {"case_id", "steps"},
             "R-06", "model witness needs exactly case_id and steps")
    case_id = witness["case_id"]
    cases = {case["id"]: case for case in payload["cases"]}
    _require(isinstance(case_id, str) and case_id in cases, "R-06",
             "unknown witness case " + _short(case_id))
    _require(requirement_id in cases[case_id].get("requirements", []), "R-06",
             f"case {case_id} does not bind requirement {requirement_id}")
    steps = witness["steps"]
    _require(isinstance(steps, list) and steps, "R-06", "witness needs sampled steps")
    for item in steps:
        _require(isinstance(item, dict) and set(item) == {"step", "outputs"}, "R-06",
                 "each witness step needs exactly step and outputs")
        step, outputs = item["step"], item["outputs"]
        _require(type(step) is int, "R-06", "witness step must be an integer index")
        row = keyed.get((case_id, step))
        _require(row is not None, "R-06",
                 f"case {case_id} step {step} is not a sampled comparable event")
        _require(isinstance(outputs, dict) and outputs, "R-06",
                 "witness step needs at least one named output")
        for name, claimed in outputs.items():
            _require(name in row["expected"], "R-06",
                     f"output {name} is not compared at case {case_id} step {step}")
            host = row["expected"][name]
            if isinstance(host, int):
                _require(type(claimed) is int and claimed == host, "R-06",
                         f"case {case_id} step {step} output {name}: claimed "
                         f"{_short(claimed)} but host predicts {host}")
            else:
                _require(claimed is None or (isinstance(claimed, str)
                                             and claimed.lower() == "unknown"), "R-06",
                         f"case {case_id} step {step} output {name}: "
                         "host predicts unknown")


def _witness_properties(witness, requirement_id, payload, trigger_rows):
    _require(isinstance(witness, dict)
             and set(witness) == {"case_id", "property_id", "steps"}, "R-06",
             "properties witness needs exactly case_id, property_id and steps")
    case_id, property_id = witness["case_id"], witness["property_id"]
    cases = {case["id"]: case for case in payload["sampling"]["cases"]}
    properties = {prop["id"]: prop for prop in payload["properties"]}
    _require(isinstance(case_id, str) and case_id in cases, "R-06",
             "unknown witness case " + _short(case_id))
    _require(isinstance(property_id, str) and property_id in properties, "R-06",
             "unknown witness property " + _short(property_id))
    prop = properties[property_id]
    bound = set(prop.get("requirements", [])) | set(prop.get("abort_requirements", []))
    _require(requirement_id in bound, "R-06",
             f"property {property_id} does not bind requirement {requirement_id}")
    events = _property_event_steps(payload).get(case_id, set())
    steps = witness["steps"]
    _require(isinstance(steps, list) and steps, "R-06", "witness needs sampled steps")
    for item in steps:
        _require(isinstance(item, dict) and set(item) == {"step", "outputs"}, "R-06",
                 "each witness step needs exactly step and outputs")
        step, outputs = item["step"], item["outputs"]
        _require(type(step) is int and step in events, "R-06",
                 f"case {case_id} step {step} is not a sampled event")
        _require(isinstance(outputs, dict) and set(outputs) == {"trigger"}, "R-06",
                 "properties witness outputs must be exactly trigger")
        claimed = outputs["trigger"]
        _require(type(claimed) is bool, "R-06", "trigger witness must be a boolean")
        host = trigger_rows.get((property_id, case_id, step))
        if host is not None:
            _require(claimed == host, "R-06",
                     f"{property_id} {case_id} step {step}: claimed trigger {claimed} "
                     f"but host predicts {host}")


def _check_claims(claims, draft):
    payload = draft.payload
    route = draft.route
    _require(isinstance(claims, list), "R-07", "claims must be a list")
    declared, trigger_declared = set(), {}
    cases = {case["id"]: case for case in
             ((payload.get("sampling") or {}).get("cases") or [])}
    properties = {prop["id"]: prop for prop in payload.get("properties", [])}
    events = _property_event_steps(payload) if route == "properties" else {}
    for claim in claims:
        _require(isinstance(claim, dict) and isinstance(claim.get("kind"), str),
                 "R-07", "each claim needs a string kind")
        kind = claim["kind"]
        _require(kind in _CLAIM_FIELDS, "R-07", f"unknown claim kind {_short(kind)}")
        _require(set(claim) == _CLAIM_FIELDS[kind], "R-07",
                 f"claim {kind} needs exactly " + ", ".join(sorted(_CLAIM_FIELDS[kind])))
        if kind == "trigger":
            property_id, case_id, step = (claim["property_id"], claim["case_id"],
                                          claim["step"])
            _require(route == "properties", "R-07",
                     "trigger claims belong to the properties route only")
            _require(type(claim["value"]) is bool, "R-07",
                     "trigger claim value must be a boolean")
            _require(isinstance(property_id, str) and property_id in properties, "R-07",
                     "trigger claim names an unknown property")
            _require(isinstance(case_id, str) and case_id in cases, "R-07",
                     "trigger claim names an unknown case")
            _require(type(step) is int and step in events.get(case_id, set()), "R-07",
                     "trigger claim names a non-sampled step")
            key = (property_id, case_id, step)
            _require(key not in trigger_declared, "R-07",
                     f"duplicate trigger claim {_short(key)}")
            trigger_declared[key] = claim["value"]
            continue
        identity = (kind, claim["path"])
        _require(identity not in declared, "R-07", f"duplicate claim {_short(identity)}")
        declared.add(identity)
        node = _pointer(payload, claim["path"])
        _require(isinstance(node, dict), "R-07",
                 "claim path is not an expression object: " + _short(claim["path"]))
        value = claim.get("value")
        if kind == "concat_arity":
            _require(node.get("op") == "concat" and type(value) is int
                     and len(node.get("args", [])) == value, "R-07",
                     f"concat arity at {claim['path']} is {len(node.get('args', []))}, "
                     f"not {_short(value)}")
        elif kind == "slice":
            _require(node.get("op") == "slice" and node.get("lsb") == claim["lsb"]
                     and node.get("width") == claim["width"], "R-07",
                     f"slice at {claim['path']} is lsb={node.get('lsb')} "
                     f"width={node.get('width')}")
        elif kind == "op":
            _require(node.get("op") == value, "R-07",
                     f"op at {claim['path']} is {_short(node.get('op'))}, not {_short(value)}")
        elif kind == "width":
            _require(node.get("width") == value, "R-07",
                     f"width at {claim['path']} is {_short(node.get('width'))}")
        elif kind == "const":
            _require("const" in node and node["const"] == value, "R-07",
                     f"const at {claim['path']} is {_short(node.get('const'))}")
        elif kind == "ref":
            _require("ref" in node and node["ref"] == value, "R-07",
                     f"ref at {claim['path']} is {_short(node.get('ref'))}")
    return declared, trigger_declared


def _check_phase_claims(declared, payload):
    required = {(item["used_in"], item["register"], item["phase"])
                for item in _required_phase_claims(payload)}
    _require(isinstance(declared, list), "R-08", "state_phase_claims must be a list")
    seen = set()
    for item in declared:
        _require(isinstance(item, dict) and set(item) == {"used_in", "register", "phase"},
                 "R-08", "each phase claim needs exactly used_in, register and phase")
        _require(item["used_in"] in ("outputs", "state.next"), "R-08",
                 "phase claim used_in must be outputs or state.next")
        _require(isinstance(item["register"], str), "R-08",
                 "phase claim register must be a name")
        _require(item["phase"] in ("NEW", "OLD"), "R-08",
                 "phase claim must be NEW or OLD")
        identity = (item["used_in"], item["register"], item["phase"])
        _require(identity not in seen, "R-08",
                 f"duplicate phase claim {_short(identity)}")
        seen.add(identity)
    if seen != required:
        _require(False, "R-08", "phase claims must equal the host set " + _short(sorted(required)))


def _check_init_claims(declared, payload):
    allowed = _init_allowed_sources(payload)
    _require(isinstance(declared, list), "R-09", "init_claims must be a list")
    seen = {}
    for item in declared:
        _require(isinstance(item, dict) and set(item) == {"register", "source"}, "R-09",
                 "each init claim needs exactly register and source")
        register, source = item["register"], item["source"]
        _require(isinstance(register, str), "R-09", "init claim register must be a name")
        _require(source in ("initial", "reset", "unconstrained"), "R-09",
                 "init claim source must be initial, reset or unconstrained")
        _require(register not in seen, "R-09", f"register {register} declared twice")
        seen[register] = source
    _require(set(seen) == set(allowed), "R-09",
             "init claims must cover every state register " + _short(sorted(allowed)))
    for register, source in seen.items():
        _require(source in allowed[register], "R-09",
                 f"{register}: source {source} is not allowed; host allows "
                 + _short(allowed[register]))


def _check_degenerate(declared, tables):
    if tables["route"] == "model":
        host = set(_degenerate_outputs(tables["suite"], tables["rows"]))
    else:
        host = set()
    _require(isinstance(declared, list), "R-10", "degenerate_outputs must be a list")
    seen = set()
    for item in declared:
        _require(isinstance(item, dict) and set(item) == {"output"}, "R-10",
                 "each degenerate output needs exactly the output name")
        _require(isinstance(item["output"], str), "R-10",
                 "degenerate output name must be a string")
        _require(item["output"] not in seen, "R-10",
                 f"degenerate output {item['output']} declared twice")
        seen.add(item["output"])
    if seen != host:
        _require(False, "R-10", "degenerate outputs must equal the host set " + _short(sorted(host)))


def _required_trigger_claims(rows):
    return [{"property_id": row["property_id"], "case_id": row["case_id"],
             "step": row["step"], "value": row["trigger"]}
            for row in rows[:_REVIEW_REQUIRED_TRIGGER_LIMIT]]


def _check_review_contract(review, draft, tables):
    payload, route = draft.payload, draft.route
    missing = sorted(_REVIEW_FIELDS - set(review))
    extra = sorted(set(review) - _REVIEW_FIELDS)
    _require(not missing, "R-01", "review is missing required fields: " + ", ".join(missing))
    _require(not extra, "R-01", "review contains unexpected fields: " + ", ".join(extra))
    _require(type(review["review_contract_version"]) is int
             and review["review_contract_version"] == 2, "R-01",
             "review_contract_version must be the integer 2")
    decision = review["decision"]
    _require(decision in ("accept", "reject", "unknown"), "R-02",
             "decision must be accept, reject or unknown")
    _require(isinstance(review["reason"], str) and review["reason"].strip(), "R-02",
             "reason must be nonempty text")
    _require(review["checker_hash"] == draft.checker_hash, "R-03",
             "checker_hash must echo the frozen checker hash")
    _require(review["expected_table_sha256"] == tables["table_sha256"], "R-03",
             "expected_table_sha256 must echo the host table hash")
    requirements = [item["id"] for item in payload["requirements"]]
    checked = review["checked_requirements"]
    _require(isinstance(checked, list) and all(isinstance(item, str) for item in checked),
             "R-04", "checked_requirements must be a list of requirement IDs")
    _require(len(checked) == len(set(checked)), "R-04",
             "checked_requirements must not repeat an ID")
    _require(set(checked).issubset(requirements), "R-04",
             "checked_requirements names an unknown requirement ID")
    if decision == "accept":
        _require(set(checked) == set(requirements), "R-04",
                 "accepted review must cover every declared requirement")
    reviews = review["requirement_reviews"]
    _require(isinstance(reviews, list), "R-05", "requirement_reviews must be a list")
    seen, contradicted = set(), 0
    for item in reviews:
        _require(isinstance(item, dict), "R-05", "requirement review must be an object")
        _require({"requirement_id", "verdict"}.issubset(item)
                 and set(item).issubset({"requirement_id", "verdict", "witness"}), "R-05",
                 "requirement review needs requirement_id and verdict, with an optional witness")
        identity, verdict = item["requirement_id"], item["verdict"]
        _require(isinstance(identity, str) and identity in requirements, "R-05",
                 f"unknown requirement id {_short(identity)}")
        _require(identity not in seen, "R-05", f"requirement {identity} reviewed twice")
        seen.add(identity)
        _require(verdict in ("supported", "contradicted", "insufficient"), "R-05",
                 f"unknown verdict {_short(verdict)} for {identity}")
        if verdict in ("contradicted", "insufficient"):
            contradicted += 1
        witness = item.get("witness")
        if verdict == "supported":
            _require(witness is not None, "R-06",
                     f"supported requirement {identity} needs a witness")
        if witness is not None:
            if route == "model":
                _witness_model(witness, identity, payload, tables["keyed"])
            else:
                _witness_properties(witness, identity, payload, tables["trigger_rows"])
    if decision == "accept":
        _require(contradicted == 0, "R-05",
                 "accepted review cannot include contradicted or insufficient requirements")
        _require(seen == set(requirements), "R-05",
                 "accepted review must review every requirement as supported")
    if decision == "reject":
        _require(contradicted > 0, "R-05",
                 "a rejecting review needs a contradicted or insufficient requirement")
    declared, trigger_declared = _check_claims(review["claims"], draft)
    if route == "model":
        required = {(item["kind"], item["path"])
                    for item in _required_expression_claims(payload)}
        absent = sorted(required - declared)
        _require(not absent, "R-07b",
                 "claims miss host-required expression facts: "
                 + ", ".join(f"{kind} {path}" for kind, path in absent[:8]))
    _check_phase_claims(review["state_phase_claims"], payload)
    _check_init_claims(review["init_claims"], payload)
    _check_degenerate(review["degenerate_outputs"], tables)
    counterexamples = review["counterexamples"]
    _require(isinstance(counterexamples, list), "R-02", "counterexamples must be a list")
    for item in counterexamples:
        _require(isinstance(item, dict) and item, "R-02",
                 "each counterexample must be a nonempty object")
    if counterexamples:
        _require(decision == "reject", "R-11",
                 "a declared counterexample requires decision reject")
    if route == "properties":
        required_triggers = _required_trigger_claims(tables["rows"])
        for item in required_triggers:
            key = (item["property_id"], item["case_id"], item["step"])
            _require(key in trigger_declared, "R-12",
                     f"missing required trigger claim for {_short(key)}")
            _require(trigger_declared[key] == item["value"], "R-12",
                     f"trigger claim {_short(key)} says {_short(trigger_declared[key])}, "
                     f"host predicts {_short(item['value'])}")


def review_request(task, draft, *, violations=None):
    _check_integrity(draft)
    if _task_hash(task) != draft.task_hash:
        raise CheckerError("review task differs from checker construction task")
    evidence = build_review_evidence(draft)
    content = {
        "task": public_context(task),
        "route": draft.route, "checker_hash": draft.checker_hash,
        "checker": draft.payload, "preflight": _review_preflight(draft),
        "review_contract_version": 2,
        "expected_table_sha256": evidence["expected_table_sha256"],
        "review_evidence": evidence,
    }
    if violations:
        # A retry names only host rule IDs, field paths and expected values.
        content["contract_violations"] = [str(item)[:500] for item in violations]
    return [
        {"role": "system", "content": _instruction("adaptive_review.j2")},
        {"role": "user", "content": _canonical(content)},
    ]


def approve_review(text, draft, *, finish_reason=None):
    """Freeze exactly the reviewed content under the v2 host contract."""
    status, reason, review, violations, retryable = "invalid", "", {}, [], True
    record = {"review_contract_version": 2, "decision": None, "status": "invalid",
              "retryable": True, "violations": [], "reason": "",
              "checker_hash": "", "expected_table_sha256": "",
              "review_evidence_sha256": "", "response_sha256": ""}
    try:
        _check_integrity(draft)
        record["checker_hash"] = draft.checker_hash
        try:
            review = _load(text, finish_reason=finish_reason, max_bytes=131072)
        except (ValueError, TypeError, KeyError, RecursionError, OverflowError) as error:
            raise _ReviewViolation(
                "R-00", "review response is not one bounded strict JSON object: "
                + _failure_reason(error)) from error
        evidence = build_review_evidence(draft)
        tables = _host_tables(draft)
        record["expected_table_sha256"] = tables["table_sha256"]
        record["review_evidence_sha256"] = evidence["evidence_sha256"]
        _check_review_contract(review, draft, tables)
        status = {"accept": "approved", "reject": "rejected",
                  "unknown": "unknown"}[review["decision"]]
        reason = review["reason"][:4000]
        retryable = False
    except _ReviewViolation as error:
        violations = [f"{error.rule}: {error.detail}"[:1000]]
        reason = violations[0][:4000]
        decision = review.get("decision") if isinstance(review, dict) else None
        retryable = decision not in ("reject", "unknown")
    except (ValueError, TypeError, KeyError, RecursionError, OverflowError) as error:
        reason = _failure_reason(error)
        violations = ["R-00: " + reason[:1000]]
        decision = review.get("decision") if isinstance(review, dict) else None
        retryable = decision not in ("reject", "unknown")
    record.update(
        decision=review.get("decision") if isinstance(review, dict) else None,
        status=status, retryable=retryable, violations=violations, reason=reason,
        checker_hash=draft.checker_hash if draft.status == "ready" else "",
        response_sha256=_sha_text(text) if isinstance(text, str) else "")
    return FrozenChecker(status, draft.route, reason, draft.checker_hash, draft.task_hash,
                         draft._payload_json, draft._preflight_json, _canonical(review),
                         retryable, _canonical(violations), _canonical(record))


def _revision_basis(task, draft, rejected):
    _check_integrity(draft)
    _route(draft.route)
    if _task_hash(task) != draft.task_hash:
        raise CheckerError("revision task differs from original checker task")
    if "revision" in draft.preflight or "format_correction" in draft.preflight:
        raise CheckerError("checker recovery is limited to one format correction or semantic revision")
    if not isinstance(rejected, FrozenChecker) or rejected.status != "rejected":
        raise CheckerError("checker revision requires a valid formal rejection")
    if (rejected.route != draft.route or rejected.task_hash != draft.task_hash
            or rejected.checker_hash != draft.checker_hash or rejected.payload != draft.payload
            or rejected.preflight != draft.preflight):
        raise CheckerError("rejection does not bind to the original checker and task")
    # Recompute the host evidence from the draft and re-run the v2 validator; the
    # rejected review must be a legal formal rejection for this exact checker.
    verified = approve_review(_canonical(rejected.review), draft)

    def identity(record):
        result = dict(record)
        result.pop("response_sha256", None)  # Re-encoding changes the canonical text hash.
        return result

    if (verified.status != "rejected" or verified.violations
            or verified.review != rejected.review
            or identity(verified.review_record) != identity(rejected.review_record)):
        raise CheckerError("checker revision requires an intact v2 formal rejection")
    return rejected.review


def revision_request(task, draft, rejected):
    """Request one complete revision, using public inputs and a bound rejection only."""
    review = _revision_basis(task, draft, rejected)
    # Reuse the full original route/DSL instructions, including unknown and timing rules.
    messages = checker_request(task, draft.route)
    messages[0]["content"] += "\n\n" + _instruction("adaptive_checker_revision.j2")
    content = json.loads(messages[1]["content"])
    content.update(checker_hash=draft.checker_hash, checker=draft.payload,
                   rejected_review=review)
    messages[1]["content"] = _canonical(content)
    return messages


def _revision_sampling(payload, route):
    if route == "properties":
        return payload["sampling"]
    from agent.domain.rtl.observation import sampling_plan_from_suite

    return sampling_plan_from_suite(payload)


def _preserve_revision_scope(original, revised, route):
    if original["requirements"] != revised["requirements"]:
        raise CheckerError("revision must retain every original requirement ID and citation in order")
    old_plan = _revision_sampling(original, route)
    new_plan = _revision_sampling(revised, route)
    if (old_plan["ports"] != new_plan["ports"] or old_plan["clock"] != new_plan["clock"]
            or new_plan["cases"][:len(old_plan["cases"])] != old_plan["cases"]):
        raise CheckerError("revision must preserve original sampling; new cases may only be appended")
    if route == "properties":
        revised_properties = {item["id"]: item for item in revised["properties"]}
        for prop in original["properties"]:
            current = revised_properties.get(prop["id"])
            if current is None or any(not set(prop[key]).issubset(current[key])
                                      for key in ("requirements", "abort_requirements")):
                raise CheckerError("revision must preserve original property IDs and requirement bindings")


def _revision_comparison(payload, route):
    # Fill schema defaults only for no-op detection. Stored payloads and their
    # construction/review hashes retain the exact validated representation.
    if route == "model":
        return SuiteModel.model_validate(payload).model_dump(mode="json")
    from agent.domain.rtl.properties import PropertySuite

    normalized = PropertySuite.model_validate(payload).model_dump(mode="json")
    normalized["properties"].sort(key=lambda prop: prop["id"])
    for prop in normalized["properties"]:
        for key in ("requirements", "abort_requirements"):
            prop[key].sort()
    return normalized


def parse_checker_revision(text, task, draft, rejected, *, finish_reason=None):
    """Strictly preflight a changed checker; only a fresh review can authorize its use."""
    try:
        review = _revision_basis(task, draft, rejected)
        revised = parse_checker(text, task, draft.route, finish_reason=finish_reason)
        if revised.status != "ready":
            return revised
        original_payload, revised_payload = draft.payload, revised.payload
        _preserve_revision_scope(original_payload, revised_payload, draft.route)
        if (_revision_comparison(original_payload, draft.route)
                == _revision_comparison(revised_payload, draft.route)):
            raise CheckerError("checker revision made no substantive contract change")
        preflight = {**revised.preflight, "revision": {
            "attempt": 1, "parent_checker_hash": draft.checker_hash,
            "rejected_review_hash": _digest(review),
        }}
        return CheckerDraft("ready", revised.route,
                            "revised checker passed preflight; a new independent review is required",
                            revised.checker_hash, revised.task_hash,
                            revised._payload_json, _canonical(preflight))
    except (ValueError, TypeError, KeyError, RecursionError, OverflowError) as error:
        return CheckerDraft("invalid", draft.route, _failure_reason(error), "", _task_hash(task))
