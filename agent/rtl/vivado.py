"""Managed Vivado checks with bounded scratch space and strict diagnostics."""

from __future__ import annotations
import os
import re
import shutil
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from .result import CheckResult


def extract_diagnostics(log: str, limit=32):
    """Collect roots before summary truncation; incomplete evidence stays explicit."""
    rows, seen, omitted, truncated = [], set(), 0, False
    for line in log.splitlines():
        match = re.search(r"(ERROR|WARNING):\s*\[([^\]]+)\]\s*(.*)", line, re.I)
        if not match:
            continue
        severity, code, message = match.groups()
        code = " ".join(code.upper().split())
        if severity.upper() == "WARNING" and code != "SYNTH 8-3848":
            continue
        key = (code, message)
        if key in seen:
            continue
        seen.add(key)
        if len(rows) >= limit:
            omitted += 1
            continue
        truncated |= len(message) > 700
        symbols = re.findall(
            r"(?:variable|signal|net)\s+['\"]([A-Za-z_][A-Za-z0-9_$]*)['\"]",
            message,
            re.I,
        )
        rows.append(
            dict(
                code=code,
                severity=severity.lower(),
                message=message[:700],
                symbols=list(dict.fromkeys(symbols)),
                cascade=code == "XSIM 43-3322",
            )
        )
    return dict(items=rows, omitted=omitted, complete=not (omitted or truncated))


_INTERESTING = (
    "ERROR:",
    "CRITICAL WARNING:",
    "error:",
    "WARNING: [Synth 8-3848]",
    "Synthesis finished",
    "Synthesis failed",
    "Mismatches:",
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
    if any(
        text in low
        for text in (
            "permission denied",
            "no space left",
            "out of memory",
            "cannot open shared object",
        )
    ) or re.search(
        r"(?:license[^\n]*(?:failed|expired|error|unavailable)|(?:failed|unable|cannot)[^\n]*license|no valid license)",
        low,
    ):
        return "environment"
    # Match primary source diagnostics, not generic follow-on errors such as
    # "module ignored". Environment errors above always take precedence.
    if re.search(
        r"ERROR:\s*\[VRFC 10-3818\][^\n]*driven by invalid combination of procedural drivers",
        output,
        re.IGNORECASE,
    ):
        return "code"
    if re.search(r"ERROR: \[VRFC 10-(?:1280|9336)\]", output, re.IGNORECASE):
        return "code"
    if re.search(
        r"ERROR: \[VRFC 10-1219\][^\n]*part-select direction is opposite from prefix index direction",
        output,
        re.IGNORECASE,
    ):
        return "code"
    if re.search(
        r"ERROR: \[VRFC [^\]]+\].*(?:syntax error|cannot find port|not declared|not found|type mismatch|procedural assignment to a non-register|redeclaration of ANSI port|multiple drivers|already declared)",
        output,
        re.IGNORECASE,
    ):
        return "code"
    if re.search(
        r"ERROR: \[Synth [^\]]+\].*(?:syntax error|multi-driven|multiple drivers|latch)",
        output,
        re.IGNORECASE,
    ):
        return "code"
    return "unknown"


_CAPACITY = threading.BoundedSemaphore(4)


@contextmanager
def tool_slot(ctx, timeout_s):
    """Share the four-process ceiling across lint, synthesis and simulation."""
    timeout = ctx.budget.timeout(timeout_s)
    acquired = _CAPACITY.acquire(timeout=max(0, timeout))
    try:
        yield acquired
    finally:
        if acquired:
            _CAPACITY.release()


def scratch_directory():
    path = os.environ.get("EDA_TMP") or os.environ.get("AGENT_TMP") or "/tmp"
    Path(path).mkdir(parents=True, exist_ok=True)
    return path


def executable(name):
    return shutil.which(
        name, path=os.environ.get("RTL_TOOL_BIN") or os.environ.get("PATH")
    )


def process_output(result):
    return getattr(result, "stdout", getattr(result, "output", ""))


def process_status(result):
    if getattr(result, "timed_out", False):
        return "timeout"
    status = getattr(result, "status", None)
    if status:
        return status
    return "ok" if result.rc == 0 else "unavailable" if result.rc == -1 else "failed"


def _check(ctx, candidate, kind, timeout_s):
    started = time.monotonic()
    names = ("xvlog", "xelab") if kind == "lint" else ("vivado",)
    tools = {name: executable(name) for name in names}
    missing = [name for name, path in tools.items() if not path]
    if missing:
        return CheckResult(
            "unavailable",
            "tools unavailable: " + ", ".join(missing),
            rc=-1,
            failure_kind="environment",
        )
    top = ctx.task.top
    part = os.environ.get("RTL_PART", "xczu3eg-sbva484-1-e")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", top):
        return CheckResult("error", "invalid top module name", rc=2)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", part):
        return CheckResult(
            "error", "invalid FPGA part", rc=2, failure_kind="environment"
        )
    commands, logs, outcomes = [], [], []
    timeout = ctx.budget.timeout(timeout_s)
    deadline = started + timeout
    with tool_slot(ctx, timeout) as acquired:
        if not acquired:
            return CheckResult(
                "timeout",
                "Vivado concurrency wait timed out",
                rc=124,
                failure_kind="timeout",
            )
        with tempfile.TemporaryDirectory(
            prefix=f"rtla_{kind}_", dir=scratch_directory()
        ) as work:
            Path(work, "solution.sv").write_text(candidate.code, encoding="utf-8")
            if kind == "lint":
                planned = [
                    (tools["xvlog"], "--sv", "solution.sv"),
                    (tools["xelab"], top, "-s", "dutsim", "-timescale", "1ps/1ps"),
                ]
            else:
                Path(work, "synth.tcl").write_text(
                    f"read_verilog -sv solution.sv\nsynth_design -top {top} -part {part} -mode out_of_context\n",
                    encoding="utf-8",
                )
                planned = [
                    (
                        tools["vivado"],
                        "-mode",
                        "batch",
                        "-source",
                        "synth.tcl",
                        "-nojournal",
                        "-log",
                        "synth.log",
                    )
                ]
            for command in planned:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return CheckResult(
                        "timeout",
                        f"{kind} exceeded its time limit",
                        rc=124,
                        failure_kind="timeout",
                        elapsed_s=time.monotonic() - started,
                        command=tuple(commands),
                        log_paths=tuple(logs),
                    )
                commands.append(command)
                result = ctx.processes.run(
                    command, cwd=work, timeout_s=ctx.budget.timeout(remaining)
                )
                output = process_output(result)
                outcomes.append(output)
                if getattr(result, "log_path", None):
                    logs.append(str(result.log_path))
                if process_status(result) != "ok":
                    break
    output = "\n".join(outcomes)
    status = process_status(result)
    failure = (
        "timeout"
        if status == "timeout"
        else "environment"
        if status == "unavailable"
        else classify_tool_failure(output)
        if status == "failed"
        else "unknown"
    )
    # A successful process with a license failure is still unavailable evidence.
    if classify_tool_failure(output) == "environment":
        failure, status = "environment", "unavailable"
    elif status == "ok" and re.search(r"(?im)^\s*(?:ERROR|FATAL):", output):
        failure = classify_tool_failure(output)
        status = "failed" if failure == "code" else "error"
    if kind == "synth" and status == "ok" and "Synthesis finished" not in output:
        status = "failed"
        output += "\n[agent] synthesis success marker missing"
    version = re.search(
        r"(?:Vivado(?: Simulator)?|xvlog|xelab)\s+v?(\d{4}\.\d+)", output, re.I
    )
    return CheckResult(
        "passed" if status == "ok" else status,
        summarize_log(output),
        rc=result.rc if status == process_status(result) else 1,
        elapsed_s=time.monotonic() - started,
        command=tuple(commands),
        log_paths=tuple(logs),
        failure_kind=failure,
        details={
            "repair_diagnostics": extract_diagnostics(output),
            "candidate_hash": candidate.code_hash,
            "tool_version": version.group(1) if version else None,
        },
    )


def lint(ctx, candidate, *, timeout_s=300.0):
    return _check(ctx, candidate, "lint", timeout_s)


def synth(ctx, candidate, *, timeout_s=600.0):
    return _check(ctx, candidate, "synth", timeout_s)
