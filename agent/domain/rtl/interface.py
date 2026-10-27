"""Structured parsing and comparison of RTL module interfaces."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable, Literal


InterfaceSource = Literal["interface_file", "prompt_list", "generated_code", "unknown"]
Confidence = Literal["high", "medium", "low", "none"]
CheckStatus = Literal["ok", "mismatch", "advisory", "skipped", "parse_error"]


@dataclass(frozen=True)
class PortSpec:
    name: str
    direction: str
    width: int | None
    range_text: str | None = None

    def public_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "direction": self.direction,
            "width": self.width,
            "range": self.range_text,
        }


@dataclass(frozen=True)
class InterfaceSpec:
    module_name: str | None
    ports: tuple[PortSpec, ...]
    source: InterfaceSource
    confidence: Confidence
    warnings: tuple[str, ...] = ()
    complete: bool = True

    @property
    def parsed(self) -> bool:
        return self.module_name is not None and self.confidence in ("high", "medium")

    def public_dict(self) -> dict[str, object]:
        return {
            "module_name": self.module_name,
            "ports": [port.public_dict() for port in self.ports],
            "source": self.source,
            "confidence": self.confidence,
            "warnings": list(self.warnings),
            "complete": self.complete,
        }


@dataclass(frozen=True)
class InterfaceDifference:
    kind: str
    message: str
    port_name: str | None = None
    expected: object = None
    actual: object = None

    def public_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "port_name": self.port_name,
            "expected": self.expected,
            "actual": self.actual,
            "message": self.message,
        }


@dataclass(frozen=True)
class InterfaceCheckResult:
    status: CheckStatus
    blocking: bool
    expected: InterfaceSpec
    actual: InterfaceSpec
    differences: tuple[InterfaceDifference, ...]
    summary: str

    @property
    def rc(self) -> int:
        return 1 if self.blocking else 0

    @property
    def parse_error_scope(self) -> str | None:
        if self.status != "parse_error":
            return None
        # An unreadable explicit contract takes precedence when both sides fail.
        # Candidate parser limitations are not proof of invalid RTL: a caller may
        # obtain compiler diagnostics without treating this result as a pass.
        if self.expected.source == "interface_file" and (
            not self.expected.parsed or not self.expected.complete
        ):
            return "public"
        if any(item.kind == "actual_parse" for item in self.differences):
            return "candidate"
        return "public"

    def trace_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "blocking": self.blocking,
            "rc": self.rc,
            "expected_source": self.expected.source,
            "expected_confidence": self.expected.confidence,
            "expected_complete": self.expected.complete,
            "actual_confidence": self.actual.confidence,
            "actual_complete": self.actual.complete,
            "expected_module": self.expected.module_name,
            "actual_module": self.actual.module_name,
            "parse_error_scope": self.parse_error_scope,
            "differences": [item.public_dict() for item in self.differences],
            "warnings": list(self.expected.warnings + self.actual.warnings),
            "excerpt": self.summary[:500],
        }


_IDENTIFIER_RE = re.compile(r"^[A-Za-z_]\w*$")
_MODULE_RE = re.compile(r"\bmodule\s+([A-Za-z_]\w*)")
_DIRECTION_RE = re.compile(r"\b(input|output|inout)\b")
_PROMPT_PORT_LINE_RE = re.compile(r"^\s*-\s*(input|output|inout)\b(.*)$")
_PROMPT_BULLET_RE = re.compile(r"^\s*-\s*\S")
_PROMPT_PORT_BODY_RE = re.compile(
    r"^\s*(?:(?:wire|reg|logic|bit|var|signed|unsigned|tri)\s+)*"
    r"(?:\[\s*([^\]]+)\s*\]\s*)?"
    r"(?:(?:wire|reg|logic|bit|var|signed|unsigned|tri)\s+)*"
    r"([A-Za-z_]\w*)\s*,?\s*"
    r"(?:\(\s*([A-Za-z_]\w*|\d+)\s*(?:bits?|位)\s*\))?\s*$"
)
_DECLARATION_RE = re.compile(r"\b(input|output|inout)\b(.*?);", re.DOTALL)
_TYPE_WORDS_RE = re.compile(
    r"\b(?:wire|reg|logic|bit|var|signed|unsigned|tri|supply0|supply1)\b"
)


def parse_expected_interface(
    interface: str, prompt: str = "", *, top: str | None = None
) -> InterfaceSpec:
    """Use an interface file, or conservative public prompt declarations."""
    if interface and interface.strip():
        return parse_module_interface(interface, source="interface_file", top=top)
    from agent.domain.rtl.public_interface import supplement_public_interface

    return supplement_public_interface(
        prompt, parse_prompt_interface(prompt, top=top), top=top
    )


def parse_prompt_interface(prompt: str, *, top: str | None = None) -> InterfaceSpec:
    """Parse a prose port list without treating bugfix source as a specification."""
    text = prompt or ""
    ports: list[PortSpec] = []
    warnings: list[str] = []
    complete = True
    in_port_list = False
    for line in text.splitlines():
        match = _PROMPT_PORT_LINE_RE.fullmatch(line)
        if match is None:
            if in_port_list and _PROMPT_BULLET_RE.match(line):
                complete = False
                warnings.append(f"unrecognized prompt port bullet: {line.strip()!r}")
            elif line.strip():
                in_port_list = False
            continue
        in_port_list = True
        direction, body = match.groups()
        port_match = _PROMPT_PORT_BODY_RE.fullmatch(body)
        if port_match is None:
            complete = False
            warnings.append(f"could not parse prompt port line: {line.strip()!r}")
            continue
        range_text, name, bits = port_match.groups()
        width: int | None = 1
        if range_text is not None:
            range_text = range_text.strip()
            width, _, width_warning = _parse_width(f"[{range_text}]")
            if width_warning:
                warnings.append(width_warning)
        if bits is not None:
            if range_text is not None:
                complete = False
                warnings.append(f"prompt port {name!r} has both range and bit count")
                continue
            width = int(bits) if bits.isdigit() else None
            if width is None:
                range_text = bits
                warnings.append(f"could not resolve prompt width ({bits} bits)")
        ports.append(PortSpec(name, direction, width, range_text))
    if not ports:
        if _MODULE_RE.search(_mask_comments(text)):
            warnings.append(
                "embedded module text was not treated as an interface specification"
            )
        else:
            warnings.append("no prompt port list found")
        return InterfaceSpec(None, (), "prompt_list", "none", tuple(warnings), False)

    name_match = re.search(r"\bmodule\s+named\s+([A-Za-z_]\w*)", text)
    if top:
        module_name = top
    elif name_match:
        module_name = name_match.group(1)
    else:
        module_name = "TopModule"
        warnings.append("module name not stated; defaulted to TopModule")
    duplicate_warnings = _duplicate_port_warnings(ports)
    if duplicate_warnings:
        complete = False
    warnings.extend(duplicate_warnings)
    return InterfaceSpec(
        module_name,
        tuple(ports),
        "prompt_list",
        "medium",
        tuple(warnings),
        complete,
    )


def parse_module_interface(
    text: str, *, source: InterfaceSource = "generated_code", top: str | None = None
) -> InterfaceSpec:
    """Parse ANSI or classic non-ANSI Verilog module declarations."""
    raw = text or ""
    cleaned = _mask_comments(raw)
    module_match = next(
        (
            match
            for match in _MODULE_RE.finditer(cleaned)
            if top is None or match.group(1) == top
        ),
        None,
    )
    if module_match is None:
        message = f"module {top!r} not found" if top else "no module declaration found"
        return InterfaceSpec(None, (), source, "none", (message,), False)

    module_name = module_match.group(1)
    warnings: list[str] = []
    cursor = _skip_space(cleaned, module_match.end())
    if cursor < len(cleaned) and cleaned[cursor] == "#":
        cursor = _skip_space(cleaned, cursor + 1)
        if cursor >= len(cleaned) or cleaned[cursor] != "(":
            return InterfaceSpec(
                module_name,
                (),
                source,
                "low",
                ("malformed parameter list in module declaration",),
                False,
            )
        parameter_end = _balanced_end(cleaned, cursor)
        if parameter_end is None:
            return InterfaceSpec(
                module_name,
                (),
                source,
                "low",
                ("unterminated parameter list in module declaration",),
                False,
            )
        cursor = _skip_space(cleaned, parameter_end + 1)

    if cursor >= len(cleaned) or cleaned[cursor] != "(":
        semicolon = cleaned.find(";", cursor)
        if semicolon < 0:
            return InterfaceSpec(
                module_name,
                (),
                source,
                "low",
                ("module declaration has no port list or semicolon",),
                False,
            )
        return InterfaceSpec(module_name, (), source, "high", ())

    port_end = _balanced_end(cleaned, cursor)
    if port_end is None:
        return InterfaceSpec(
            module_name,
            (),
            source,
            "low",
            ("unterminated module port list",),
            False,
        )
    header = cleaned[cursor + 1 : port_end]
    body = cleaned[port_end + 1 :]
    endmodule = re.search(r"\bendmodule\b", body)
    if endmodule is not None:
        body = body[: endmodule.start()]
    items = _split_commas(header)
    ansi = any(_DIRECTION_RE.search(item) for item in items)
    if ansi:
        ports, parse_warnings = _parse_ansi_ports(items)
    else:
        ports, parse_warnings = _parse_non_ansi_ports(items, body)
    warnings.extend(parse_warnings)
    warnings.extend(_duplicate_port_warnings(ports))
    confidence: Confidence = "high" if not warnings else "medium"
    complete = not any(
        warning.startswith(
            (
                "port declaration has no direction",
                "could not parse port name",
                "port '",
                "duplicate port",
            )
        )
        for warning in warnings
    )
    return InterfaceSpec(
        module_name, tuple(ports), source, confidence, tuple(warnings), complete
    )


def check_interface_result(
    source: str, interface: str, prompt: str = "", *, top: str | None = None
) -> InterfaceCheckResult:
    """Compare generated RTL with the authoritative or advisory expectation."""
    expected = parse_expected_interface(interface, prompt, top=top)
    actual = parse_module_interface(
        source, source="generated_code", top=top or expected.module_name
    )

    if top and not actual.parsed:
        summary = "; ".join(actual.warnings) or f"module {top!r} not found"
        difference = InterfaceDifference("actual_parse", summary)
        return InterfaceCheckResult(
            "parse_error", True, expected, actual, (difference,), summary
        )

    # A missing specification prevents comparison, but does not make an invalid
    # candidate declaration usable. Diagnose only explicit parser evidence here;
    # unresolved parameter widths and unsupported interface types stay advisory.
    missing_directions = tuple(
        InterfaceDifference(
            "missing_direction",
            f"port {port.name!r} has no input, output or inout declaration",
            port.name,
            actual="unknown",
        )
        for port in actual.ports
        if port.direction == "unknown"
        and f"port {port.name!r} has no direction declaration" in actual.warnings
    )
    if missing_directions:
        summary = "invalid candidate interface: " + "; ".join(
            item.message for item in missing_directions
        )
        return InterfaceCheckResult(
            "mismatch", True, expected, actual, missing_directions, summary
        )

    if not expected.parsed:
        if interface and interface.strip():
            summary = "interface.txt is present but its module declaration could not be parsed"
            return InterfaceCheckResult(
                "parse_error", True, expected, actual, (), summary
            )
        summary = "No interface declaration was supplied and no port list could be parsed from the task; interface checking is skipped"
        return InterfaceCheckResult("skipped", False, expected, actual, (), summary)

    if expected.source == "interface_file" and not expected.complete:
        summary = "interface.txt port declaration could not be parsed completely"
        return InterfaceCheckResult("parse_error", True, expected, actual, (), summary)

    if not actual.parsed:
        summary = (
            "; ".join(actual.warnings)
            or "no module declaration found in the generated code"
        )
        difference = InterfaceDifference("actual_parse", summary)
        return InterfaceCheckResult(
            "parse_error", True, expected, actual, (difference,), summary
        )

    differences = _compare_interfaces(expected, actual)
    if not differences:
        summary = (
            "interface matches the port list read from the prompt"
            if expected.source == "prompt_list"
            else "interface matches the declaration"
        )
        return InterfaceCheckResult("ok", False, expected, actual, (), summary)

    detail = "; ".join(item.message for item in differences)
    if expected.source == "prompt_list":
        summary = "Port list differs from the task (prose-derived interface; advisory only, not blocking): " + detail
        return InterfaceCheckResult(
            "advisory", False, expected, actual, differences, summary
        )
    summary = "interface mismatch: " + detail
    return InterfaceCheckResult(
        "mismatch", True, expected, actual, differences, summary
    )


def _compare_interfaces(
    expected: InterfaceSpec, actual: InterfaceSpec
) -> tuple[InterfaceDifference, ...]:
    differences: list[InterfaceDifference] = []
    if actual.module_name != expected.module_name:
        differences.append(
            InterfaceDifference(
                "module_name",
                f"module name is {actual.module_name!r}, must be {expected.module_name!r}",
                expected=expected.module_name,
                actual=actual.module_name,
            )
        )

    want = {port.name: port for port in expected.ports}
    got = {port.name: port for port in actual.ports}
    for name, port in want.items():
        if name not in got:
            differences.append(
                InterfaceDifference(
                    "missing_port",
                    f"missing port {name!r}",
                    name,
                    expected=port.public_dict(),
                )
            )
    for name, port in got.items():
        if expected.complete and name not in want:
            differences.append(
                InterfaceDifference(
                    "extra_port",
                    f"extra port {name!r} not in the declared interface",
                    name,
                    actual=port.public_dict(),
                )
            )
    for name in want.keys() & got.keys():
        expected_port = want[name]
        actual_port = got[name]
        if actual_port.direction != expected_port.direction:
            differences.append(
                InterfaceDifference(
                    "direction",
                    f"port {name!r} is {actual_port.direction}, "
                    f"must be {expected_port.direction}",
                    name,
                    expected_port.direction,
                    actual_port.direction,
                )
            )
        width_differs = (
            expected_port.width is not None and actual_port.width != expected_port.width
        )
        if width_differs:
            differences.append(
                InterfaceDifference(
                    "width",
                    f"port {name!r} is {_width_text(actual_port.width)}, "
                    f"must be {_width_text(expected_port.width)}",
                    name,
                    expected_port.width,
                    actual_port.width,
                )
            )
    return tuple(differences)


def _parse_ansi_ports(items: Iterable[str]) -> tuple[list[PortSpec], list[str]]:
    ports: list[PortSpec] = []
    warnings: list[str] = []
    direction: str | None = None
    width: int | None = 1
    range_text: str | None = None
    for item in items:
        direction_match = _DIRECTION_RE.search(item)
        if direction_match:
            direction = direction_match.group(1)
            width, range_text, width_warning = _parse_width(item)
            if width_warning:
                warnings.append(width_warning)
        if direction is None:
            warnings.append(f"port declaration has no direction: {item.strip()!r}")
            name = _ordinary_port_name(item)
            if name is not None:
                ports.append(PortSpec(name, "unknown", None))
                warnings.append(f"port {name!r} has no direction declaration")
            continue
        name = _declaration_name(item)
        if name is None:
            warnings.append(f"could not parse port name from {item.strip()!r}")
            continue
        ports.append(PortSpec(name, direction, width, range_text))
    return ports, warnings


def _parse_non_ansi_ports(
    header_items: Iterable[str], body: str
) -> tuple[list[PortSpec], list[str]]:
    warnings: list[str] = []
    header_names: list[str] = []
    ordinary_names: set[str] = set()
    for item in header_items:
        name = _declaration_name(item)
        if name is None:
            warnings.append(f"could not parse port name from {item.strip()!r}")
        else:
            header_names.append(name)
            if _ordinary_port_name(item) is not None:
                ordinary_names.add(name)
    declarations: dict[str, PortSpec] = {}
    for match in _DECLARATION_RE.finditer(body):
        direction = match.group(1)
        declaration = match.group(2)
        width, range_text, width_warning = _parse_width(declaration)
        if width_warning:
            warnings.append(width_warning)
        for item in _split_commas(declaration):
            name = _declaration_name(item)
            if name is not None:
                declarations[name] = PortSpec(name, direction, width, range_text)

    ports: list[PortSpec] = []
    for name in header_names:
        port = declarations.get(name)
        if port is None:
            warnings.append(
                f"port {name!r} has no direction declaration"
                if name in ordinary_names
                else f"could not establish direction of typed port {name!r}"
            )
            port = PortSpec(name, "unknown", None)
        ports.append(port)
    return ports, warnings


def _ordinary_port_name(text: str) -> str | None:
    """Recognize ordinary net/variable ports, not interface or user-defined types."""
    declaration = text.split("=", 1)[0]
    declaration = re.sub(r"\[[^\]]*\]", " ", declaration)
    declaration = _TYPE_WORDS_RE.sub(" ", declaration).strip()
    return declaration if _IDENTIFIER_RE.fullmatch(declaration) else None


def _parse_width(text: str) -> tuple[int | None, str | None, str | None]:
    range_match = re.search(r"\[([^\]]+)\]", text)
    if range_match is None:
        return 1, None, None
    range_text = range_match.group(1).strip()
    constant = re.fullmatch(r"(-?\d+)\s*:\s*(-?\d+)", range_text)
    if constant is None:
        return None, range_text, f"could not resolve packed width [{range_text}]"
    width = abs(int(constant.group(1)) - int(constant.group(2))) + 1
    return width, range_text, None


def _declaration_name(text: str) -> str | None:
    candidate = text.split("=", 1)[0]
    candidate = re.sub(r"\[[^\]]*\]", " ", candidate)
    candidate = _DIRECTION_RE.sub(" ", candidate)
    candidate = _TYPE_WORDS_RE.sub(" ", candidate)
    names = re.findall(r"[A-Za-z_]\w*", candidate)
    return names[-1] if names and _IDENTIFIER_RE.fullmatch(names[-1]) else None


def _split_commas(text: str) -> list[str]:
    items: list[str] = []
    start = 0
    depths = {"(": 0, "[": 0, "{": 0}
    pairs = {")": "(", "]": "[", "}": "{"}
    for index, char in enumerate(text):
        if char in depths:
            depths[char] += 1
        elif char in pairs:
            opener = pairs[char]
            depths[opener] = max(0, depths[opener] - 1)
        elif char == "," and not any(depths.values()):
            items.append(text[start:index])
            start = index + 1
    tail = text[start:]
    if tail.strip():
        items.append(tail)
    return items


def _balanced_end(text: str, start: int) -> int | None:
    depth = 0
    for index in range(start, len(text)):
        if text[index] == "(":
            depth += 1
        elif text[index] == ")":
            depth -= 1
            if depth == 0:
                return index
    return None


def _skip_space(text: str, position: int) -> int:
    while position < len(text) and text[position].isspace():
        position += 1
    return position


def _mask_comments(text: str) -> str:
    def mask(match: re.Match[str]) -> str:
        return "".join("\n" if char == "\n" else " " for char in match.group(0))

    text = re.sub(r"//[^\n]*", mask, text)
    return re.sub(r"/\*.*?\*/", mask, text, flags=re.DOTALL)


def _duplicate_port_warnings(ports: Iterable[PortSpec]) -> list[str]:
    seen: set[str] = set()
    warnings: list[str] = []
    for port in ports:
        if port.name in seen:
            warnings.append(f"duplicate port {port.name!r}")
        seen.add(port.name)
    return warnings


def _width_text(width: int | None) -> str:
    return "unknown width" if width is None else f"{width} bits"


def check_interface(ctx, candidate):
    """Prompt-inferred differences remain advisory; explicit contracts can block."""
    import time
    from agent.domain.rtl.result import CheckResult

    started = time.monotonic()
    result = check_interface_result(
        candidate.code, ctx.task.interface, ctx.task.prompt, top=ctx.task.top
    )
    status = {
        "ok": "passed",
        "mismatch": "failed",
        "advisory": "failed",
        "skipped": "skipped",
        "parse_error": "error",
    }[result.status]
    return CheckResult(
        status,
        result.summary,
        blocking=result.blocking,
        rc=result.rc,
        elapsed_s=time.monotonic() - started,
        details=result.trace_dict(),
        failure_kind="code" if result.blocking and status == "failed" else "unknown",
    )
