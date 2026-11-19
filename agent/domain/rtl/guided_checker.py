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
MAX_NOTE_CHARACTERS = 240
MAX_TABLE_CHARACTERS = 16384
CLOCK_NAME = re.compile(r"(?i)(?:^|_)(?:clk|clock)$|^(?:clk|clock)")
EDGE = re.compile(
    r"(?i)\b(?P<hdl>posedge|negedge)\b|"
    r"\b(?P<english>rising|positive|falling|negative)[\s-]+"
    r"(?:(?:clock|clk)[\s-]+)?edges?\b"
)
PUBLIC_DOCUMENT = re.compile(r"<!--[ \t]+Public specification:[ \t]+[^<>]+?[ \t]+-->")
ADAPTATION_HEADING = "## Single-file Vivado evaluation adaptation"


class CheckerError(ValueError):
    pass


@dataclass(frozen=True)
class CheckerCase:
    id: str
    init_count: int
    checked_outputs: tuple[str, ...]
    unchecked_outputs: tuple[str, ...]
    expected: dict[int, dict[str, int]] = field(default_factory=dict)
    pre_expected: dict[int, dict[str, int]] = field(default_factory=dict)
    explanation: str | None = None

    def expectations(self):
        """Yield (expanded step, phase, outputs) for each explicit comparison."""
        for step in sorted(self.expected.keys() | self.pre_expected.keys()):
            if step in self.pre_expected:
                yield step, "pre", self.pre_expected[step]
            if step in self.expected:
                yield step, "post", self.expected[step]

    def public_dict(self):
        result = {
            "id": self.id,
            "init_count": self.init_count,
            "checked_outputs": list(self.checked_outputs),
            "unchecked_outputs": list(self.unchecked_outputs),
            "expected": {str(k): v for k, v in self.expected.items()},
            "pre_expected": {str(k): v for k, v in self.pre_expected.items()},
        }
        if self.explanation is not None:
            result["explanation"] = self.explanation
        return result


@dataclass(frozen=True)
class TableChecker:
    plan: dict
    cases: tuple[CheckerCase, ...]
    checked_outputs: tuple[str, ...]
    unchecked_outputs: tuple[str, ...]

    def public_dict(self):
        return {
            # Retain the exact content identity of previously saved tables.
            "schema_version": 3 if any(case.explanation is not None for case in self.cases) else 2,
            "plan": self.plan,
            "cases": [case.public_dict() for case in self.cases],
            "checked_outputs": list(self.checked_outputs),
            "unchecked_outputs": list(self.unchecked_outputs),
        }


def checker_public_prompt(task, *, max_cases, max_steps, init_cycles):
    return (
        "Public task and resolved interface:\n"
        + json.dumps(public_context(task), ensure_ascii=False, separators=(",", ":"))
        + "\n\nHost execution contract (authoritative mechanics, not functional requirements):\n"
        + json.dumps(checker_contract(task, max_cases=max_cases, max_steps=max_steps,
                                      init_cycles=init_cycles), ensure_ascii=False,
                     separators=(",", ":"))
    )


def checker_request(task, skill_body, focus=(), *, max_cases=4, max_steps=8, init_cycles=2):
    if focus:
        raise CheckerError("independent checker construction accepts no external focus text")
    user = (
        checker_public_prompt(task, max_cases=max_cases, max_steps=max_steps, init_cycles=init_cycles)
        + "\n\nReturn the line table described by the skill. "
        "Start each test point with case <id> # <one short explanation of the stimulus and expected behavior>. "
        "For a sequential case the first stimulus line must be init. "
        "Every non-clock input must appear on every stimulus line. "
        "Use hexadecimal values without width prefixes. "
        "Return only the explained case headers and their stimulus lines."
    )
    return [
        {"role": "system", "content": skill_body},
        {"role": "user", "content": user},
    ]


def _top_clock_text(text):
    """Keep the preamble, first marked public document, and final adaptation."""
    lines = text.splitlines(keepends=True)
    kept = []
    seen_document = in_dependency = False
    fence = ""
    for index, line in enumerate(lines):
        # Four leading spaces or a tab can be a Markdown code block.
        label = line.rstrip()
        if not label.startswith("    "):
            label = label.lstrip(" ")
        if fence:
            if label.startswith(fence) and not label.strip(fence[0]):
                fence = ""
        elif opening := re.match(r"^(`{3,}|~{3,})", label):
            fence = opening[1]
        elif seen_document and label == ADAPTATION_HEADING:
            return "".join(kept + lines[index:])
        elif PUBLIC_DOCUMENT.fullmatch(label):
            in_dependency = seen_document
            seen_document = True
            continue
        if not in_dependency:
            kept.append(line)
    return "".join(kept)


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
    public_text = _top_clock_text(task.prompt) + "\n" + _top_clock_text(task.interface)
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
                # copula and article: "clk's rising edge",
                # "areset is a positive edge".
                # Do not skip arbitrary words such as "not" or data names.
                target = re.search(
                    r"\b([A-Za-z_][A-Za-z0-9_$]*)(?:['’]s)?"
                    r"(?:\s+(?:is|are)(?:\s+(?:a|an|the))?)?\s+$", before, re.I,
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
        "schema_version": 3,
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
                   "max_table_characters": MAX_TABLE_CHARACTERS,
                   "max_explanation_characters": MAX_NOTE_CHARACTERS},
        "table": {
            "case_header": "case <unique_id> # <one short explanation of the stimulus and expected behavior>",
            "all_non_clock_inputs_required": [name for name in inputs if name != clock],
            "outputs": outputs,
            "checked_outputs": "At least one output expectation per line. Use the same output names throughout a case, counting either phase. For each output, write name=value to compare its post sample and omit unspecified phases.",
            "pre_outputs": "On a clocked line use pre.<output>=value when the output is specified after input drive but before the active edge. A line may select pre, post or both for each output. Combinational lines accept only unqualified outputs.",
            "value_encoding": "Unsigned hexadecimal bit patterns, no width prefix or 0x; fit the declared width. Signed values use their exact width's two's-complement bits. X/Z, negative literals and overflow are rejected.",
            "first_line": "init" if clock else "init or step",
            "line_count": "Both init and step lines count toward max_table_lines_per_case.",
        },
        "execution": {
            "case_isolation": "Each case uses a separate DUT instance; no state is shared. No automatic reset or internal state initialization is performed.",
            "initial_clock": 0 if clock else None,
            "init_repeats": init_cycles if clock else 1,
            "init_semantics": "Each init repeats its inputs for init_repeats events. Compare explicit pre outputs before the first edge of the first repetition, and unqualified outputs after the last repetition. Drive any public reset explicitly.",
            "step_semantics": "Each step produces one event. Compare any explicit pre outputs before its edge and unqualified outputs at its post sample.",
            "event_timing_ns": {"drive_inputs": 5, "record_pre": 9,
                                "active_clock_edge": 10 if clock else None,
                                "record_post": 11,
                                "return_clock_inactive": 15 if clock else None,
                                "event_period": 15},
            "sampling": "Pre is recorded after inputs settle at 9 ns and compared only for explicit pre.<output> expectations. Post is recorded at 11 ns, after settling and any positive clock edge and nonblocking updates. Count known compared bits separately for each phase.",
            "failure_step_index": "Zero-based index of the expanded event in the case, with phase pre or post. A first init of N repeats compares explicit pre values at step 0 and post values at step N-1. The next step is N.",
            "failure_value_encoding": "Expanded sampling inputs, expected_bits, actual_bits and known masks are JSON integer bit patterns (decimal JSON numbers), unlike hexadecimal table tokens.",
            "unknown_outputs": "Unknown output bits remain unknown. Compare the known bits of each output and report any mismatch even if other bits are unknown. Any unresolved bits without a known mismatch yield an unknown verdict.",
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


def case_blocks(text):
    """Split a table at case headers, retaining each block's text and line number."""
    if not isinstance(text, str) or not text.strip():
        raise CheckerError("checker table is empty")
    text = text.strip()
    lines = text.splitlines()
    if lines[0].startswith("```"):
        if len(lines) < 2 or lines[-1].strip() != "```" or not re.fullmatch(r"```[\w-]*", lines[0].strip()):
            raise CheckerError("malformed enclosing code fence")
        text = "\n".join(lines[1:-1]).strip()
    if len(text) > MAX_TABLE_CHARACTERS:
        raise CheckerError(f"checker table exceeds {MAX_TABLE_CHARACTERS} characters")
    blocks = []
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if line.split(maxsplit=1)[:1] == ["case"]:
            blocks.append((number, []))
        elif not blocks:
            raise CheckerError(f"line {number}: expected a case header")
        blocks[-1][1].append(raw)
    if not blocks:
        raise CheckerError("checker table is empty")
    return [(number, "\n".join(lines)) for number, lines in blocks]


def short_note(raw, label):
    note = raw.strip()
    if not note or len(note) > MAX_NOTE_CHARACTERS or not note.isprintable():
        raise CheckerError(f"{label} must contain 1..{MAX_NOTE_CHARACTERS} printable characters on one line")
    return note


def _stimulus(line, ports, clock, non_clock):
    kind, *tokens = line.split()
    if kind not in ("init", "step"):
        raise CheckerError(f"expected init or step, found {kind!r}")
    driven, post, pre = {}, {}, {}
    for token in tokens:
        if "=" not in token:
            raise CheckerError(f"expected name=value, found {token!r}")
        key, value = token.split("=", 1)
        is_pre = key.startswith("pre.")
        name = key.removeprefix("pre.")
        if name not in ports:
            raise CheckerError("unknown checker port: " + key)
        if is_pre:
            if not clock or ports[name]["direction"] != "output":
                raise CheckerError("pre expectations require a clocked public output: " + key)
            target = pre
        else:
            target = post if ports[name]["direction"] == "output" else driven
        if name in target:
            raise CheckerError("duplicate checker token: " + key)
        target[name] = _value(value, ports[name]["width"], name=key)
    if driven.keys() != non_clock:
        raise CheckerError("every non-clock input must be driven on every line; "
                           f"missing={sorted(non_clock - driven.keys())}, extra={sorted(driven.keys() - non_clock)}")
    if not post and not pre:
        raise CheckerError("each line must check at least one output")
    return kind, driven, post, pre


def parse_checker(text, task, *, max_cases=4, max_steps=8, init_cycles=2, require_explanations=False):
    """Pass require_explanations=True for every live construction or correction."""
    blocks = case_blocks(text)
    ports, inputs, outputs, clock = _ports(task)
    max_cases, max_steps, max_events = _limits(max_cases, max_steps, init_cycles, clock)
    if len(blocks) > max_cases:
        raise CheckerError(f"line {blocks[max_cases][0]}: case count exceeds limit of {max_cases}")
    non_clock = set(inputs) - {clock}
    init_count = init_cycles if clock else 1
    result_cases, plan_cases, ids = [], [], set()
    total_events = 0
    for number, block in blocks:
        first, *rows = block.splitlines()
        header, separator, note = first.strip().partition("#")
        fields = header.split()
        if len(fields) != 2 or not CASE_ID.fullmatch(fields[1]):
            raise CheckerError(f"line {number}: invalid case id in {header.strip()!r}")
        case_id = fields[1]
        if case_id in ids:
            raise CheckerError(f"line {number}: duplicate case id {case_id}")
        ids.add(case_id)
        explanation = None
        if separator or require_explanations:
            explanation = short_note(note, f"line {number}, case {case_id}: explanation after #")
        checked, steps = (), []
        expected, pre_expected = {}, {}
        line_count = 0
        for line_number, line in enumerate(rows, number + 1):
            if not line.strip():
                continue
            line_count += 1
            where = f"line {line_number}, case {case_id}"
            if line_count > max_steps:
                raise CheckerError(f"{where}: case exceeds configured step limit of {max_steps}")
            try:
                kind, driven, post, pre = _stimulus(line, ports, clock, non_clock)
            except CheckerError as error:
                raise CheckerError(f"{where}: {error}") from error
            if not steps and clock and kind != "init":
                raise CheckerError(f"{where}: sequential case must start with init")
            names = tuple(sorted(post.keys() | pre.keys()))
            if checked and checked != names:
                raise CheckerError(f"{where}: checked output set changed from {list(checked)} to {list(names)}")
            checked = names
            if pre:
                pre_expected[len(steps)] = pre
            repeats = init_count if kind == "init" else 1
            total_events += repeats
            if len(steps) + repeats > max_events or total_events > 256:
                raise CheckerError(f"{where}: expanded event limit exceeded ({max_events} per case, 256 total)")
            for _ in range(repeats):
                steps.append({"inputs": driven, "sample": True, "edge": bool(clock)})
            if post:
                expected[len(steps) - 1] = post
        if not steps:
            raise CheckerError(f"line {number}: case has no lines: {case_id}")
        plan_cases.append({"id": case_id, "steps": steps})
        result_cases.append(CheckerCase(
            id=case_id, init_count=init_count, explanation=explanation,
            checked_outputs=checked,
            unchecked_outputs=tuple(name for name in outputs if name not in checked),
            expected=expected, pre_expected=pre_expected,
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


def _comparison_status(failed, unknown, compared, unchecked_outputs):
    if failed:
        return "failed"
    if unknown or not compared:
        return "unknown"
    return "partial_passed" if unchecked_outputs else "passed"


def evaluate_checker(checker, trace):
    compared_by_phase = {"pre": 0, "post": 0}
    unknown_by_phase = {"pre": 0, "post": 0}
    try:
        validate_trace(trace, checker.plan)
    except SuiteError as error:
        return {
            "status": "invalid",
            "failure_kind": "checker",
            "summary": str(error),
            "checked_outputs": list(checker.checked_outputs),
            "unchecked_outputs": list(checker.unchecked_outputs),
            "case_results": [], "failed": [], "unknown": [], "compared_bits": 0, "unknown_bits": 0,
            "compared_bits_by_phase": compared_by_phase,
            "unknown_bits_by_phase": unknown_by_phase,
        }
    rows = {
        (row["case_index"], row["step"], row["phase"]): row for row in trace.rows
    }
    failed, unknown, case_results = [], [], []
    for ci, case in enumerate(checker.cases):
        case_compared = {"pre": 0, "post": 0}
        case_unknown = {"pre": 0, "post": 0}
        failed_before, unknown_before = len(failed), len(unknown)
        for step, phase, expected in case.expectations():
            row = rows.get((ci, step, phase))
            if row is None:
                unknown.append({"case_id": case.id, "step": step, "phase": phase, "reason": "missing_row"})
                continue
            for name, expected_bits in sorted(expected.items()):
                value = row["values"][name]
                known = value["known"]
                unknown_mask = ((1 << value["width"]) - 1) ^ known
                mismatch = (value["bits"] ^ expected_bits) & known
                case_compared[phase] += known.bit_count()
                case_unknown[phase] += unknown_mask.bit_count()
                if mismatch or unknown_mask:
                    detail = {
                        "case_id": case.id, "step": step, "phase": phase, "signal": name,
                        "expected_bits": expected_bits, "actual_bits": value["bits"],
                        "known": known, "width": value["width"],
                    }
                    if mismatch:
                        failed.append({**detail, "mismatch_mask": mismatch})
                    if unknown_mask:
                        unknown.append({**detail, "unknown_mask": unknown_mask})
        mismatches = len(failed) - failed_before
        case_results.append({
            "case_id": case.id, "explanation": case.explanation,
            "status": _comparison_status(mismatches, len(unknown) - unknown_before,
                                         sum(case_compared.values()), case.unchecked_outputs),
            "checked_outputs": list(case.checked_outputs), "unchecked_outputs": list(case.unchecked_outputs),
            "compared_bits": sum(case_compared.values()), "unknown_bits": sum(case_unknown.values()),
            "compared_bits_by_phase": case_compared, "unknown_bits_by_phase": case_unknown,
            "mismatches": mismatches,
        })
        for phase in compared_by_phase:
            compared_by_phase[phase] += case_compared[phase]
            unknown_by_phase[phase] += case_unknown[phase]
    compared = sum(compared_by_phase.values())
    unknown_bits = sum(unknown_by_phase.values())
    return {
        "status": _comparison_status(failed, unknown, compared, checker.unchecked_outputs),
        "failure_kind": "unknown",
        "summary": f"{len(failed)} mismatches, {unknown_bits} unknown bits, {compared} compared bits",
        "checked_outputs": list(checker.checked_outputs),
        "unchecked_outputs": list(checker.unchecked_outputs),
        "case_results": case_results,
        "failed": failed,
        "unknown": unknown,
        "compared_bits": compared,
        "unknown_bits": unknown_bits,
        "compared_bits_by_phase": compared_by_phase,
        "unknown_bits_by_phase": unknown_by_phase,
    }
