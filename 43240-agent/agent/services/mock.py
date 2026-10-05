"""Mock replies exercise plumbing; they do not solve the task."""
import re

def mock_content(messages):
    user = "\n".join(str(m['content']) for m in messages if m.get('role') == 'user')
    header, outputs = _parse_module(user)
    if header is None:
        header, outputs = _header_from_prompt(user)
    body = header + "\n  // MOCK BACKEND: placeholder implementation.\n" if header else "// MOCK: no interface found\n"
    for name, width in outputs:
        body += f"  assign {name} = {width}'b0;\n"
    if header:
        body += "endmodule\n"
    return "以下是实现：\n\n```verilog\n" + body + "```\n"

_MODULE_RE = re.compile(r"module\s+(\w+)\s*(?:#\s*\([^)]*\)\s*)?\((.*?)\)\s*;", re.DOTALL)


def _header_from_prompt(text: str) -> tuple[str | None, list[tuple[str, int]]]:
    """从题面的端口清单拼出 module 头。

    复用 tools.ports_from_prompt，与 check_interface 用的是同一份解析，
    免得两处对「题面里的端口表」有两套理解。
    """
    from ..tools import ports_from_prompt

    name, ports = ports_from_prompt(text)
    if not name or not ports:
        return None, []
    decls = []
    for direction, width, pname in ports:
        w = "" if width <= 1 else f" [{width - 1}:0]"
        decls.append(f"  {direction}{w} {pname}")
    header = f"module {name} (\n" + ",\n".join(decls) + "\n);"
    outputs = [(n, w) for d, w, n in ports if d == "output"]
    return header, outputs


def _parse_module(text: str) -> tuple[str | None, list[tuple[str, int]]]:
    """Return the module header verbatim plus its output ports and widths."""
    m = _MODULE_RE.search(text)
    if not m:
        return None, []

    header = m.group(0)
    outputs: list[tuple[str, int]] = []
    for decl in m.group(2).split(","):
        decl = decl.strip()
        if not decl.lower().startswith("output"):
            continue
        rng = re.search(r"\[\s*(\d+)\s*:\s*(\d+)\s*\]", decl)
        width = abs(int(rng.group(1)) - int(rng.group(2))) + 1 if rng else 1
        name = decl.split()[-1].strip("[]() \t")
        if name:
            outputs.append((name, width))
    return header, outputs
