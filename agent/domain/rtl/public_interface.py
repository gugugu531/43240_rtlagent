"""Conservative interface evidence from public specification sections only."""

from __future__ import annotations

import ast
from dataclasses import replace
import re

from agent.domain.rtl.interface import InterfaceSpec, PortSpec, _mask_comments, _split_commas

_NAME = r"[A-Za-z_]\w*"
_MAX_VALUE = 1 << 20
_MAX_WIDTH = 65536
_PORT_TEXT = re.compile(
    rf"(?:-\s*)?(?P<names>`?{_NAME}`?(?:\s*,\s*`?{_NAME}`?)*)"
    r"(?:\s*\[(?P<range>[^\]]+)\])?\s*(?:—|–|:\s|\s-\s)\s*(?P<description>.+)"
)
_PORT_DECL = re.compile(
    rf"(?:(input|output|inout)\s+)?"
    r"(?:(?:wire|reg|logic|bit|signed|unsigned|var|tri|supply0|supply1)\s+)*"
    rf"(?:\[([^\]]+)\]\s*)?({_NAME})"
)
_EXAMPLE_SECTION = re.compile(
    r"(?:(?:buggy|worked|incorrect|illustrative) )?examples?(?: \d+)?[:.]?"
    r"|(?:buggy|previous|sample) (?:code|implementation):?"
)
_INTERFACE_INTRO = re.compile(
    r"(?:^|[.!?]\s+)(?:implement|use)\s+(?:exactly\s+)?(?:this|the\s+following)\s+"
    r"(?:(?:verilog|systemverilog|sv|module)\s+)?(?:interface|signature|module\s+header)\s*[.:]?$",
    re.I,
)


def _next_starts_with_module(lines: list[str], start: int) -> bool:
    index = start
    while index < len(lines) and (
        not lines[index].strip()
        or lines[index].strip() in ("```", "```verilog", "```systemverilog", "```sv")
    ):
        index += 1
    if index >= len(lines):
        return False
    return bool(re.match(rf"module\s+{_NAME}\b", lines[index].lstrip()))


def _integer(expression: str, parameters: dict[str, int]) -> int:
    """Evaluate a small integer grammar, never Python calls or arbitrary code."""
    if len(expression) > 128:
        raise ValueError("integer expression is too long")
    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except (SyntaxError, RecursionError) as exc:
        raise ValueError("unsupported integer expression") from exc
    if sum(1 for _ in ast.walk(tree)) > 64:
        raise ValueError("integer expression is too complex")

    def visit(node):
        if isinstance(node, ast.Constant) and type(node.value) is int:
            value = node.value
        elif isinstance(node, ast.Name) and node.id in parameters:
            value = parameters[node.id]
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = visit(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
        elif isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult)):
            left, right = visit(node.left), visit(node.right)
            value = left + right if isinstance(node.op, ast.Add) else left - right if isinstance(node.op, ast.Sub) else left * right
        else:
            raise ValueError("unsupported or unresolved integer expression")
        if abs(value) > _MAX_VALUE:
            raise ValueError("integer expression exceeds limit")
        return value

    return visit(tree.body)


def _width(range_text: str, parameters: dict[str, int]) -> int:
    parts = range_text.split(":")
    if len(parts) != 2:
        raise ValueError("packed range needs two bounds")
    width = abs(_integer(parts[0], parameters) - _integer(parts[1], parameters)) + 1
    if not 1 <= width <= _MAX_WIDTH:
        raise ValueError("packed width exceeds limit")
    return width


def _title(line: str) -> str:
    return re.sub(r"^(?:#+\s*|-\s*)", "", line.strip()).replace("**", "").replace("__", "").strip().lower()


def _declared_top(prompt: str, top: str | None) -> str | None:
    if top:
        return top
    names = set(re.findall(rf"\bmodule\s+named\s+({_NAME})\b", prompt, re.I))
    return next(iter(names)) if len(names) == 1 else None


def _group(text: str, cursor: int) -> tuple[str, int]:
    while cursor < len(text) and text[cursor].isspace():
        cursor += 1
    if cursor == len(text) or text[cursor] != "(":
        raise ValueError("expected parenthesized declaration")
    start, depth = cursor + 1, 1
    for cursor in range(start, len(text)):
        depth += (text[cursor] == "(") - (text[cursor] == ")")
        if depth == 0:
            return text[start:cursor], cursor + 1
    raise ValueError("incomplete declaration")


def parameter_defaults(declarations: str) -> dict[str, int]:
    if declarations.rstrip().endswith(","):
        raise ValueError("incomplete parameter declaration")
    parameters = {}
    for declaration in _split_commas(declarations):
        parameter = re.fullmatch(
            rf"\s*(?:parameter\s+)?(?:(?:int|integer|signed|unsigned)\s+)*({_NAME})\s*=\s*(.+?)\s*",
            declaration, re.S,
        )
        if not parameter or parameter.group(1) in parameters:
            raise ValueError("unsupported or duplicate parameter declaration")
        parameters[parameter.group(1)] = _integer(parameter.group(2), parameters)
    return parameters


def declared_ports(declaration: str, parameters: dict[str, int], *, allow_unknown_width=False) -> tuple[PortSpec, ...]:
    """Read a simple ANSI header, including port order and default parameter widths."""
    if declaration.rstrip().endswith(","):
        raise ValueError("incomplete port declaration")
    ports, direction, width, raw_range = [], None, None, None
    names = set()
    for item in _split_commas(declaration):
        port = _PORT_DECL.fullmatch(item.strip())
        if not port:
            raise ValueError("unsupported port declaration")
        new_direction, new_range, port_name = port.groups()
        if new_direction:
            direction, raw_range = new_direction, new_range
            try:
                width = _width(raw_range, parameters) if raw_range else 1
            except ValueError:
                if not allow_unknown_width:
                    raise
                width = None
        elif item.strip() != port_name:
            raise ValueError("type or range without an explicit direction")
        if direction is None or port_name in names or port_name in (
            "input", "output", "inout", "wire", "reg", "logic", "bit", "signed", "unsigned", "var", "tri",
        ):
            raise ValueError("missing direction or duplicate port")
        names.add(port_name)
        ports.append(PortSpec(port_name, direction, width, raw_range))
    return tuple(ports)


def _signature(prompt: str, top: str | None) -> InterfaceSpec | None:
    lines = prompt.splitlines()
    sections = []
    in_fence = False
    example_level = None
    plain_example = False
    for index, line in enumerate(lines):
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        title = _title(line)
        heading = re.match(r"^\s*(#{1,6})\s", line)
        if heading:
            level = len(heading.group(1))
            if example_level is not None and level <= example_level:
                example_level = None
            plain_example = False
        if _EXAMPLE_SECTION.fullmatch(title):
            if heading and example_level is None:
                example_level = level
            elif not heading:
                plain_example = True
        elif title in ("requirements:", "required interface:", "required module interface:"):
            plain_example = False
        if example_level is None and not plain_example:
            if title in ("design signature:", "module signature:"):
                sections.append(index + 1)
            elif _INTERFACE_INTRO.search(line.strip()) and _next_starts_with_module(lines, index + 1):
                sections.append(index + 1)
    if not sections:
        return None
    if len(sections) != 1:
        return InterfaceSpec(top, (), "prompt_signature", "none", ("multiple public signature sections",), False)
    index = sections[0]
    while index < len(lines) and (not lines[index].strip() or lines[index].strip() in ("```", "```verilog", "```systemverilog", "```sv")):
        index += 1
    text = _mask_comments("\n".join(lines[index:])).lstrip()
    match = re.match(rf"module\s+({_NAME})\s*", text)
    if not match or (top and match.group(1) != top):
        return InterfaceSpec(top, (), "prompt_signature", "none", ("public signature does not declare the requested top",), False)
    name, cursor = match.group(1), match.end()
    try:
        parameters = {}
        if text[cursor:cursor + 1] == "#":
            declarations, cursor = _group(text, cursor + 1)
            parameters = parameter_defaults(declarations)
        declaration, cursor = _group(text, cursor)
        if not text[cursor:].lstrip().startswith(";"):
            raise ValueError("module header is missing its semicolon")
        ports = declared_ports(declaration, parameters)
        # Do not silently prefer the first of two declarations in the signature section.
        trailing = text[cursor:].lstrip()[1:]
        trailing = re.split(r"(?m)^\s*(?:#+\s*)?[A-Za-z][A-Za-z ]+:\s*$", trailing, maxsplit=1)[0]
        if re.search(r"\bmodule\s+", trailing):
            raise ValueError("multiple modules in public signature section")
        return InterfaceSpec(name, ports, "prompt_signature", "high", (f"public signature at line {index + 1}; widths use its declared parameter defaults",), True)
    except ValueError as exc:
        return InterfaceSpec(name, (), "prompt_signature", "none", (f"unresolved public signature: {exc}",), False)


def _description_width(description: str, raw_range: str | None) -> int | None:
    widths = [int(number) for number in re.findall(r"(?<![\w.-])(\d+)\s*(?:-\s*bits?\b|bits?\b)", description, re.I)]
    ranges = re.findall(r"\[([^\]]+)\]", description)
    if raw_range:
        ranges.append(raw_range)
    for item in ranges:
        try:
            widths.append(_width(item, {}))
        except ValueError:
            # A symbol alone is not a width. Preserve it as unresolved rather
            # than guessing a value from another module's parameter defaults.
            if not widths and re.fullmatch(rf"\s*{_NAME}\s*(?:[-+]\s*\d+)?\s*:\s*\d+\s*", item):
                return None
            raise
    if not widths:
        return None
    if len(set(widths)) != 1 or not 1 <= widths[0] <= _MAX_WIDTH:
        raise ValueError("conflicting or invalid explicit width")
    return widths[0]


def _described_ports(prompt: str):
    ports, errors, active, started, in_fence = [], [], None, False, False
    for number, line in enumerate(prompt.splitlines(), 1):
        stripped, title = line.strip(), _title(line)
        if stripped.startswith("```"):
            if active is not None:
                errors.append(f"code block in public port section at line {number}")
            in_fence = not in_fence
            active = None
            continue
        if in_fence:
            continue
        heading = re.fullmatch(r"(inputs?|outputs?)(?:\s+(?:ports?|interface))?:", title)
        if heading:
            if active is not None and not started:
                errors.append(f"empty public port section before line {number}")
            active, started = ("input" if heading.group(1).startswith("input") else "output"), False
            continue
        if active is None or not stripped:
            continue
        match = _PORT_TEXT.fullmatch(stripped)
        if match:
            started = True
            names = re.findall(_NAME, match.group("names"))
            try:
                width = _description_width(match.group("description"), match.group("range"))
                opposite = "output" if active == "input" else "input"
                if re.search(rf"\b{opposite}s?\b", match.group("description"), re.I):
                    raise ValueError("conflicting port direction in description")
            except ValueError as exc:
                width = None
                errors.append(f"public port description at line {number}: {exc}")
            ports.extend((PortSpec(name, active, width, match.group("range")), number) for name in names)
            continue
        if not started and (re.search(r"\bmodule\s+named\s+", stripped, re.I) or stripped.lower() == "interface."):
            continue
        boundary = re.fullmatch(r"-{3,}", stripped) or re.match(r"^#+\s", stripped) or re.fullmatch(r"[a-z][a-z /-]*:", title)
        if not boundary:
            errors.append(f"unrecognized public port description at line {number}")
        elif not started:
            errors.append(f"empty public port section before line {number}")
        active = None
    if active is not None and not started:
        errors.append("empty public port section at end of prompt")
    return ports, errors


def _merge_descriptions(original, described, errors):
    if not original.complete:
        return original
    known = {port.name: port for port in original.ports}
    evidence, warnings = {}, []
    for port, line in described:
        if port.name not in known or port.direction != known[port.name].direction:
            errors.append(f"public interface description conflicts at line {line}")
        elif port.width is not None:
            evidence.setdefault(port.name, []).append((port.width, line))
    ports = []
    for port in original.ports:
        facts = evidence.get(port.name, [])
        widths = {value for value, _ in facts}
        if port.width is not None:
            widths.add(port.width)
        if len(widths) > 1:
            errors.append(f"conflicting public widths for {port.name}")
            port = replace(port, width=None)
        elif port.width is None and len(widths) == 1:
            port = replace(port, width=next(iter(widths)))
            warnings.append(f"public width for {port.name} from description line {facts[0][1]}")
        ports.append(port)
    symbolic = {}
    for port in ports:
        if port.range_text and port.width is not None:
            symbolic.setdefault(port.range_text, set()).add(port.width)
    conflicts = {symbol for symbol, widths in symbolic.items() if len(widths) > 1}
    if conflicts:
        errors.append("conflicting widths for the same public symbolic range")
        ports = [replace(port, width=None) if port.range_text in conflicts else port for port in ports]
    if not warnings and not errors:
        return original
    resolved = {port.range_text for port in ports if port.range_text and port.width is not None}
    unresolved = {port.range_text for port in ports if port.width is None}
    stale = {
        message
        for value in resolved - unresolved
        for message in (
            f"could not resolve prompt width ({value} bits)",
            f"could not resolve packed width [{value}]",
        )
    }
    retained = tuple(warning for warning in original.warnings if warning not in stale)
    return replace(original, ports=tuple(ports), warnings=retained + tuple(warnings + errors), complete=not errors)


def supplement_public_interface(prompt: str, original: InterfaceSpec, *, top: str | None = None) -> InterfaceSpec:
    """Keep original port lists; add only explicit public signature/width evidence."""
    described, errors = _described_ports(prompt)
    declared_top = _declared_top(prompt, top)
    if original.ports:
        signature = _signature(prompt, top or original.module_name)
        if signature is not None:
            expected = {port.name: (port.direction, port.width) for port in original.ports}
            declared = {port.name: (port.direction, port.width) for port in signature.ports}
            if not signature.complete or expected.keys() != declared.keys() or any(
                direction != declared[name][0] or (width is not None and width != declared[name][1])
                for name, (direction, width) in expected.items() if name in declared
            ):
                errors.append("public signature conflicts with the explicit port list")
            elif original.complete:
                # A prose list may group inputs and outputs differently. The
                # declared header supplies the positional interface contract.
                return _merge_descriptions(signature, described, errors)
        return _merge_descriptions(original, described, errors)

    # A malformed explicit list must not be replaced by another interpretation.
    if any("could not parse prompt port" in warning for warning in original.warnings):
        return original
    if not top and len(set(re.findall(rf"\bmodule\s+named\s+({_NAME})\b", prompt, re.I))) > 1:
        return replace(original, complete=False, warnings=original.warnings + ("ambiguous public top name",))
    signature = _signature(prompt, declared_top)
    if signature is not None:
        return _merge_descriptions(signature, described, errors)
    if not described or not declared_top:
        return original
    ports = tuple(port for port, _ in described)
    if len({port.name for port in ports}) != len(ports):
        errors.append("duplicate public port description")
    for port in ports:
        if port.width is None:
            errors.append(f"no explicit public width for {port.name}")
    return InterfaceSpec(declared_top, ports, "prompt_list", "medium", tuple(errors) or ("ports from explicit public input/output sections",), not errors)
