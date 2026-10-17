"""Extract structured RTL source information from model replies."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

from agent.core.extraction import ExtractionResult, ExtractionStatus


@dataclass(frozen=True)
class _Block:
    body: str
    closed: bool


@dataclass(frozen=True)
class _AnalyzedBlock:
    code: str
    module_names: tuple[str, ...]
    complete: bool
    contains_target: bool


_FENCE_START_RE = re.compile(r"```([^\r\n`]*)[ \t]*(?:\r?\n|$)")
_RTL_LABELS = {"", "verilog", "systemverilog", "sv", "v"}
_MODULE_NAME_RE = re.compile(r"\bmodule\s+([A-Za-z_]\w*)")
_MODULE_TOKEN_RE = re.compile(r"\bmodule\b")
_ENDMODULE_TOKEN_RE = re.compile(r"\bendmodule\b")


def extract_result(text: str, target_module: str | None = None) -> ExtractionResult:
    """Select RTL while reporting ambiguity, truncation and target-module fit."""
    reply = text or ""
    blocks = _fenced_rtl_blocks(reply)
    analyzed = [_analyze_block(block.body, target_module) for block in blocks]
    truncation = any(
        not block.closed or (_has_module(block.body) and not item.complete)
        for block, item in zip(blocks, analyzed)
    )
    diagnostics: list[str] = []

    complete_blocks = [item for item in analyzed if item.complete]
    if complete_blocks:
        selected = max(
            complete_blocks,
            key=lambda item: (item.contains_target, len(item.code)),
        )
        competing = [
            item for item in complete_blocks
            if target_module is None or item.contains_target
        ]
        ambiguous = len({item.code for item in competing}) > 1
        target_found = selected.contains_target if target_module else False
        if len(blocks) > 1:
            diagnostics.append(f"found {len(blocks)} RTL code blocks")
        if ambiguous:
            diagnostics.append("multiple different complete RTL drafts found")
        if target_module and not target_found:
            diagnostics.append(f"target module {target_module!r} was not found")
        if truncation:
            diagnostics.append("another RTL block appears incomplete or truncated")

        status: ExtractionStatus = "ok"
        if ambiguous:
            status = "ambiguous"
        elif target_module and not target_found:
            status = "target_missing"
        return ExtractionResult(
            code=selected.code,
            status=status,
            complete=True,
            target_module_found=target_found,
            module_names=selected.module_names,
            multiple_blocks=len(blocks) > 1,
            suspected_truncation=truncation,
            diagnostics=tuple(diagnostics),
        )

    if blocks:
        diagnostics.append("no fenced block contains complete RTL")
        if truncation:
            diagnostics.append("an RTL fence or module appears truncated")
        names = _unique_names(name for item in analyzed for name in item.module_names)
        return ExtractionResult(
            code="",
            status="incomplete" if truncation or names else "empty",
            complete=False,
            target_module_found=False,
            module_names=names,
            multiple_blocks=len(blocks) > 1,
            suspected_truncation=truncation,
            diagnostics=tuple(diagnostics),
        )

    unfenced = _unfenced_rtl(reply, target_module)
    if unfenced is not None and unfenced.complete:
        target_found = unfenced.contains_target if target_module else False
        status = "ok" if not target_module or target_found else "target_missing"
        if status == "target_missing":
            diagnostics.append(f"target module {target_module!r} was not found")
        return ExtractionResult(
            code=unfenced.code,
            status=status,
            complete=True,
            target_module_found=target_found,
            module_names=unfenced.module_names,
            multiple_blocks=False,
            suspected_truncation=False,
            diagnostics=tuple(diagnostics),
        )

    names = unfenced.module_names if unfenced is not None else ()
    incomplete = unfenced is not None and bool(names)
    if incomplete:
        diagnostics.append("module declaration has no matching endmodule")
    else:
        diagnostics.append("no RTL module found in reply")
    return ExtractionResult(
        code="",
        status="incomplete" if incomplete else "empty",
        complete=False,
        target_module_found=False,
        module_names=names,
        multiple_blocks=False,
        suspected_truncation=incomplete,
        diagnostics=tuple(diagnostics),
    )


def extract_code(text: str, target_module: str | None = None) -> str:
    """Compatibility wrapper returning only the selected source code."""
    return extract_result(text, target_module).code


def _fenced_rtl_blocks(text: str) -> list[_Block]:
    blocks: list[_Block] = []
    position = 0
    while True:
        start = _FENCE_START_RE.search(text, position)
        if start is None:
            break
        raw_label = start.group(1).strip().lower()
        label = raw_label.split(None, 1)[0] if raw_label else ""
        end = text.find("```", start.end())
        closed = end >= 0
        body = text[start.end():end if closed else len(text)]
        if label in _RTL_LABELS:
            blocks.append(_Block(body=body, closed=closed))
        if not closed:
            break
        position = end + 3
    return blocks


def _unfenced_rtl(text: str, target_module: str | None) -> _AnalyzedBlock | None:
    stripped = _strip_comments(text)
    first = _MODULE_NAME_RE.search(stripped)
    if first is None:
        return None
    end_matches = list(_ENDMODULE_TOKEN_RE.finditer(stripped))
    if not end_matches or end_matches[-1].end() <= first.start():
        fragment = text[first.start():]
    else:
        fragment = text[first.start():end_matches[-1].end()]
    return _analyze_block(fragment, target_module)


def _analyze_block(body: str, target_module: str | None) -> _AnalyzedBlock:
    code = body.strip()
    stripped = _strip_comments(code)
    names = _unique_names(_MODULE_NAME_RE.findall(stripped))
    module_count = len(_MODULE_TOKEN_RE.findall(stripped))
    endmodule_count = len(_ENDMODULE_TOKEN_RE.findall(stripped))
    complete = module_count > 0 and endmodule_count >= module_count
    return _AnalyzedBlock(
        code=code + "\n" if complete else "",
        module_names=names,
        complete=complete,
        contains_target=bool(target_module and target_module in names),
    )


def _has_module(text: str) -> bool:
    return _MODULE_NAME_RE.search(_strip_comments(text)) is not None


def _strip_comments(text: str) -> str:
    def mask(match: re.Match[str]) -> str:
        return "".join("\n" if char == "\n" else " " for char in match.group(0))

    text = re.sub(r"//[^\n]*", mask, text)
    return re.sub(r"/\*.*?\*/", mask, text, flags=re.DOTALL)


def _unique_names(names: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(names))
