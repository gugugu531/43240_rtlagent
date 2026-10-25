"""Neutral public-port sampling. A complete trace is not a functional verdict."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
from pathlib import Path
import re
import tempfile
import time
from typing import Annotated, Literal
import uuid

from pydantic import Field, ValidationError, model_validator

from agent.runtime.budget import BudgetExhausted
from .suite.schema import Case, Contract, LegacyClock, Name, Port
from .suite.semantics import SuiteError, _name


class SamplingPlan(Contract):
    schema_version: Literal[1]
    ports: Annotated[dict[Name, Port], Field(min_length=1, max_length=64)]
    clock: LegacyClock | None = None
    cases: Annotated[list[Case], Field(min_length=1, max_length=8)]

    @model_validator(mode="before")
    @classmethod
    def exact_version(cls, value):
        if isinstance(value, dict) and type(value.get("schema_version")) is not int:
            raise ValueError("schema_version must be integer 1")
        return value

    @model_validator(mode="after")
    def cross_fields(self):
        for name in self.ports:
            _name(name)
        inputs = {n for n, p in self.ports.items() if p.direction == "input"}
        if not any(p.direction == "output" for p in self.ports.values()):
            raise ValueError("sampling needs at least one output")
        if self.clock:
            if self.clock.port not in inputs or self.ports[self.clock.port].width != 1:
                raise ValueError("clock must be a one-bit input")
            inputs.remove(self.clock.port)
        ids = set()
        samples = events = 0
        for case in self.cases:
            if case.id in ids:
                raise ValueError("case ids must be unique")
            ids.add(case.id)
            if len(case.steps) > (32 if self.clock else 256):
                raise ValueError("sampling limit is 32 sequential or 256 combinational events per case")
            for step in case.steps:
                if step.edges is not None:
                    raise ValueError("sampling v1 uses single clock edge boolean, not edges")
                if set(step.inputs) != inputs:
                    raise ValueError("each event must drive every non-clock input exactly once")
                for name, number in step.inputs.items():
                    width = self.ports[name].width
                    if not -(1 << (width - 1)) <= number < (1 << width):
                        raise ValueError(f"input {name} exceeds declared width")
                events += 1
                samples += step.sample
        if events > 256 or not samples:
            raise ValueError("sampling needs a sampled event and at most 256 total events")
        return self


def _plain(plan):
    return plan.model_dump(mode="json") if isinstance(plan, SamplingPlan) else plan


def validate_sampling_plan(plan, *, expected_interface=None):
    """Strict structural checks; bind to a complete public interface when supplied."""
    try:
        value = SamplingPlan.model_validate(_plain(plan)).model_dump(mode="json")
    except (ValidationError, TypeError) as error:
        raise SuiteError(str(error)) from error
    if expected_interface is not None:
        if hasattr(expected_interface, "ports"):
            if not expected_interface.parsed or not expected_interface.complete:
                raise SuiteError("sampling requires a complete resolved public interface")
            actual = {p.name: (p.direction, p.width) for p in expected_interface.ports}
        elif isinstance(expected_interface, dict):
            actual = {n: (p["direction"], p["width"]) for n, p in expected_interface.items()}
        else:
            raise SuiteError("invalid public interface")
        declared = {n: (p["direction"], p["width"]) for n, p in value["ports"].items()}
        if actual != declared:
            raise SuiteError("sampling ports differ from the resolved public interface")
    return value


def sampling_plan_from_suite(suite):
    """Adapt a single-clock behavior suite, without executing its expected model."""
    from .suite.schema import validate_suite

    suite = validate_suite(suite)
    clock = suite.get("clock")
    clocks = suite.get("clocks") or {}
    if len(clocks) > 1:
        raise SuiteError("neutral sampling v1 does not support multiple clocks")
    if clocks:
        name, config = next(iter(clocks.items()))
        clock = {"port": name, "edge": config["edge"]}
    cases = []
    for case in suite["cases"]:
        steps = []
        for step in case["steps"]:
            steps.append({
                "inputs": step["inputs"], "sample": step.get("sample", True),
                "edge": bool(step["edges"]) if clocks else step.get("edge", True),
            })
        cases.append({"id": case["id"], "requirements": case.get("requirements", []), "steps": steps})
    return validate_sampling_plan({"schema_version": 1, "ports": suite["ports"], "clock": clock, "cases": cases})


def sampling_hash(plan):
    return hashlib.sha256(json.dumps(validate_sampling_plan(plan), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def build_observation_testbench(plan, top, marker):
    plan = validate_sampling_plan(plan)
    _name(top)
    if not re.fullmatch(r"[a-f0-9]{16}", marker):
        raise SuiteError("invalid observation marker")
    ports = dict(sorted(plan["ports"].items()))
    clock = plan["clock"]
    lines = ["`timescale 1ns/1ps", "module rtla_observe_tb;"]
    for ci, case in enumerate(plan["cases"]):
        for name, port in ports.items():
            kind = "reg" if port["direction"] == "input" else "wire"
            lines.append(f"{kind} [{port['width'] - 1}:0] rtla_c{ci}_{name};")
        lines.append(f"{top} rtla_dut{ci} (" + ", ".join(f".{n}(rtla_c{ci}_{n})" for n in ports) + ");")
        lines.append("initial begin")
        if clock:
            lines.append(f"rtla_c{ci}_{clock['port']} = 1'b{int(clock['edge'] != 'posedge')};")
        tick = 0
        for si, step in enumerate(case["steps"]):
            lines.append("#5;")
            for name, number in sorted(step["inputs"].items()):
                width = ports[name]["width"]
                lines.append(f"rtla_c{ci}_{name} = {width}'h{number & ((1 << width) - 1):x};")
            lines.append("#4;")
            for phase in ("pre", "post"):
                if phase == "post":
                    lines.append("#1;")
                    if clock and step["edge"]:
                        lines.append(f"rtla_c{ci}_{clock['port']} <= 1'b{int(clock['edge'] == 'posedge')};")
                    tick += int(step["edge"] if clock else True)
                    lines.append("#1;")
                fmt = f"RTLA_OBS_{marker}|{ci}|{si}|{tick}|{phase}|" + "|".join("b:%b" for _ in ports)
                lines.append(f'$display("{fmt}", ' + ", ".join(f"rtla_c{ci}_{n}" for n in ports) + ");")
            lines.append("#4;")
            if clock:
                lines.append(f"rtla_c{ci}_{clock['port']} <= 1'b{int(clock['edge'] != 'posedge')};")
        lines.append("end")
    duration = max(len(c["steps"]) for c in plan["cases"]) * 15 + 10
    lines += [f'initial begin #{duration}; $display("RTLA_OBS_DONE_{marker}"); $finish; end', "endmodule"]
    return "\n".join(lines) + "\n"


@dataclass
class TraceRun:
    status: str
    plan_hash: str
    candidate_hash: str
    execution_id: str
    rows: list[dict] = field(default_factory=list)
    summary: str = ""
    failure_kind: str = "unknown"
    artifacts: dict = field(default_factory=dict)
    command: list = field(default_factory=list)
    log_paths: list = field(default_factory=list)
    elapsed_s: float = 0.0
    rc: int | None = None
    sampling_version: int = 1

    def public_dict(self):
        return asdict(self)


def parse_observations(text, plan, marker, *, candidate_hash="", execution_id=""):
    """Reject malformed, duplicated, missing and out-of-order samples; preserve X/Z."""
    plan = validate_sampling_plan(plan)
    if not re.fullmatch(r"[a-f0-9]{16}", marker):
        raise SuiteError("invalid observation marker")
    ports = sorted(plan["ports"])
    expected = {}
    for ci, case in enumerate(plan["cases"]):
        tick = 0
        for si, step in enumerate(case["steps"]):
            for phase in ("pre", "post"):
                if phase == "post":
                    tick += int(step["edge"] if plan["clock"] else True)
                expected[ci, si, phase] = tick
    prefix, done = f"RTLA_OBS_{marker}|", f"RTLA_OBS_DONE_{marker}"
    seen, ordered, last = {}, [], {}
    completed = False
    for line in text.splitlines():
        if line == done:
            if completed or len(seen) != len(expected):
                raise SuiteError("duplicate or premature observation completion marker")
            completed = True
            continue
        if not line.startswith(prefix):
            continue
        if completed:
            raise SuiteError("observation emitted after completion")
        parts = line[len(prefix):].split("|")
        if len(parts) != len(ports) + 4 or not all(re.fullmatch(r"\d+", p) for p in parts[:3]):
            raise SuiteError("malformed observation event")
        ci, si, tick = map(int, parts[:3])
        phase = parts[3]
        key = ci, si, phase
        if key not in expected or key in seen or tick != expected[key]:
            raise SuiteError("duplicate or unexpected observation event/tick/phase")
        ordinal = si * 2 + int(phase == "post")
        if ordinal != last.get(ci, -1) + 1:
            raise SuiteError("out-of-order observation event")
        last[ci] = ordinal
        values = {}
        for name, token in zip(ports, parts[4:]):
            width = plan["ports"][name]["width"]
            if not re.fullmatch(r"b:[01xXzZ]{" + str(width) + "}", token):
                raise SuiteError("observation bit value or width differs from plan")
            bits = known = 0
            for char in token[2:]:
                bits, known = bits << 1, known << 1
                if char in "01":
                    bits, known = bits | int(char), known | 1
            values[name] = {"bits": bits, "known": known, "width": width}
        step = plan["cases"][ci]["steps"][si]
        for name, port in plan["ports"].items():
            if port["direction"] != "input":
                continue
            if plan["clock"] and name == plan["clock"]["port"]:
                active = phase == "post" and step["edge"]
                number = int(plan["clock"]["edge"] == "posedge") if active else int(plan["clock"]["edge"] != "posedge")
            else:
                number = step["inputs"][name] & ((1 << port["width"]) - 1)
            if values[name] != {"bits": number, "known": (1 << port["width"]) - 1, "width": port["width"]}:
                raise SuiteError("observed input differs from the fixed stimulus")
        row = {"case_id": plan["cases"][ci]["id"], "case_index": ci, "step": si,
               "clock_tick": tick, "phase": phase, "sample": step["sample"],
               "edge": step["edge"] if plan["clock"] else False, "values": values}
        seen[key] = row
        ordered.append(row)
    if len(seen) != len(expected) or not completed:
        raise SuiteError("observation trace or completion marker is incomplete")
    return TraceRun("complete", sampling_hash(plan), candidate_hash, execution_id, ordered,
                    summary=f"collected {len(ordered)} pre/post samples; no expected behavior checked")


def observe(ctx, candidate, plan, *, timeout_s=300.0):
    """Run one bounded observation through managed processes, without any oracle."""
    from .interface import parse_expected_interface
    from .vivado import (executable, scratch_directory, tool_slot, process_status,
                         process_output, classify_tool_failure, classify_functional_failure)

    started = time.monotonic()
    identity = uuid.uuid4().hex
    marker = identity[:16]
    result = TraceRun("error", "", candidate.code_hash, identity)
    stem = f"observations/{candidate.id}-{identity}"

    def finish(status, summary, failure_kind="unknown", **fields):
        result.status, result.summary, result.failure_kind = status, summary, failure_kind
        result.elapsed_s = time.monotonic() - started
        for key, value in fields.items():
            setattr(result, key, value)
        path = stem + "/result.json"
        result.artifacts["result"] = str(ctx.record.record_dir / path) if hasattr(ctx.record, "record_dir") else path
        saved = ctx.record.write_json(path, result.public_dict())
        result.artifacts["result"] = str(saved)
        return result

    try:
        plan = validate_sampling_plan(plan, expected_interface=parse_expected_interface(ctx.task.interface, ctx.task.prompt, top=ctx.task.top))
        result.plan_hash = sampling_hash(plan)
        driver = build_observation_testbench(plan, ctx.task.top, marker)
    except (SuiteError, ValueError, TypeError) as error:
        return finish("error", str(error), "checker")
    result.artifacts["plan"] = str(ctx.record.write_json(stem + "/plan.json", plan))
    result.artifacts["driver"] = str(ctx.record.write_text(stem + "/driver.sv", driver))
    tools = {name: executable(name) for name in ("xvlog", "xelab", "xsim")}
    missing = [name for name, path in tools.items() if not path]
    if missing:
        return finish("unavailable", "observation tools unavailable: " + ", ".join(missing), "environment")
    try:
        timeout = ctx.budget.timeout(timeout_s)
        deadline = started + timeout
        with tool_slot(ctx, timeout) as acquired:
            if not acquired:
                return finish("timeout", "observation concurrency wait timed out", "timeout", rc=124)
            with tempfile.TemporaryDirectory(prefix="rtla_observe_", dir=scratch_directory()) as work:
                Path(work, "solution.sv").write_text(candidate.code, encoding="utf-8")
                Path(work, "driver.sv").write_text(driver, encoding="utf-8")
                for index, command in enumerate(((tools["xvlog"], "--sv", "solution.sv", "driver.sv"),
                    (tools["xelab"], "rtla_observe_tb", "-s", "rtla_observe_sim", "-timescale", "1ps/1ps"),
                    (tools["xsim"], "rtla_observe_sim", "-runall"))):
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return finish("timeout", "observation time limit exceeded", "timeout", rc=124)
                    result.command.append(list(command))
                    process = ctx.processes.run(command, cwd=work, timeout_s=ctx.budget.timeout(remaining))
                    output = process_output(process)
                    result.log_paths.append(str(ctx.record.write_text(stem + f"/stage-{index}.log", output)))
                    status = process_status(process)
                    environment = classify_tool_failure(output) == "environment"
                    if status != "ok" or environment or re.search(r"(?im)^\s*(?:ERROR|FATAL):", output):
                        failure = "timeout" if status == "timeout" else "environment" if status == "unavailable" or environment else classify_functional_failure(output, candidate_code=candidate.code, top=ctx.task.top)
                        return finish("timeout" if failure == "timeout" else "unavailable" if failure == "environment" else "error",
                                      f"observation stage {index} failed: " + output[-1500:], failure, rc=process.rc)
                try:
                    parsed = parse_observations(output, plan, marker, candidate_hash=candidate.code_hash, execution_id=identity)
                except SuiteError as error:
                    return finish("error", str(error), "unknown", rc=process.rc)
                result.rows = parsed.rows
                result.artifacts["rows"] = str(ctx.record.write_json(stem + "/rows.json", result.rows))
                return finish("complete", parsed.summary, rc=process.rc)
    except BudgetExhausted as error:
        return finish("timeout", str(error), "timeout", rc=124)
