"""Feedback the agent can obtain without the official testbench.

Three tools, in increasing cost:

    interface check     pure Python (agent.core.interface), microseconds
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
clear reason and the agent stops with its current candidate. The interface check
still works. They never pretend to have checked something they did not.
"""

from __future__ import annotations

import os
import re
import signal
import shutil
import subprocess
import tempfile
import textwrap
import time
from typing import Sequence

from agent.core.interface import (
    parse_prompt_interface,
)

from agent.core import tool as tool_contract
from agent.core.tool import TOOL_SUMMARY_LIMIT, ToolResult, ToolStatus
from agent.services import tool_support
from agent.services.tool_support import (
    CommandOutcome, build_result, make_work_dir, unavailable, validate_top,
    classify_tool_failure, summarize_log,
)

# Existing imports remain valid; implementations live in the shared support module.
_CommandOutcome = CommandOutcome
_build_result = build_result
_make_work_dir = make_work_dir
_unavailable = unavailable
_validate_top = validate_top


def _implementation_sources() -> tuple[bytes, ...]:
    """Include the compiler adapter and diagnostics in cache identity."""
    from pathlib import Path
    return tuple(Path(path).read_bytes() for path in
                 (__file__, tool_contract.__file__, tool_support.__file__))


PART = os.environ.get("RTL_PART", "xczu3eg-sbva484-1-e")
class RtlToolchain:
    def __init__(self, *, config=None, executor=None, log_dir=None, redactor=None) -> None:
        from agent.core.config import ToolConfig
        self.config = config or ToolConfig.from_env()
        self.executor, self.log_dir, self.redactor = executor, log_dir, redactor
        search = self.config.bin_dir if self.config.bin_dir is not None else os.environ.get("PATH", "")
        self.xvlog = shutil.which("xvlog", path=search)
        self.xelab = shutil.which("xelab", path=search)
        self.vivado = shutil.which("vivado", path=search)
        self.reason = ""
        missing = [n for n, p in (("xvlog", self.xvlog), ("xelab", self.xelab),
                                  ("vivado", self.vivado)) if not p]
        if missing:
            self.reason = (f"not on PATH: {', '.join(missing)}; "
                           "source your Vivado settings64.sh")

    def fingerprint(self):
        import hashlib
        paths = [self.xvlog, self.xelab, self.vivado]
        if any(path is None for path in paths):
            return None
        try:
            identity = [(p, os.stat(p).st_size, os.stat(p).st_mtime_ns) for p in paths]
            return hashlib.sha256(repr((identity, self.config.public_dict(), sorted(os.environ.items()), _implementation_sources())).encode()).hexdigest()
        except OSError:
            return None

    def run_command(self, cmd: Sequence[str], cwd: str, timeout_s: float) -> CommandOutcome:
        if self.executor is None:
            return _run_command(cmd, cwd, timeout_s)
        from agent.core.process import ProcessRequest
        result = self.executor.run(ProcessRequest(tuple(cmd), cwd, timeout_s))
        return CommandOutcome(tuple(cmd), result.rc, result.status, result.elapsed_s, result.output,
                               result.log_path)

    def _command(self, cmd, cwd, timeout_s):
        """Compatibility entry point for existing development callers."""
        return self.run_command(cmd, cwd, timeout_s)

    def identify(self, timeout_s=5.0):
        """Explicit opt-in probe, bounded and executed by the managed executor."""
        started = time.monotonic()
        tools = {}
        with tempfile.TemporaryDirectory(prefix='agent_identity_', dir=self.config.temp_dir) as work:
            for name, executable in (('xvlog', self.xvlog), ('xelab', self.xelab), ('vivado', self.vivado)):
                remaining = timeout_s - (time.monotonic() - started)
                if executable is None or remaining <= 0:
                    tools[name] = dict(version=None, status='unavailable')
                    continue
                result = self.run_command([executable, '-version'], work, remaining)
                match = re.search(r'(?:Vivado(?: Simulator)?|xvlog|xelab)\s+v?(\d{4}\.\d+)', result.output, re.I)
                tools[name] = dict(version=match.group(1) if match and result.status == 'ok' else None,
                                   status=result.status, command=list(result.command), log_path=result.log_path)
        return dict(fingerprint=self.fingerprint(), tools=tools, elapsed_s=time.monotonic() - started)

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
            return unavailable("lint", f"vivado unavailable: {self.reason}")
        invalid = validate_top(top, "lint")
        if invalid is not None:
            return invalid

        try:
            work = make_work_dir("agent_lint_", self.config.temp_dir)
        except OSError as exc:
            return unavailable("lint", f"could not create work directory: {exc}")
        keep_work = self.config.keep_work
        try:
            src = os.path.join(work, "solution.sv")
            with open(src, "w", encoding="utf-8") as fh:
                fh.write(source)

            commands = [
                [self.xvlog or "xvlog", "--sv", "solution.sv"],
                [self.xelab or "xelab", top, "-s", "dutsim"],
            ]
            started = time.monotonic()
            outcomes = [self.run_command(commands[0], work, timeout_s)]
            if outcomes[0].status == "ok":
                remaining = max(0.0, timeout_s - (time.monotonic() - started))
                outcomes.append(self.run_command(commands[1], work, remaining))
            return build_result("lint", outcomes, work, keep_work, self.log_dir, self.redactor)
        except OSError as exc:
            return unavailable("lint", f"could not prepare lint input: {exc}")
        finally:
            if not keep_work:
                shutil.rmtree(work, ignore_errors=True)

    # ----------------------------------------------------------------- synth

    def synth(self, source: str, top: str,
              timeout_s: float = 900.0) -> ToolResult:
        if not self.available:
            return unavailable("synth", f"vivado unavailable: {self.reason}")
        invalid = validate_top(top, "synth")
        if invalid is not None:
            return invalid

        try:
            work = make_work_dir("agent_synth_", self.config.temp_dir)
        except OSError as exc:
            return unavailable("synth", f"could not create work directory: {exc}")
        keep_work = self.config.keep_work
        try:
            with open(os.path.join(work, "solution.sv"), "w", encoding="utf-8") as fh:
                fh.write(source)
            with open(os.path.join(work, "synth.tcl"), "w", encoding="utf-8") as fh:
                fh.write(
                    textwrap.dedent(
                        f"""\
                        read_verilog -sv solution.sv
                        synth_design -top {top} -part {self.config.part} -mode out_of_context
                        """
                    )
                )
            outcome = self.run_command(
                [self.vivado or "vivado", "-mode", "batch", "-source", "synth.tcl",
                 "-nojournal", "-log", "synth.log"],
                work, timeout_s,
            )
            if outcome.status == "ok" and "Synthesis finished" not in outcome.output:
                outcome = CommandOutcome(
                    command=outcome.command,
                    rc=1,
                    status="failed",
                    elapsed_s=outcome.elapsed_s,
                    output=outcome.output + "\n[agent] synthesis success marker missing",
                )
            return build_result("synth", [outcome], work, keep_work, self.log_dir, self.redactor)
        except OSError as exc:
            return unavailable("synth", f"could not prepare synthesis input: {exc}")
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


# --------------------------------------------------------------------- utils


def _run_command(cmd: Sequence[str], cwd: str, timeout_s: float,
                 terminate_grace_s: float = 1.0) -> CommandOutcome:
    command = tuple(str(part) for part in cmd)
    started = time.monotonic()
    if not command:
        return CommandOutcome(command, -1, "unavailable", 0.0,
                               "[agent] empty command")
    if timeout_s <= 0:
        return CommandOutcome(
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
        return CommandOutcome(
            command, -1, "unavailable", time.monotonic() - started,
            f"[agent] could not launch {command[0]}: {exc}",
        )

    try:
        output, _ = proc.communicate(timeout=timeout_s)
        status: ToolStatus = "ok" if proc.returncode == 0 else "failed"
        return CommandOutcome(
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
        return CommandOutcome(
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
