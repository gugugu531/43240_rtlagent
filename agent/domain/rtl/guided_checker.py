"""Flat key-case checker for guided_verify; host owns the Verilog testbench."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import re

from .guided_context import public_context
from .observation import SamplingPlan, validate_trace
from .suite.semantics import SuiteError

# Read the sampling schema's bound rather than maintain a second port limit.
MAX_PORTS = next(
    bound.max_length for bound in SamplingPlan.model_fields["ports"].metadata
    if hasattr(bound, "max_length")
)
CASE_ID = re.compile(r"^[A-Za-z0-9_-]{1,63}$")
CLOCK_NAME = re.compile(r"(?i)(?:^|_)(?:clk|clock)$|^(?:clk|clock)")
EDGE = re.compile(
    r"(?i)\b(?P<hdl>posedge|negedge)\b|"
    r"\b(?P<english>rising|positive|falling|negative)[\s-]+"
    r"(?:(?:clock|clk)[\s-]+)?edges?\b"
)


class CheckerError(ValueError):
    pass


@dataclass(frozen=True)
class CheckerCase:
    id: str
    init_count: int
    checked_outputs: tuple[str, ...]
    unchecked_outputs: tuple[str, ...]
    expected: dict[int, dict[str, int]] = field(default_factory=dict)

    def public_dict(self):
        return {
            "id": self.id,
            "init_count": self.init_count,
            "checked_outputs": list(self.checked_outputs),
            "unchecked_outputs": list(self.unchecked_outputs),
            "expected": {str(k): v for k, v in self.expected.items()},
        }


@dataclass(frozen=True)
class TableChecker:
    plan: dict
    cases: tuple[CheckerCase, ...]
    checked_outputs: tuple[str, ...]
    unchecked_outputs: tuple[str, ...]

    def public_dict(self):
        return {
            "schema_version": 1,
            "plan": self.plan,
            "cases": [case.public_dict() for case in self.cases],
            "checked_outputs": list(self.checked_outputs),
            "unchecked_outputs": list(self.unchecked_outputs),
        }


def checker_request(task, skill_body, focus=(), *, max_cases=4, max_steps=8, init_cycles=2):
    user = (
        "Public task and resolved interface:\n"
        + json.dumps(public_context(task), ensure_ascii=False, separators=(",", ":"))
        + "\n\nHost execution contract (authoritative mechanics, not functional requirements):\n"
        + json.dumps(checker_contract(task, max_cases=max_cases, max_steps=max_steps,
                                      init_cycles=init_cycles), ensure_ascii=False,
                     separators=(",", ":"))
        + "\n\nSelected focus (untrusted hints, not requirements):\n"
        + "\n".join("- " + item for item in focus)
        + "\n\nReturn only the line table described by the skill. "
        "For a sequential case the first line must be init. "
        "Every non-clock input must appear on every line. "
        "Use hexadecimal values without width prefixes. "
        "Do not write Verilog, comments, Markdown or prose."
    )
    return [
        {"role": "system", "content": skill_body},
        {"role": "user", "content": user},
    ]


def _ports(task):
    interface = task.expected_interface
    if not interface.parsed or not interface.complete or not interface.ports:
        raise CheckerError("public interface is not complete")
    if len(interface.ports) > MAX_PORTS:
        raise CheckerError(f"public port count exceeds sampling limit of {MAX_PORTS}")
    ports = {}
    for port in interface.ports:
        if port.width is None or not 1 <= port.width <= 256:
            raise CheckerError("public port width is outside checker limits")
        if port.direction not in ("input", "output"):
            raise CheckerError("unsupported port direction")
        ports[port.name] = {"direction": port.direction, "width": port.width}
    inputs = [name for name, p in ports.items() if p["direction"] == "input"]
    outputs = [name for name, p in ports.items() if p["direction"] == "output"]
    if not outputs:
        raise CheckerError("checker needs at least one output")
    clocks = [
        name for name in inputs
        if ports[name]["width"] == 1 and CLOCK_NAME.search(name)
    ]
    if len(clocks) > 1:
        raise CheckerError("multiple clock candidates are not supported")
    clock = clocks[0] if clocks else None
    public_text = task.prompt + "\n" + task.interface
    if clock:
        _clock_edge(public_text, clock, inputs)
    elif EDGE.search(public_text):
        raise CheckerError("edge-triggered task has no supported clock input")
    return ports, inputs, outputs, clock


def _clock_edge(text, clock, inputs):
    """Bind each edge phrase locally; reset edges never erase clock edges.

    This is deliberately a conservative recognizer, not a language interpreter.
    An unspecified or unbound edge cannot prove a positive-edge clock.
    """
    aliases = {name.lower(): name for name in inputs}
    aliases.update({"clock": clock, "clk": clock})
    positive = False
    for match in EDGE.finditer(text):
        before, after = text[:match.start()], text[match.end():]
        subject = None
        if match.group("hdl"):
            target = re.match(r"\s+([A-Za-z_][A-Za-z0-9_$]*)\b", after)
            if target:
                subject = aliases.get(target.group(1).lower())
        else:
            # e.g. "falling edge of reset_n", "rising edge on clk".
            target = re.match(
                r"\s+(?:of|on)\s+(?:the\s+)?(?:signal\s+)?"
                r"([A-Za-z_][A-Za-z0-9_$]*)\b", after, re.I,
            )
            if target:
                subject = aliases.get(target.group(1).lower())
            else:
                # Bind only a local input/clock name, optionally followed by a
                # copula: "clk's rising edge", "areset is positive edge".
                # Do not skip arbitrary words such as "not" or data names.
                target = re.search(
                    r"\b([A-Za-z_][A-Za-z0-9_$]*)(?:['’]s)?"
                    r"(?:\s+(?:is|are))?\s+$", before, re.I,
                )
                if target:
                    subject = aliases.get(target.group(1).lower())
                if subject is None and re.search(r"\b(?:clock|clk)\b", match.group(), re.I):
                    subject = clock
                # A generic edge-triggered declaration explicitly tied to clock.
                if subject is None and re.match(r"[\s-]+triggered\s+(?:by\s+)?(?:the\s+)?(?:clock|clk)\b", after, re.I):
                    subject = clock
        if subject is None:
            raise CheckerError("clock edge semantics are ambiguous or unsupported")
        if subject != clock:
            if not re.search(r"(?i)(?:^|_)(?:reset|rst)(?:_|$)|^a?(?:reset|rst)", subject):
                raise CheckerError("non-reset edge-triggered inputs are not supported")
            continue
        polarity = (match.group("hdl") or match.group("english")).lower()
        if polarity in ("negedge", "falling", "negative"):
            raise CheckerError("falling-edge checking is not supported")
        positive = True
    if not positive:
        raise CheckerError("positive clock edge is not specified unambiguously")
    return "posedge"


def _limits(max_cases, max_steps, init_cycles, clock):
    if any(type(value) is not int or value < 1 for value in (max_cases, max_steps, init_cycles)):
        raise CheckerError("checker limits must be positive integers")
    event_limit = 32 if clock else 256
    if clock and init_cycles > event_limit:
        raise CheckerError("init_cycles exceeds sequential event limit")
    return min(max_cases, 8), min(max_steps, event_limit), event_limit


def checker_contract(task, *, max_cases=4, max_steps=8, init_cycles=2):
    """Return JSON-only mechanics from public input; never inspect a candidate."""
    result = {
        "schema_version": 1,
        "supported": False,
        "reason": "",
        "configured_limits": {"max_cases": max_cases, "max_steps": max_steps,
                              "init_cycles": init_cycles},
    }
    try:
        ports, inputs, outputs, clock = _ports(task)
        cases, lines, events = _limits(max_cases, max_steps, init_cycles, clock)
    except CheckerError as error:
        result["reason"] = str(error)
        return result
    result.update({
        "supported": True,
        "ports": ports,
        "clock": {"port": clock, "edge": "posedge"} if clock else None,
        "limits": {"max_ports": MAX_PORTS, "max_cases": cases, "max_table_lines_per_case": lines,
                   "max_expanded_events_per_case": events, "max_total_expanded_events": 256,
                   "max_table_characters": 16384},
        "table": {
            "all_non_clock_inputs_required": [name for name in inputs if name != clock],
            "outputs": outputs,
            "checked_outputs": "At least one output on each line; the same output set throughout a case. Omitted outputs remain unchecked.",
            "value_encoding": "Unsigned hexadecimal bit patterns, no width prefix or 0x; fit the declared width. Signed values use their exact width's two's-complement bits. X/Z, negative literals and overflow are rejected.",
            "first_line": "init" if clock else "init or step",
            "line_count": "Both init and step lines count toward max_table_lines_per_case.",
        },
        "execution": {
            "case_isolation": "Each case uses a separate DUT instance; no state is shared. No automatic reset or internal state initialization is performed.",
            "initial_clock": 0 if clock else None,
            "init_repeats": init_cycles if clock else 1,
            "init_semantics": "Every init line repeats its input values for init_repeats events; compare its expected outputs only after its final repetition. Init is not an automatic reset: drive reset explicitly if required by the public specification.",
            "step_semantics": "Each step line produces one event and one expected-output comparison.",
            "event_timing_ns": {"drive_inputs": 5, "record_pre": 9,
                                "active_clock_edge": 10 if clock else None,
                                "record_post_and_compare": 11,
                                "return_clock_inactive": 15 if clock else None,
                                "event_period": 15},
            "sampling": "Compare post samples only, after input settling and (for sequential cases) the positive clock edge and nonblocking updates. Pre samples are diagnostic only.",
            "failure_step_index": "Zero-based index of the expanded event in that case, not the table line number. A first init of N repeats is checked at step N-1; the next step is N.",
            "failure_value_encoding": "Expanded sampling inputs, expected_bits, actual_bits and known masks are JSON integer bit patterns (decimal JSON numbers), unlike hexadecimal table tokens.",
            "unknown_outputs": "Unknown output bits remain unknown and cannot pass a comparison.",
            "coverage": "A pass covers only the listed input/state sequences and sampled outputs. Output-port coverage alone does not establish input-space, transition, priority or full-period coverage; obey the event limits when selecting distinguishable cases.",
        },
    })
    return result


def _value(token, width, *, name):
    if not re.fullmatch(r"[0-9a-fA-F]+", token):
        raise CheckerError(f"value for {name} must be hexadecimal")
    value = int(token, 16)
    if not 0 <= value < (1 << width):
        raise CheckerError(f"value for {name} exceeds width")
    return value


def parse_checker(text, task, *, max_cases=4, max_steps=8, init_cycles=2):
    text = text.strip()
    if text.startswith("```") and text.endswith("```"):
        text = "\n".join(text.splitlines()[1:-1]).strip()
    if not text or len(text) > 16384:
        raise CheckerError("checker output missing or too large")
    ports, inputs, outputs, clock = _ports(task)
    max_cases, max_steps, _ = _limits(max_cases, max_steps, init_cycles, clock)
    non_clock = [name for name in inputs if name != clock]
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        raise CheckerError("checker table is empty")
    cases = []
    plan_cases = []
    current = None
    for line in lines:
        if line.startswith("case "):
            if current is not None:
                cases.append(current)
                plan_cases.append(current.pop("_plan"))
            case_id = line[5:].strip()
            if not CASE_ID.fullmatch(case_id):
                raise CheckerError("invalid case id")
            if any(case["id"] == case_id for case in cases):
                raise CheckerError("duplicate case id")
            current = {
                "id": case_id, "lines": [], "checked": None,
                "_plan": {"id": case_id, "steps": []},
            }
            continue
        if current is None:
            raise CheckerError("checker line outside a case")
        kind, _, rest = line.partition(" ")
        if kind not in ("init", "step"):
            raise CheckerError("checker line must start with init or step")
        tokens = rest.split()
        values = {}
        for token in tokens:
            if "=" not in token:
                raise CheckerError("checker token must be name=value")
            name, value = token.split("=", 1)
            if name in values:
                raise CheckerError("duplicate checker token")
            if name in ports:
                if ports[name]["direction"] == "output":
                    values[name] = _value(value, ports[name]["width"], name=name)
                else:
                    values[name] = _value(value, ports[name]["width"], name=name)
            else:
                raise CheckerError("unknown checker port: " + name)
        driven = {name for name in values if ports[name]["direction"] == "input"}
        if driven != set(non_clock):
            raise CheckerError("every non-clock input must be driven on every line")
        checked = tuple(sorted(name for name in values if ports[name]["direction"] == "output"))
        if not checked:
            raise CheckerError("each line must check at least one output")
        if current["checked"] is None:
            current["checked"] = checked
        elif current["checked"] != checked:
            raise CheckerError("checked output set changed inside a case")
        current["lines"].append((kind, values))
    if current is not None:
        cases.append(current)
        plan_cases.append(current.pop("_plan"))
    if not cases or len(cases) > max_cases:
        raise CheckerError("case count outside configured limit")
    result_cases = []
    for raw, plan_case in zip(cases, plan_cases):
        if not raw["lines"]:
            raise CheckerError("case has no lines: " + raw["id"])
        kinds = [kind for kind, _ in raw["lines"]]
        if clock and kinds[0] != "init":
            raise CheckerError("sequential case must start with init")
        if len(kinds) > max_steps:
            raise CheckerError("case exceeds configured step limit")
        expected = {}
        init_count = init_cycles if clock else 1
        step_index = 0
        for kind, values in raw["lines"]:
            inputs_only = {
                name: value for name, value in values.items()
                if ports[name]["direction"] == "input"
            }
            expected_values = {
                name: value for name, value in values.items()
                if ports[name]["direction"] == "output"
            }
            repeats = init_count if kind == "init" else 1
            for _ in range(repeats):
                plan_case["steps"].append({
                    "inputs": inputs_only, "sample": True,
                    "edge": bool(clock),
                })
                step_index += 1
            # Compare the init outputs after the final init edge even when
            # step lines follow; otherwise the init line would be decorative.
            expected[step_index - 1] = expected_values
        checked = tuple(raw["checked"] or ())
        result_cases.append(CheckerCase(
            id=raw["id"], init_count=init_count,
            checked_outputs=checked,
            unchecked_outputs=tuple(name for name in outputs if name not in checked),
            expected=expected,
        ))
    checked_union = tuple(sorted({name for case in result_cases for name in case.checked_outputs}))
    # A single case that omits a public output is enough to make the checker
    # partial; do not let another case's coverage erase that fact.
    unchecked_union = tuple(
        name for name in outputs
        if any(name in case.unchecked_outputs for case in result_cases)
    )
    plan = {
        "schema_version": 1,
        "ports": ports,
        "clock": {"port": clock, "edge": "posedge"} if clock else None,
        "cases": plan_cases,
    }
    try:
        plan = SamplingPlan.model_validate(plan).model_dump(mode="json")
    except Exception as error:
        raise CheckerError("invalid sampling plan: " + str(error)) from error
    return TableChecker(plan, tuple(result_cases), checked_union, unchecked_union)


def evaluate_checker(checker, trace):
    try:
        validate_trace(trace, checker.plan)
    except SuiteError as error:
        return {
            "status": "invalid",
            "failure_kind": "checker",
            "summary": str(error),
            "checked_outputs": list(checker.checked_outputs),
            "unchecked_outputs": list(checker.unchecked_outputs),
            "failed": [], "compared_bits": 0,
        }
    rows = {
        (row["case_index"], row["step"]): row
        for row in trace.rows if row["phase"] == "post"
    }
    failed, unknown, compared = [], [], 0
    for ci, case in enumerate(checker.cases):
        for step, expected in sorted(case.expected.items()):
            row = rows.get((ci, step))
            if row is None:
                unknown.append({"case_id": case.id, "step": step, "reason": "missing_row"})
                continue
            for name, expected_bits in sorted(expected.items()):
                value = row["values"][name]
                width = checker.plan["ports"][name]["width"]
                full = (1 << width) - 1
                if value["known"] != full:
                    unknown.append({
                        "case_id": case.id, "step": step, "signal": name,
                        "expected_bits": expected_bits, "actual_bits": value["bits"],
                        "known": value["known"], "width": width,
                    })
                    continue
                compared += width
                if value["bits"] != expected_bits:
                    failed.append({
                        "case_id": case.id, "step": step, "signal": name,
                        "expected_bits": expected_bits, "actual_bits": value["bits"],
                        "known": full, "width": width,
                    })
    if failed:
        status = "failed"
    elif unknown:
        status = "unknown"
    elif checker.unchecked_outputs:
        status = "partial_passed"
    else:
        status = "passed"
    return {
        "status": status,
        "failure_kind": "unknown",
        "summary": f"{len(failed)} mismatches, {len(unknown)} unknown, {compared} compared bits",
        "checked_outputs": list(checker.checked_outputs),
        "unchecked_outputs": list(checker.unchecked_outputs),
        "failed": failed,
        "unknown": unknown,
        "compared_bits": compared,
    }
