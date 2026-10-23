"""Shared RTL tool results, diagnostics, logs and scratch directories."""
from __future__ import annotations
from dataclasses import dataclass
import os
import re
import tempfile
from typing import Sequence
from agent.core.tool import TOOL_SUMMARY_LIMIT, ToolResult, ToolStatus


@dataclass(frozen=True)
class CommandOutcome:
    command: tuple[str, ...]
    rc: int
    status: ToolStatus
    elapsed_s: float
    output: str
    log_path: str | None = None


def extract_diagnostics(log: str, limit=32):
    """Collect roots before summary truncation; incomplete evidence stays explicit."""
    rows, seen, omitted, truncated = [], set(), 0, False
    for line in log.splitlines():
        match = re.search(r'(ERROR|WARNING):\s*\[([^\]]+)\]\s*(.*)', line, re.I)
        if not match:
            continue
        severity, code, message = match.groups()
        code = ' '.join(code.upper().split())
        if severity.upper() == 'WARNING' and code != 'SYNTH 8-3848':
            continue
        key = (code, message)
        if key in seen:
            continue
        seen.add(key)
        if len(rows) >= limit:
            omitted += 1
            continue
        truncated |= len(message) > 700
        symbols = re.findall(r"(?:variable|signal|net)\s+['\"]([A-Za-z_][A-Za-z0-9_$]*)['\"]", message, re.I)
        rows.append(dict(code=code, severity=severity.lower(), message=message[:700],
                         symbols=list(dict.fromkeys(symbols)), cascade=code == 'XSIM 43-3322'))
    return dict(items=rows, omitted=omitted, complete=not (omitted or truncated))


def build_result(tool: str, outcomes: Sequence[CommandOutcome],
                  work: str, keep_work: bool, log_dir=None, redactor=None) -> ToolResult:
    commands = tuple(outcome.command for outcome in outcomes)
    final = outcomes[-1]
    full_output = "\n".join(outcome.output for outcome in outcomes)
    log_paths = tuple(outcome.log_path for outcome in outcomes if outcome.log_path)
    if len(log_paths) != len(outcomes):
        # Only write a log when the process executor kept no copy of its own.
        log_paths = ()
        full_log_path = os.path.join(work, f"{tool}.full.log") if keep_work else None
        if log_dir is not None:
            try:
                os.makedirs(log_dir, exist_ok=True)
                full_log_path = os.path.join(log_dir, os.path.basename(work) + '.log')
            except OSError:
                full_log_path = None
        if full_log_path is not None:
            try:
                _write_full_log(full_log_path, outcomes, redactor)
                log_paths = (full_log_path,)
            except OSError:
                pass
    version_match = re.search(r'(?:Vivado(?: Simulator)?|xvlog|xelab)\s+v?(\d{4}\.\d+)', full_output, re.I)
    return ToolResult(
        tool=tool,
        command=commands,
        rc=final.rc,
        status=final.status,
        elapsed_s=sum(outcome.elapsed_s for outcome in outcomes),
        summary=summarize_log(full_output),
        log_paths=log_paths,
        work_dir=work if keep_work else None,
        failure_kind=classify_tool_failure(full_output) if final.status == "failed" else "unknown",
        diagnostic_tool=os.path.basename(final.command[0]) if final.command else None,
        tool_version=version_match.group(1) if version_match else None,
        details={'repair_diagnostics': extract_diagnostics(full_output)},
    )


def _write_full_log(path: str, outcomes: Sequence[CommandOutcome], redactor=None) -> None:
    if redactor is None:
        from agent.recording.redaction import Redactor
        redactor = Redactor()
    with open(path, "w", encoding="utf-8") as fh:
        for index, outcome in enumerate(outcomes):
            if index:
                fh.write("\n")
            fh.write(redactor.copy("$ " + " ".join(outcome.command) + "\n"))
            fh.write(redactor.copy(outcome.output))
            if outcome.output and not outcome.output.endswith("\n"):
                fh.write("\n")


def unavailable(tool: str, reason: str) -> ToolResult:
    return ToolResult(tool, (), -1, "unavailable", 0.0, reason)


_VERILOG_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


def validate_top(top: str, tool: str) -> ToolResult | None:
    if _VERILOG_IDENTIFIER_RE.fullmatch(top):
        return None
    return ToolResult(
        tool=tool,
        command=(),
        rc=2,
        status="failed",
        elapsed_s=0.0,
        summary=f"invalid top module name: {top!r}",
    )


def make_work_dir(prefix: str, scratch: str | None = None) -> str:
    scratch = scratch or _scratch_dir()
    os.makedirs(scratch, exist_ok=True)
    return tempfile.mkdtemp(prefix=prefix, dir=scratch)


def _scratch_dir() -> str:
    """Local disk, never network storage.

    Vivado produces large numbers of small files. On the NFS-backed /workspace of
    the cloud platform that is pathologically slow. This is not an optimisation.

    Section 9 of docs/API_CONTRACT.md names `/tmp/eda` and the base image exports it
    as `EDA_TMP`. Honour it -- running run.sh directly (rather than through
    serve_api.py, which passes `AGENT_TMP`) otherwise lands in `/tmp`, which is
    local disk too but not the directory the platform cleans up for you.

    `TRACK_TMP` is the old name of `EDA_TMP`, kept as a fallback.
    """
    return (os.environ.get("AGENT_TMP")
            or os.environ.get("EDA_TMP")
            or os.environ.get("TRACK_TMP")
            or "/tmp")


_INTERESTING = (
    "ERROR:", "CRITICAL WARNING:", "error:",
    "WARNING: [Synth 8-3848]",
    "Synthesis finished", "Synthesis failed", "Mismatches:",
)


def summarize_log(log: str, budget: int = 2000) -> str:
    """Compress a tool log to something a model can actually read.

    A Vivado synthesis log runs to thousands of lines. Feeding it back whole eats
    the context window and buries the one line that matters. Keep the lines that
    carry a verdict, drop the rest, and mark the truncation honestly.
    """
    lines = [ln.rstrip() for ln in log.splitlines()]
    keep = [ln for ln in lines if any(k in ln for k in _INTERESTING)]
    if not keep:
        keep = lines[-40:]

    text = "\n".join(keep)
    if len(text) > budget:
        text = text[:budget] + f"\n... [truncated, {len(text) - budget} more chars]"
    return text


def classify_tool_failure(output: str) -> str:
    """Only well identified compiler errors are treated as source defects."""
    low = output.lower()
    if (any(text in low for text in ('permission denied', 'no space left',
                                    'out of memory', 'cannot open shared object'))
            or re.search(r'(?:license[^\n]*(?:failed|expired|error|unavailable)|(?:failed|unable|cannot)[^\n]*license|no valid license)', low)):
        return 'environment'
    # Match primary source diagnostics, not generic follow-on errors such as
    # "module ignored". Environment errors above always take precedence.
    if re.search(r'ERROR:\s*\[VRFC 10-3818\][^\n]*driven by invalid combination of procedural drivers',
                 output, re.IGNORECASE):
        return 'code'
    if re.search(r'ERROR: \[VRFC 10-(?:1280|9336)\]', output, re.IGNORECASE):
        return 'code'
    if re.search(r'ERROR: \[VRFC 10-1219\][^\n]*part-select direction is opposite from prefix index direction',
                 output, re.IGNORECASE):
        return 'code'
    if re.search(r'ERROR: \[VRFC [^\]]+\].*(?:syntax error|cannot find port|not declared|not found|type mismatch|procedural assignment to a non-register|redeclaration of ANSI port|multiple drivers|already declared)',
                 output, re.IGNORECASE):
        return 'code'
    if re.search(r'ERROR: \[Synth [^\]]+\].*(?:syntax error|multi-driven|multiple drivers|latch)',
                 output, re.IGNORECASE):
        return 'code'
    return 'unknown'
