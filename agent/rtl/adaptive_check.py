"""One-shot, public-task-only checker contracts; no model calls or candidate access."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import itertools
import json
from pathlib import Path
import re

from agent.llm.structured import strict_json
from agent.rtl.specification import source_catalog
from agent.rtl.suite.schema import SuiteModel, validate_suite
from agent.rtl.suite.semantics import _validate_expr
from agent.rtl.suite.evaluate import (
    require_comparable_expectations,
    require_requirement_coverage,
)


class CheckerError(ValueError):
    pass


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value):
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


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
            pending.extend(node.values())
        elif isinstance(node, list):
            pending.extend(node)
    return value


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

    @property
    def repair_authorized(self):
        return self.status == "approved"

    @property
    def review(self):
        return json.loads(self._review_json)

    def public_dict(self):
        return {**super().public_dict(), "review": self.review,
                "repair_authorized": self.repair_authorized}


def _instruction(name):
    return (Path(__file__).parent.parent / "prompts" / name).read_text(encoding="utf-8")


def checker_request(task, route):
    """Build messages using only explicit public TaskSpec fields and DSL capabilities."""
    _route(route)
    if route == "model":
        schema = SuiteModel.model_json_schema()
    else:
        from agent.rtl.properties import PropertySuite

        schema = PropertySuite.model_json_schema()
    text = task.prompt + "\n" + task.interface
    return [
        {"role": "system", "content": _instruction("adaptive_checker.j2")},
        {"role": "user", "content": _canonical({
            "task": _public_task(task), "route": route,
            "source_catalog": source_catalog(text), "checker_schema": schema,
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
    from agent.rtl.observation import sampling_plan_from_suite, sampling_hash

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
        "sampling_plan_hash": sampling_hash(sampling),
        "actual_comparisons": 0, "semantic_truth_proven": False,
    }


def _async_preflight(value, task_text):
    """Require an off-edge reset observation when the public text explicitly requires it."""
    pattern = (
        r"\basync(?:hronous(?:ly)?)?\b(?:[\s-]+(?:active|low|high|level|sensitive))*"
        r"[\s-]+(?:reset|clear)(?:s|ting|ing)?\b|"
        r"\b(?:reset|clear)(?:[\s-]+(?:is|must|be|shall|an|a|signal|input|active|low|high|and))*"
        r"[\s-]+async(?:hronous(?:ly)?)?\b|异步(?:的|低电平|高电平|有效|\s)*(?:复位|清零)|"
        r"(?:复位|清零)(?:为|是|采用|使用|\s)*异步"
    )
    if not re.search(pattern, task_text, re.I):
        return
    resets = value.get("async_resets") or ([value["async_reset"]] if value.get("async_reset") else [])
    if not resets or not any(re.search(pattern, r["quote"], re.I) for r in value["requirements"]):
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
    from agent.rtl.properties import validate_properties

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
    return value, {
        "kind": "property_contract_validation", "properties": len(value["properties"]),
        "actual_triggers": 0, "actual_comparisons": 0, "semantic_truth_proven": False,
    }


def parse_checker(text, task, route, *, finish_reason=None):
    """Validate once. A failure is a structural fallback, never a correction request."""
    route, task_hash = _route(route), _task_hash(task)
    try:
        response = _load(text, finish_reason=finish_reason)
        if response.get("status") == "unsupported":
            if set(response) != {"status", "reason"} or not isinstance(response["reason"], str) or not response["reason"].strip():
                raise CheckerError("unsupported needs exactly status and a nonempty reason")
            return CheckerDraft("unsupported", route, response["reason"][:4000], "", task_hash,
                                _preflight_json=_canonical({"claim_independently_confirmed": False}))
        if set(response) != {"status", "checker"} or response.get("status") != "ready" or not isinstance(response.get("checker"), dict):
            raise CheckerError("ready response needs exactly status and a checker object")
        payload, preflight = (_model_preflight if route == "model" else _properties_preflight)(response["checker"], task)
        checker_hash = _digest({"task_hash": task_hash, "route": route, "checker": payload})
        return CheckerDraft("ready", route, "schema and preflight passed; semantic review is still required",
                            checker_hash, task_hash, _canonical(payload), _canonical(preflight))
    except (ValueError, TypeError, KeyError, RecursionError, OverflowError) as error:
        return CheckerDraft("invalid", route, str(error)[:4000], "", task_hash)


def _check_integrity(draft):
    if draft.status != "ready" or not isinstance(draft.payload, dict):
        raise CheckerError("semantic review requires a ready checker draft")
    expected = _digest({"task_hash": draft.task_hash, "route": draft.route, "checker": draft.payload})
    if expected != draft.checker_hash:
        raise CheckerError("checker content no longer matches its construction hash")


def review_request(task, draft):
    _check_integrity(draft)
    if _task_hash(task) != draft.task_hash:
        raise CheckerError("review task differs from checker construction task")
    return [
        {"role": "system", "content": _instruction("adaptive_review.j2")},
        {"role": "user", "content": _canonical({
            "task": _public_task(task), "source_catalog": source_catalog(task.prompt + "\n" + task.interface),
            "route": draft.route, "checker_hash": draft.checker_hash,
            "checker": draft.payload, "preflight": draft.preflight,
        })},
    ]


def approve_review(text, draft, *, finish_reason=None):
    """Freeze exactly the reviewed content; rejection never authorizes RTL repair."""
    status, reason, review = "invalid", "", {}
    try:
        _check_integrity(draft)
        review = _load(text, finish_reason=finish_reason, max_bytes=131072)
        if set(review) != {"checker_hash", "decision", "reason", "checked_requirements"}:
            raise CheckerError("review needs exactly checker_hash, decision, reason and checked_requirements")
        if review["checker_hash"] != draft.checker_hash:
            raise CheckerError("semantic review checker_hash differs from frozen draft")
        if review["decision"] not in ("accept", "reject", "unknown"):
            raise CheckerError("semantic review decision must be accept, reject or unknown")
        if not isinstance(review["reason"], str) or not review["reason"].strip():
            raise CheckerError("semantic review needs an explanatory reason")
        checked = review["checked_requirements"]
        expected = {item["id"] for item in draft.payload["requirements"]}
        if (not isinstance(checked, list) or any(not isinstance(item, str) for item in checked)
                or len(checked) != len(set(checked)) or not set(checked).issubset(expected)):
            raise CheckerError("review checked_requirements must uniquely name existing requirement IDs")
        if review["decision"] == "accept" and set(checked) != expected:
            raise CheckerError("accepted review must explicitly cover every declared requirement")
        status = {"accept": "approved", "reject": "rejected", "unknown": "unknown"}[review["decision"]]
        reason = review["reason"][:4000]
    except (ValueError, TypeError, KeyError, RecursionError, OverflowError) as error:
        reason = str(error)[:4000]
    return FrozenChecker(status, draft.route, reason, draft.checker_hash, draft.task_hash,
                         draft._payload_json, draft._preflight_json, _canonical(review))
