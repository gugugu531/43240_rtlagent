"""Feedback the agent can obtain without the official testbench.

Three tools, in increasing cost:

    check_interface()   pure Python, no tools, microseconds
    lint()              xvlog + xelab on the DUT alone, seconds
    synth()             synth_design, tens of seconds

The official testbench stays with the organisers and is what decides L2, so
nothing here can tell you whether the design is functionally correct. What the
first tool *can* tell you is whether the module will elaborate against that
testbench at all -- and on the RTL side that is worth more than it sounds:

    wrong port name   ERROR: [VRFC 10-3180] cannot find port 'q' on this module
    wrong module name ERROR: [VRFC 10-2063] Module <TopModule> not found

Both kill elaboration, so both score L0. There is no "compiles but does not
link" middle ground the way there is in C++. A deterministic textual check
against the declared interface costs nothing and removes the entire failure
class -- which is also a demonstration that a skill need not involve a model.

If Vivado is not installed, lint() and synth() return status=unavailable with a
clear reason and the agent falls back to fewer rounds. check_interface() still
works. They never pretend to have checked something they did not.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import re
import signal
import shutil
import subprocess
import tempfile
import textwrap
import time
from typing import Literal, Sequence

from .interface import (
    check_interface_result,
    parse_module_interface,
    parse_prompt_interface,
)

PART = os.environ.get("RTL_PART", "xczu3eg-sbva484-1-e")
TOOL_SUMMARY_LIMIT = 2000
ToolStatus = Literal["ok", "failed", "timeout", "unavailable"]


@dataclass(frozen=True)
class ToolResult:
    """Standard result of one logical RTL tool step.

    ``command`` is nested because lint consists of xvlog followed by xelab.
    Full logs stay out of this object and trace; in debug mode the path points
    to a file in the retained work directory.
    """

    tool: str
    command: tuple[tuple[str, ...], ...]
    rc: int
    status: ToolStatus
    elapsed_s: float
    summary: str
    full_log_path: str | None = None
    work_dir: str | None = None

    def __iter__(self):
        """Keep the previous ``rc, summary = result`` call shape working."""
        yield self.rc
        yield self.summary

    def trace_dict(self) -> dict[str, object]:
        fields: dict[str, object] = {
            "tool": self.tool,
            "command": [list(command) for command in self.command],
            "rc": self.rc,
            "status": self.status,
            "elapsed_s": round(self.elapsed_s, 3),
            "excerpt": self.summary[:TOOL_SUMMARY_LIMIT],
        }
        if self.full_log_path is not None:
            fields["full_log_path"] = self.full_log_path
        if self.work_dir is not None:
            fields["work_dir"] = self.work_dir
        return fields


@dataclass(frozen=True)
class _CommandOutcome:
    command: tuple[str, ...]
    rc: int
    status: ToolStatus
    elapsed_s: float
    output: str


class RtlToolchain:
    def __init__(self) -> None:
        self.xvlog = shutil.which("xvlog")
        self.xelab = shutil.which("xelab")
        self.vivado = shutil.which("vivado")
        self.reason = ""
        missing = [n for n, p in (("xvlog", self.xvlog), ("xelab", self.xelab),
                                  ("vivado", self.vivado)) if not p]
        if missing:
            self.reason = (f"not on PATH: {', '.join(missing)}; "
                           "source your Vivado settings64.sh")

    @property
    def available(self) -> bool:
        return not self.reason

    # ------------------------------------------------------------------ lint

    def lint(self, source: str, top: str,
             timeout_s: float = 300.0) -> ToolResult:
        """Analyze and elaborate the DUT on its own.

        The timeout covers the whole logical lint step. Work package B will
        supply it from one shared deadline without changing this interface.
        """
        if not self.available:
            return _unavailable("lint", f"vivado unavailable: {self.reason}")
        invalid = _validate_top(top, "lint")
        if invalid is not None:
            return invalid

        try:
            work = _make_work_dir("agent_lint_")
        except OSError as exc:
            return _unavailable("lint", f"could not create work directory: {exc}")
        keep_work = os.environ.get("AGENT_KEEP_WORK") == "1"
        try:
            src = os.path.join(work, "solution.sv")
            with open(src, "w", encoding="utf-8") as fh:
                fh.write(source)

            commands = [
                [self.xvlog or "xvlog", "--sv", "solution.sv"],
                [self.xelab or "xelab", top, "-s", "dutsim"],
            ]
            started = time.monotonic()
            outcomes = [_run_command(commands[0], work, timeout_s)]
            if outcomes[0].status == "ok":
                remaining = max(0.0, timeout_s - (time.monotonic() - started))
                outcomes.append(_run_command(commands[1], work, remaining))
            return _build_result("lint", outcomes, work, keep_work)
        except OSError as exc:
            return _unavailable("lint", f"could not prepare lint input: {exc}")
        finally:
            if not keep_work:
                shutil.rmtree(work, ignore_errors=True)

    # ----------------------------------------------------------------- synth

    def synth(self, source: str, top: str,
              timeout_s: float = 900.0) -> ToolResult:
        if not self.available:
            return _unavailable("synth", f"vivado unavailable: {self.reason}")
        invalid = _validate_top(top, "synth")
        if invalid is not None:
            return invalid

        try:
            work = _make_work_dir("agent_synth_")
        except OSError as exc:
            return _unavailable("synth", f"could not create work directory: {exc}")
        keep_work = os.environ.get("AGENT_KEEP_WORK") == "1"
        try:
            with open(os.path.join(work, "solution.sv"), "w", encoding="utf-8") as fh:
                fh.write(source)
            with open(os.path.join(work, "synth.tcl"), "w", encoding="utf-8") as fh:
                fh.write(
                    textwrap.dedent(
                        f"""\
                        read_verilog -sv solution.sv
                        synth_design -top {top} -part {PART} -mode out_of_context
                        """
                    )
                )
            outcome = _run_command(
                [self.vivado or "vivado", "-mode", "batch", "-source", "synth.tcl",
                 "-nojournal", "-log", "synth.log"],
                work, timeout_s,
            )
            if outcome.status == "ok" and "Synthesis finished" not in outcome.output:
                outcome = _CommandOutcome(
                    command=outcome.command,
                    rc=1,
                    status="failed",
                    elapsed_s=outcome.elapsed_s,
                    output=outcome.output + "\n[agent] synthesis success marker missing",
                )
            return _build_result("synth", [outcome], work, keep_work)
        except OSError as exc:
            return _unavailable("synth", f"could not prepare synthesis input: {exc}")
        finally:
            if not keep_work:
                shutil.rmtree(work, ignore_errors=True)


# ------------------------------------------------------- interface checking

def ports_from_prompt(prompt: str) -> tuple[str | None, list[tuple[str, int, str]]]:
    """Compatibility wrapper used by the mock model client."""
    spec = parse_prompt_interface(prompt)
    ports = [
        (port.direction, port.width or 1, port.name) for port in spec.ports
    ]
    return spec.module_name, ports


def check_interface(source: str, interface: str,
                    prompt: str = "") -> tuple[int, str]:
    """Compatibility wrapper returning the previous ``(rc, summary)`` shape."""
    result = check_interface_result(source, interface, prompt)
    return result.rc, result.summary


def _ports(text: str) -> tuple[str | None, list[tuple[str, int, str]]]:
    """Legacy tuple view for older internal callers."""
    spec = parse_module_interface(text)
    ports = [
        (port.direction, port.width or 1, port.name) for port in spec.ports
    ]
    return spec.module_name, ports


# --------------------------------------------------------------------- utils


def run_command(tool: str, cmd: Sequence[str], cwd: str,
                timeout_s: float, full_log_path: str | None = None,
                terminate_grace_s: float = 1.0) -> ToolResult:
    """Run one command in its own process group and return a public result."""
    outcome = _run_command(cmd, cwd, timeout_s, terminate_grace_s)
    if full_log_path is not None:
        try:
            _write_full_log(full_log_path, [outcome])
        except OSError:
            full_log_path = None
    return ToolResult(
        tool=tool,
        command=(outcome.command,),
        rc=outcome.rc,
        status=outcome.status,
        elapsed_s=outcome.elapsed_s,
        summary=summarize_log(outcome.output),
        full_log_path=full_log_path,
        work_dir=cwd if full_log_path is not None else None,
    )


def _run_command(cmd: Sequence[str], cwd: str, timeout_s: float,
                 terminate_grace_s: float = 1.0) -> _CommandOutcome:
    command = tuple(str(part) for part in cmd)
    started = time.monotonic()
    if not command:
        return _CommandOutcome(command, -1, "unavailable", 0.0,
                               "[agent] empty command")
    if timeout_s <= 0:
        return _CommandOutcome(
            command, 124, "timeout", 0.0,
            f"[agent] {command[0]} has no time remaining",
        )

    try:
        proc = subprocess.Popen(
            command, cwd=cwd, start_new_session=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            errors="replace",
        )
    except OSError as exc:
        return _CommandOutcome(
            command, -1, "unavailable", time.monotonic() - started,
            f"[agent] could not launch {command[0]}: {exc}",
        )

    try:
        output, _ = proc.communicate(timeout=timeout_s)
        status: ToolStatus = "ok" if proc.returncode == 0 else "failed"
        return _CommandOutcome(
            command, proc.returncode, status,
            time.monotonic() - started, output or "",
        )
    except subprocess.TimeoutExpired as exc:
        partial = _timeout_output(exc)
        _terminate_process_group(proc, terminate_grace_s)
        tail, _ = proc.communicate()
        output = partial
        if tail and tail not in output:
            output += tail
        output += f"\n[agent] {command[0]} timed out after {timeout_s:.3f}s"
        return _CommandOutcome(
            command, 124, "timeout", time.monotonic() - started, output,
        )


def _terminate_process_group(proc: subprocess.Popen[str], grace_s: float) -> None:
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + max(0.0, grace_s)
    while time.monotonic() < deadline:
        if not _process_group_exists(proc.pid):
            break
        time.sleep(min(0.02, max(0.0, deadline - time.monotonic())))
    try:
        if _process_group_exists(proc.pid):
            os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    proc.wait()


def _process_group_exists(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False


def _timeout_output(exc: subprocess.TimeoutExpired) -> str:
    output = exc.output or ""
    if isinstance(output, bytes):
        return output.decode(errors="replace")
    return output


def _build_result(tool: str, outcomes: Sequence[_CommandOutcome],
                  work: str, keep_work: bool) -> ToolResult:
    commands = tuple(outcome.command for outcome in outcomes)
    final = outcomes[-1]
    full_output = "\n".join(outcome.output for outcome in outcomes)
    full_log_path = os.path.join(work, f"{tool}.full.log") if keep_work else None
    if full_log_path is not None:
        try:
            _write_full_log(full_log_path, outcomes)
        except OSError:
            full_log_path = None
    return ToolResult(
        tool=tool,
        command=commands,
        rc=final.rc,
        status=final.status,
        elapsed_s=sum(outcome.elapsed_s for outcome in outcomes),
        summary=summarize_log(full_output),
        full_log_path=full_log_path,
        work_dir=work if keep_work else None,
    )


def _write_full_log(path: str, outcomes: Sequence[_CommandOutcome]) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        for index, outcome in enumerate(outcomes):
            if index:
                fh.write("\n")
            fh.write("$ " + " ".join(outcome.command) + "\n")
            fh.write(outcome.output)
            if outcome.output and not outcome.output.endswith("\n"):
                fh.write("\n")


def _unavailable(tool: str, reason: str) -> ToolResult:
    return ToolResult(tool, (), -1, "unavailable", 0.0, reason)


_VERILOG_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


def _validate_top(top: str, tool: str) -> ToolResult | None:
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


def _make_work_dir(prefix: str) -> str:
    scratch = _scratch_dir()
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
