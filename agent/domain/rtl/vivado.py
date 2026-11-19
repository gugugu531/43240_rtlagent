"""Managed Vivado checks with bounded scratch space and strict diagnostics."""

from __future__ import annotations
import os
import re
import shutil
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from agent.runtime.budget import BudgetExhausted
from .result import CheckResult


_DIAGNOSTIC = re.compile(
    r"\b(CRITICAL\s+WARNING|ERROR|WARNING|FATAL):\s*(?:\[([^\]]+)\]\s*)?(.*)", re.I
)
_DIAGNOSTIC_SCOPE = "ERROR, WARNING, CRITICAL WARNING and FATAL lines; INFO excluded"
_HIGH_SEVERITIES = frozenset({"error", "critical warning", "fatal"})


def _retain_by_severity(candidates, limit):
    """Keep high-severity diagnostics before warnings, without changing their order.

    Candidates carry a canonical "severity" and are already in source order.
    Omitted rows must be accounted for by the caller as the amount beyond limit.
    """
    if limit >= len(candidates):
        return list(candidates)
    high = [index for index, row in enumerate(candidates)
            if row["severity"] in _HIGH_SEVERITIES]
    if len(high) >= limit:
        keep = set(high[:limit])
    else:
        low = [index for index, row in enumerate(candidates)
               if row["severity"] not in _HIGH_SEVERITIES]
        keep = set(high) | set(low[: limit - len(high)])
    return [row for index, row in enumerate(candidates) if index in keep]


def extract_diagnostics(log: str, limit=32):
    """Retain diagnostics severity-first, in source order, with explicit limits.

    ERROR, CRITICAL WARNING and FATAL lines are kept before WARNING lines so a
    warning flood cannot displace a source error; the returned items always
    follow the source transcript. Completeness covers unique diagnostic lines,
    not the full tool transcript. Repeated diagnostics are counted separately;
    messages are never interpreted as source defects here. Attribution remains
    the classifier's responsibility.
    """
    limit = max(0, limit)
    candidates, seen, duplicates = [], set(), 0
    for line_number, line in enumerate(log.splitlines(), 1):
        match = _DIAGNOSTIC.search(line)
        if not match:
            continue
        severity, code, message = match.groups()
        code = " ".join(code.upper().split()) if code else None
        severity = " ".join(severity.lower().split())
        key = (severity, code, message)
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        candidates.append(
            dict(code=code, severity=severity, message=message, line_number=line_number)
        )
    rows, truncated = [], 0
    for candidate in _retain_by_severity(candidates, limit):
        message = candidate["message"]
        symbols = re.findall(
            r"(?:variable|signal|net)\s+['\"]([A-Za-z_][A-Za-z0-9_$]*)['\"]",
            message,
            re.I,
        )
        truncated += int(len(message) > 700)
        rows.append(
            dict(
                code=candidate["code"],
                severity=candidate["severity"],
                message=message[:700],
                line_number=candidate["line_number"],
                message_truncated=len(message) > 700,
                symbols=list(dict.fromkeys(symbols)),
                cascade=candidate["code"] == "XSIM 43-3322",
            )
        )
    omitted = len(candidates) - len(rows)
    return dict(
        items=rows, omitted=omitted, truncated=truncated, duplicates=duplicates,
        complete=not (omitted or truncated), scope=_DIAGNOSTIC_SCOPE, limit=limit,
    )


def banner_version(output):
    banner = re.search(
        r"(?im)^\s*\**\s*(?:Vivado(?: Simulator)?|xvlog|xelab)\s+v?(\d{4}\.\d+)\b",
        output,
    )
    return banner.group(1) if banner else None


def knowledge_details(executions, limit=32, version_probes=None):
    """Keep diagnostic provenance local to each actual command invocation.

    Retention is severity-first across the whole run: every ERROR, CRITICAL
    WARNING and FATAL line is considered before WARNING lines, while retained
    output still follows command and source order.
    """
    limit = max(0, limit)
    commands, probes, pending, omitted, duplicates = [], {}, [], 0, 0
    for index, (command, output, status, rc) in enumerate(executions):
        # Tool namespaces are shared by multiple executables. Neither a code's
        # namespace nor a previous command's banner identifies this invocation.
        version = banner_version(output)
        probe = (version_probes or {}).get(command[0]) if version is None else None
        if probe is not None:
            probes[probe["probe_id"]] = probe
            version = probe["version"]
        provenance = dict(
            tool=Path(command[0]).name,
            version=version,
            version_source=("version_probe" if probe else "banner") if version else None,
            version_probe_id=probe["probe_id"] if probe else None,
            command_index=index,
            process_status=status,
        )
        commands.append({**provenance, "rc": rc})
        diagnostics = extract_diagnostics(output, limit=limit)
        pending.extend(
            {
                **item,
                **provenance,
                "cascade": item["cascade"] or bool(re.search(
                    r"(?:ignored due to previous errors|failed due to (?:earlier|previous) errors)",
                    item["message"], re.I,
                )),
            }
            for item in diagnostics["items"]
        )
        omitted += diagnostics["omitted"]
        duplicates += diagnostics["duplicates"]
    items = _retain_by_severity(pending, limit)
    omitted += len(pending) - len(items)
    truncated = sum(int(item["message_truncated"]) for item in items)
    return {
        "knowledge_diagnostics": dict(
            items=items, omitted=omitted, truncated=truncated, duplicates=duplicates,
            complete=not (omitted or truncated), scope=_DIAGNOSTIC_SCOPE, limit=limit,
        ),
        "knowledge_commands": commands,
        "knowledge_version_probes": list(probes.values()),
    }


def version_probes(ctx, executions, *, deadline, cwd):
    """Probe confirmed xvlog syntax after source checks, with a task-local cache."""
    cache = ctx.store.setdefault("vivado_version_probes", {})
    used = {}
    for command, output, _, _ in executions:
        executable_path = command[0]
        if (
            banner_version(output) is not None
            or Path(executable_path).name != "xvlog"
            or not Path(executable_path).is_absolute()
        ):
            continue
        if executable_path in cache:
            used[executable_path] = cache[executable_path]
            continue
        remaining = min(5.0, deadline - time.monotonic())
        if remaining <= 0:
            continue
        probe_command = (executable_path, "--version")
        try:
            probe_timeout = ctx.budget.timeout(remaining)
            result = ctx.processes.run(
                probe_command, cwd=cwd, timeout_s=probe_timeout
            )
        except BudgetExhausted:
            # Optional provenance cannot replace an already completed verdict.
            continue
        status = process_status(result)
        probe = dict(
            probe_id=uuid.uuid4().hex,
            executable=executable_path,
            command=list(probe_command),
            process_status=status,
            rc=result.rc,
            timeout_s=probe_timeout,
            elapsed_s=getattr(result, "elapsed_s", None),
            log_path=str(result.log_path) if getattr(result, "log_path", None) else None,
            version=banner_version(process_output(result)) if status == "ok" else None,
        )
        cache[executable_path] = probe
        used[executable_path] = probe
        ctx.record.emit("knowledge", "version_probe", **probe)
    return used


_INTERESTING = (
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
    keep = [ln for ln in lines if _DIAGNOSTIC.search(ln) or any(k in ln for k in _INTERESTING)]
    if not keep:
        keep = lines[-40:]

    text = "\n".join(keep)
    budget = max(0, budget)
    if len(text) > budget:
        text = text[:budget] + f"\n... [truncated, {len(text) - budget} more chars]"
    if len(keep) < len(lines):
        text += f"\n... [{len(lines) - len(keep)} other log lines omitted]"
    return text


_SOURCE_NOTICE = re.compile(
    r"^[ \t]*(ERROR|WARNING|CRITICAL WARNING):[ \t]*"
    r"\[(VRFC 10-3380|Synth 8-10929|Synth 8-151)\][ \t]+"
    r"([^\r\n]+?)[ \t]+\[([^\[\]\r\n]+?):([1-9]\d*)(?::\d+)?\][ \t]*$",
    re.I | re.M,
)


def _candidate_notices(output, candidate_path):
    """Only attribute a source location inside the current tool's candidate file."""
    if candidate_path is None:
        return
    candidate_path = Path(candidate_path).resolve()
    for match in _SOURCE_NOTICE.finditer(output):
        severity, code, message, path, line = match.groups()
        if (candidate_path.parent / path).resolve() == candidate_path:
            yield severity.upper(), code.upper(), message, int(line)


_SYNTH_HINTS = {
    "SYNTH 8-10929": re.compile(r"literal value .+ truncated to fit in \d+ bits?", re.I),
    "SYNTH 8-151": re.compile(r"case item .+ is unreachable", re.I),
}


def synthesis_hints(output, candidate_path):
    """Return bounded source warnings, independently of the synthesis verdict."""
    hints = []
    for severity, code, message, line in _candidate_notices(output, candidate_path):
        pattern = _SYNTH_HINTS.get(code)
        if severity not in ("WARNING", "CRITICAL WARNING") or not pattern or not pattern.fullmatch(message):
            continue
        hint = {"code": code, "source_line": line, "message": message[:240]}
        if hint not in hints:
            hints.append(hint)
            if len(hints) == 8:
                break
    return hints


def classify_tool_failure(output: str, *, candidate_path=None) -> str:
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
    if any(
        severity == "ERROR" and code == "VRFC 10-3380"
        and re.fullmatch(r"""identifier ['"][^'"\r\n]+['"] is used before its declaration""", message, re.I)
        for severity, code, message, _ in _candidate_notices(output, candidate_path)
    ):
        return "code"
    if re.search(
        r"^\s*ERROR:\s*\[VRFC 10-3365\]\s+generate loop index ['\"][^'\"\r\n]+['\"] "
        r"is not defined as a genvar(?:\s*\[[^\r\n]+\])?\s*$",
        output,
        re.IGNORECASE | re.MULTILINE,
    ):
        return "code"
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
        r"ERROR:\s*\[VRFC 10-9623\][^\n]*unexpected non-printable character with the hex value",
        output,
        re.IGNORECASE,
    ) or re.search(
        r"ERROR:\s*\[VRFC 10-8549\][^\n]*SystemVerilog \d{4} keyword ['\"][^'\"\n]+['\"] used in incorrect context",
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


def classify_functional_failure(
    output: str, *, candidate_code: str = "", top: str | None = None
) -> str:
    """Attribute compiler failures without blaming RTL for generated-driver bugs.

    A driver connection diagnostic identifies the connection site, not which side
    violates its contract. The candidate can disambiguate a missing direction;
    an explicit inout or an unavailable source remains unresolved.
    """
    if classify_tool_failure(output) == "environment":
        return "environment"
    if re.search(
        r"(?:error while loading shared libraries|failed to (?:launch|execute)|"
        r"(?:xvlog|xelab|xsim): (?:command )?not found)",
        output,
        re.IGNORECASE,
    ):
        return "environment"

    diagnostics = []
    for line in output.splitlines():
        match = re.search(r"\b(?:ERROR|FATAL):\s*\[([^\]]+)\]\s*(.*)", line, re.I)
        if match is not None:
            code, message = match.groups()
            diagnostics.append((" ".join(code.upper().split()), message))

    missing_directions = set()
    if candidate_code:
        from .interface import parse_module_interface

        actual = parse_module_interface(candidate_code, top=top)
        missing_directions = {
            port.name
            for port in actual.ports
            if port.direction == "unknown"
            and f"port {port.name!r} has no direction declaration" in actual.warnings
        }

    connection_errors = any(code == "VRFC 10-3595" for code, _ in diagnostics)
    causes = set()
    unresolved = False
    for code, message in diagnostics:
        if code == "XSIM 43-3322" or re.search(
            r"(?:ignored due to previous errors|failed due to (?:earlier|previous) errors)",
            message,
            re.IGNORECASE,
        ):
            continue
        location = re.search(
            r"\[(?:[^\]\n]*[/\\])?(solution|driver)\.sv:\d+(?::\d+)?\]",
            message,
            re.IGNORECASE,
        )
        if code == "VRFC 10-3595":
            port = re.search(r"inout port ['\"]([A-Za-z_]\w*)['\"]", message)
            if location and location.group(1).lower() == "driver" and port:
                if port.group(1) in missing_directions:
                    causes.add("code")
                else:
                    unresolved = True
                continue
        # These generated drive variables become multiply driven when an input
        # connection is interpreted as inout; retain its primary error above.
        if connection_errors and code == "VRFC 10-3823" and re.search(
            r"variable ['\"]rtla_c\d+_", message
        ):
            continue
        if location is None:
            unresolved = True
        elif location.group(1).lower() == "solution":
            causes.add("code")
        elif re.search(
            r"(?:cannot find port|port .*not found|module .*not found|"
            r"cannot be connected|port .*type mismatch)",
            message,
            re.IGNORECASE,
        ):
            unresolved = True
        else:
            causes.add("checker")
    if not unresolved and len(causes) == 1:
        return causes.pop()
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
    # Preserve an explicit override; otherwise honor the official image's
    # XILINX_VIVADO variable without assuming its versioned directory layout.
    if os.environ.get("RTL_TOOL_BIN"):
        return shutil.which(name, path=os.environ["RTL_TOOL_BIN"])
    found = shutil.which(name)
    if found or not os.environ.get("XILINX_VIVADO"):
        return found
    return shutil.which(name, path=str(Path(os.environ["XILINX_VIVADO"]) / "bin"))


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
    commands, logs, outcomes, executions = [], [], [], []
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
            candidate_path = Path(work, "solution.sv").resolve()
            candidate_path.write_text(candidate.code, encoding="utf-8")
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
                        details=knowledge_details(executions),
                    )
                commands.append(command)
                result = ctx.processes.run(
                    command, cwd=work, timeout_s=ctx.budget.timeout(remaining)
                )
                output = process_output(result)
                outcomes.append(output)
                executions.append(
                    (command, output, process_status(result), result.rc)
                )
                if getattr(result, "log_path", None):
                    logs.append(str(result.log_path))
                if process_status(result) != "ok":
                    break
            probes = (
                version_probes(ctx, executions, deadline=deadline, cwd=work)
                if ctx.store.get("knowledge_rag_enabled", False)
                else {}
            )
    output = "\n".join(outcomes)
    status = process_status(result)
    classification = classify_tool_failure(output, candidate_path=candidate_path)
    failure = (
        "timeout"
        if status == "timeout"
        else "environment"
        if status == "unavailable"
        else classification
        if status == "failed"
        else "unknown"
    )
    # A successful process with a license failure is still unavailable evidence.
    if classification == "environment":
        failure, status = "environment", "unavailable"
    elif status == "ok" and re.search(r"(?im)^\s*(?:ERROR|FATAL):", output):
        failure = classification
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
            **({"synthesis_hints": synthesis_hints(output, candidate_path)} if kind == "synth" else {}),
            **knowledge_details(executions, version_probes=probes),
            "candidate_hash": candidate.code_hash,
            "source_binding": {"candidate_sha256": candidate.code_hash,
                               "paths": ["solution.sv", str(candidate_path)]},
            "tool_version": version.group(1) if version else None,
        },
    )


def lint(ctx, candidate, *, timeout_s=300.0):
    return _check(ctx, candidate, "lint", timeout_s)


def synth(ctx, candidate, *, timeout_s=600.0):
    return _check(ctx, candidate, "synth", timeout_s)
