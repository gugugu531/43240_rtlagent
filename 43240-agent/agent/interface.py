"""Structured parsing and comparison of RTL module interfaces."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable, Literal


InterfaceSource = Literal[
    "interface_file", "prompt_list", "generated_code", "unknown"
]
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

    def trace_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "blocking": self.blocking,
            "rc": self.rc,
            "expected_source": self.expected.source,
            "expected_confidence": self.expected.confidence,
            "actual_confidence": self.actual.confidence,
            "expected_module": self.expected.module_name,
            "actual_module": self.actual.module_name,
            "differences": [item.public_dict() for item in self.differences],
            "warnings": list(self.expected.warnings + self.actual.warnings),
            "excerpt": self.summary[:500],
        }


_IDENTIFIER_RE = re.compile(r"^[A-Za-z_]\w*$")
_MODULE_RE = re.compile(r"\bmodule\s+([A-Za-z_]\w*)")
_DIRECTION_RE = re.compile(r"\b(input|output|inout)\b")
_PROMPT_PORT_RE = re.compile(
    r"^\s*-\s*(input|output|inout)\s+([A-Za-z_]\w*)\s*,?"
    r"\s*(?:\(\s*(\d+)\s*(?:bits?|位)\s*\))?\s*$",
    re.MULTILINE,
)
_DECLARATION_RE = re.compile(r"\b(input|output|inout)\b(.*?);", re.DOTALL)
_TYPE_WORDS_RE = re.compile(
    r"\b(?:wire|reg|logic|bit|var|signed|unsigned|tri|supply0|supply1)\b"
)


def parse_expected_interface(interface: str, prompt: str = "") -> InterfaceSpec:
    """Use an interface file when present; otherwise parse only prompt bullets."""
    if interface and interface.strip():
        return parse_module_interface(interface, source="interface_file")
    return parse_prompt_interface(prompt)


def parse_prompt_interface(prompt: str) -> InterfaceSpec:
    """Parse a prose port list without treating bugfix source as a specification."""
    text = prompt or ""
    matches = _PROMPT_PORT_RE.findall(text)
    warnings: list[str] = []
    if not matches:
        if _MODULE_RE.search(_mask_comments(text)):
            warnings.append(
                "embedded module text was not treated as an interface specification"
            )
        else:
            warnings.append("no prompt port list found")
        return InterfaceSpec(None, (), "prompt_list", "none", tuple(warnings))

    name_match = re.search(r"\bmodule\s+named\s+([A-Za-z_]\w*)", text)
    if name_match:
        module_name = name_match.group(1)
    else:
        module_name = "TopModule"
        warnings.append("module name not stated; defaulted to TopModule")
    ports = tuple(
        PortSpec(name=name, direction=direction, width=int(width) if width else 1)
        for direction, name, width in matches
    )
    warnings.extend(_duplicate_port_warnings(ports))
    return InterfaceSpec(
        module_name, ports, "prompt_list", "medium", tuple(warnings)
    )


def parse_module_interface(
        text: str, *, source: InterfaceSource = "generated_code") -> InterfaceSpec:
    """Parse ANSI or classic non-ANSI Verilog module declarations."""
    raw = text or ""
    cleaned = _mask_comments(raw)
    module_match = _MODULE_RE.search(cleaned)
    if module_match is None:
        return InterfaceSpec(
            None, (), source, "none", ("no module declaration found",)
        )

    module_name = module_match.group(1)
    warnings: list[str] = []
    cursor = _skip_space(cleaned, module_match.end())
    if cursor < len(cleaned) and cleaned[cursor] == "#":
        cursor = _skip_space(cleaned, cursor + 1)
        if cursor >= len(cleaned) or cleaned[cursor] != "(":
            return InterfaceSpec(
                module_name, (), source, "low",
                ("malformed parameter list in module declaration",),
            )
        parameter_end = _balanced_end(cleaned, cursor)
        if parameter_end is None:
            return InterfaceSpec(
                module_name, (), source, "low",
                ("unterminated parameter list in module declaration",),
            )
        cursor = _skip_space(cleaned, parameter_end + 1)

    if cursor >= len(cleaned) or cleaned[cursor] != "(":
        semicolon = cleaned.find(";", cursor)
        if semicolon < 0:
            return InterfaceSpec(
                module_name, (), source, "low",
                ("module declaration has no port list or semicolon",),
            )
        return InterfaceSpec(module_name, (), source, "high", ())

    port_end = _balanced_end(cleaned, cursor)
    if port_end is None:
        return InterfaceSpec(
            module_name, (), source, "low",
            ("unterminated module port list",),
        )
    header = cleaned[cursor + 1:port_end]
    body = cleaned[port_end + 1:]
    endmodule = re.search(r"\bendmodule\b", body)
    if endmodule is not None:
        body = body[:endmodule.start()]
    items = _split_commas(header)
    ansi = any(_DIRECTION_RE.search(item) for item in items)
    if ansi:
        ports, parse_warnings = _parse_ansi_ports(items)
    else:
        ports, parse_warnings = _parse_non_ansi_ports(items, body)
    warnings.extend(parse_warnings)
    warnings.extend(_duplicate_port_warnings(ports))
    confidence: Confidence = "high" if not warnings else "medium"
    return InterfaceSpec(
        module_name, tuple(ports), source, confidence, tuple(warnings)
    )


def check_interface_result(source: str, interface: str,
                           prompt: str = "") -> InterfaceCheckResult:
    """Compare generated RTL with the authoritative or advisory expectation."""
    expected = parse_expected_interface(interface, prompt)
    actual = parse_module_interface(source, source="generated_code")

    if not expected.parsed:
        if interface and interface.strip():
            summary = "interface.txt is present but its module declaration could not be parsed"
            return InterfaceCheckResult(
                "parse_error", True, expected, actual, (), summary
            )
        summary = (
            "接口既不在 interface 里，也没能从题面解析出端口表，"
            "本次跳过检查"
        )
        return InterfaceCheckResult("skipped", False, expected, actual, (), summary)

    if not actual.parsed:
        summary = "no module declaration found in the generated code"
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
        summary = (
            "⚠ 与题面端口清单不符（题面为散文，仅供参考，未拦截）: "
            + detail
        )
        return InterfaceCheckResult(
            "advisory", False, expected, actual, differences, summary
        )
    summary = "interface mismatch: " + detail
    return InterfaceCheckResult(
        "mismatch", True, expected, actual, differences, summary
    )


def _compare_interfaces(expected: InterfaceSpec,
                        actual: InterfaceSpec) -> tuple[InterfaceDifference, ...]:
    differences: list[InterfaceDifference] = []
    if actual.module_name != expected.module_name:
        differences.append(InterfaceDifference(
            "module_name",
            f"module name is {actual.module_name!r}, must be {expected.module_name!r}",
            expected=expected.module_name,
            actual=actual.module_name,
        ))

    want = {port.name: port for port in expected.ports}
    got = {port.name: port for port in actual.ports}
    for name, port in want.items():
        if name not in got:
            differences.append(InterfaceDifference(
                "missing_port", f"missing port {name!r}", name,
                expected=port.public_dict(),
            ))
    for name, port in got.items():
        if name not in want:
            differences.append(InterfaceDifference(
                "extra_port",
                f"extra port {name!r} not in the declared interface",
                name, actual=port.public_dict(),
            ))
    for name in want.keys() & got.keys():
        expected_port = want[name]
        actual_port = got[name]
        if actual_port.direction != expected_port.direction:
            differences.append(InterfaceDifference(
                "direction",
                f"port {name!r} is {actual_port.direction}, "
                f"must be {expected_port.direction}",
                name, expected_port.direction, actual_port.direction,
            ))
        width_differs = actual_port.width != expected_port.width
        if (actual_port.width is None and expected_port.width is None
                and actual_port.range_text != expected_port.range_text):
            width_differs = True
        if width_differs:
            differences.append(InterfaceDifference(
                "width",
                f"port {name!r} is {_width_text(actual_port.width)}, "
                f"must be {_width_text(expected_port.width)}",
                name, expected_port.width, actual_port.width,
            ))
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
            continue
        name = _declaration_name(item)
        if name is None:
            warnings.append(f"could not parse port name from {item.strip()!r}")
            continue
        ports.append(PortSpec(name, direction, width, range_text))
    return ports, warnings


def _parse_non_ansi_ports(
        header_items: Iterable[str], body: str) -> tuple[list[PortSpec], list[str]]:
    header_names = [name for item in header_items
                    if (name := _declaration_name(item)) is not None]
    declarations: dict[str, PortSpec] = {}
    warnings: list[str] = []
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
            warnings.append(f"port {name!r} has no direction declaration")
            port = PortSpec(name, "unknown", None)
        ports.append(port)
    return ports, warnings


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
