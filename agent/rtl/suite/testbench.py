"""Fixed testbench generation and strict trace comparison."""

from __future__ import annotations
import hashlib
import re
import tempfile
import time
from pathlib import Path
from .schema import validate_suite
from .semantics import SuiteError, _NAME
from agent.rtl.identity import suite_hash
from .evaluate import _clocks, _edges, expected_traces, analyze_expectations
from agent.rtl.result import CheckResult


def build_testbench(suite, top, marker):
    if not _NAME.fullmatch(top) or not re.fullmatch(r"[a-f0-9]{16}", marker):
        raise SuiteError("invalid top or trace marker")
    suite = validate_suite(suite)
    ports, clocks = (
        dict(sorted(suite["ports"].items())),
        dict(sorted(_clocks(suite).items())),
    )
    outputs = sorted(n for n, p in ports.items() if p["direction"] == "output")
    lines = ["`timescale 1ns/1ps", "module rtla_tb;"]
    for ci, case in enumerate(suite["cases"]):
        for name, port in ports.items():
            kind = "reg" if port["direction"] == "input" else "wire"
            lines.append(f"{kind} [{port['width'] - 1}:0] rtla_c{ci}_{name};")
        lines.append(
            f"{top} rtla_dut{ci} ("
            + ", ".join(f".{n}(rtla_c{ci}_{n})" for n in ports)
            + ");"
        )
        lines.append("initial begin")
        for name, clock in clocks.items():
            lines.append(f"rtla_c{ci}_{name} = 1'b{int(clock['edge'] != 'posedge')};")
        for si, step in enumerate(case["steps"]):
            lines.append("#5;")
            for name, number in sorted(step["inputs"].items()):
                bits = ports[name]["width"]
                lines.append(
                    f"rtla_c{ci}_{name} = {bits}'h{number & ((1 << bits) - 1):x};"
                )
            if clocks:
                lines.append("#5;")
                for name in sorted(_edges(suite, step)):
                    # Nonblocking assignments put simultaneous clocks in one NBA update.
                    lines.append(
                        f"rtla_c{ci}_{name} <= 1'b{int(clocks[name]['edge'] == 'posedge')};"
                    )
            lines.append("#1;")
            fmt = f"RTLA_{marker}|{ci}|{si}|" + "|".join("b:%b" for _ in outputs)
            lines.append(
                f'$display("{fmt}", '
                + ", ".join(f"rtla_c{ci}_{n}" for n in outputs)
                + ");"
            )
            lines.append("#4;")
            for name, clock in clocks.items():
                lines.append(
                    f"rtla_c{ci}_{name} <= 1'b{int(clock['edge'] != 'posedge')};"
                )
        lines.append("end")
    duration = max(len(c["steps"]) for c in suite["cases"]) * 15 + 10
    lines += [f"initial begin #{duration}; $finish; end", "endmodule"]
    return "\n".join(lines) + "\n"


def _parse_value(token, width):
    binary = token.startswith("b:")
    digits = token[2:] if binary else token
    if not re.fullmatch(r"[01xXzZ]+" if binary else r"[0-9a-fA-FxXzZ]+", digits):
        raise SuiteError("invalid simulation value")
    if binary and len(digits) != width:
        raise SuiteError("binary simulation value width differs from declared width")
    value = known = 0
    stride = 1 if binary else 4
    for digit in digits:
        value <<= stride
        known <<= stride
        if digit not in "xXzZ":
            value |= int(digit, 2 if binary else 16)
            known |= (1 << stride) - 1
    full = (1 << width) - 1
    if value > full:
        raise SuiteError("simulation value exceeds declared width")
    if len(digits) * stride < width:
        # Legacy hexadecimal traces omit leading zeroes; those bits are known zero.
        known |= full ^ ((1 << (len(digits) * stride)) - 1)
    return value & full, known & full


def parse_traces(output, suite, marker, *, compare_expected=True):
    suite = validate_suite(suite)
    outputs = sorted(n for n, p in suite["ports"].items() if p["direction"] == "output")
    rows = {}
    prefix = f"RTLA_{marker}|"
    for line in output.splitlines():
        if not line.startswith(prefix):
            continue
        parts = line[len(prefix) :].strip().split("|")
        if len(parts) != len(outputs) + 2 or not all(
            re.fullmatch(r"\d+", p) for p in parts[:2]
        ):
            raise SuiteError("malformed simulation trace")
        ci, si = map(int, parts[:2])
        if (
            ci >= len(suite["cases"])
            or si >= len(suite["cases"][ci]["steps"])
            or (ci, si) in rows
        ):
            raise SuiteError("duplicate or unexpected simulation event")
        rows[ci, si] = {
            name: _parse_value(token, suite["ports"][name]["width"])
            for name, token in zip(outputs, parts[2:])
        }
    return compare_trace_rows(rows, suite, compare_expected=compare_expected)


def compare_trace_rows(rows, suite, *, compare_expected=True):
    """Compare event outputs as { (case, step): { port: (bits, known) } }.

    Both the legacy wire parser and neutral observation adapter use this entry;
    expected values are computed exclusively from the independent suite model.
    """
    suite = validate_suite(suite)
    expected_keys = {(ci, si) for ci, case in enumerate(suite["cases"])
                     for si in range(len(case["steps"]))}
    if (not isinstance(rows, dict) or set(rows) != expected_keys
            or any(not isinstance(key, tuple) or any(type(i) is not int for i in key) for key in rows)):
        raise SuiteError("simulation event set differs from the suite")
    outputs = {n: p["width"] for n, p in suite["ports"].items() if p["direction"] == "output"}
    for values in rows.values():
        if not isinstance(values, dict) or set(values) != set(outputs):
            raise SuiteError("simulation output ports differ from the suite")
        for name, value in values.items():
            if not isinstance(value, tuple) or len(value) != 2 or any(type(i) is not int for i in value):
                raise SuiteError("simulation output needs integer bits and known mask")
            bits, known = value
            full = (1 << outputs[name]) - 1
            if not 0 <= bits <= full or not 0 <= known <= full or bits & ~known:
                raise SuiteError("simulation bits or known mask exceeds declared width")
    traces, passed, failed, first = [], [], [], None
    unknown_cases, untested_cases = [], []
    case_comparisons = []
    compared_samples = compared_values = compared_bits = 0
    unknown_expected = unknown_actual = guard_unknown = mask_unknown = 0
    expectations = iter(expected_traces(suite))
    for ci, case in enumerate(suite["cases"]):
        mismatched, uncertain, comparisons = False, False, 0
        prior_counts = (compared_samples, compared_values, compared_bits)
        for si, step in enumerate(case["steps"]):
            expected = next(expectations)
            raw = rows[ci, si]
            actual = {
                n: v if k == (1 << suite["ports"][n]["width"]) - 1 else None
                for n, (v, k) in raw.items()
            }
            trace = {
                **expected,
                "outputs": actual,
                "expected": expected["expected"] if compare_expected else None,
                "actual_bits": {n: v for n, (v, k) in raw.items()},
                "actual_known": {n: k for n, (v, k) in raw.items()},
                "unknown_outputs": [n for n, v in actual.items() if v is None],
                "compared_bits": 0,
                "compared_values": 0,
                "unknown_expected": [],
                "unknown_actual": [],
                "guard_unknown": [],
                "mask_unknown": [],
            }
            traces.append(trace)
            if not step.get("sample", True):
                continue
            if not compare_expected:
                uncertain |= any(v is None for v in actual.values())
                continue
            for name in expected["expected"]:
                full = (1 << suite["ports"][name]["width"]) - 1
                if expected["valid"][name] is False:
                    continue
                if expected["valid"][name] is None:
                    uncertain = True
                    guard_unknown += 1
                    trace["guard_unknown"].append(name)
                    continue
                if expected["mask_known"][name] != full:
                    uncertain = True
                    mask_unknown += 1
                    trace["mask_unknown"].append(name)
                    continue
                mask = expected["masks"][name]
                if not mask:
                    continue
                exp_known = expected["expected_known"][name]
                act, act_known = raw[name]
                if mask & ~exp_known:
                    uncertain = True
                    unknown_expected += 1
                    trace["unknown_expected"].append(name)
                if mask & ~act_known:
                    uncertain = True
                    unknown_actual += 1
                    trace["unknown_actual"].append(name)
                comparable = mask & exp_known & act_known
                if not comparable:
                    continue
                comparisons += 1
                trace["compared_values"] += 1
                trace["compared_bits"] += comparable.bit_count()
                if (expected["expected_bits"][name] ^ act) & comparable:
                    mismatched = True
                    if first is None:
                        first = {
                            **trace,
                            "signal": name,
                            "expected_value": expected["expected"][name],
                            "actual_value": actual[name],
                            "comparison_mask": comparable,
                            "expected_bits_value": expected["expected_bits"][name],
                            "actual_bits_value": act,
                        }
            compared_samples += bool(trace["compared_values"])
            compared_values += trace["compared_values"]
            compared_bits += trace["compared_bits"]
        if mismatched:
            failed.append(case["id"])
        elif uncertain:
            unknown_cases.append(case["id"])
        elif compare_expected and comparisons:
            passed.append(case["id"])
        else:
            untested_cases.append(case["id"])
        case_comparisons.append(
            {
                "case_id": case["id"],
                "requirements": case.get("requirements", []),
                "compared_samples": compared_samples - prior_counts[0],
                "compared_values": compared_values - prior_counts[1],
                "compared_bits": compared_bits - prior_counts[2],
                "status": "failed" if mismatched else "unknown" if uncertain else "passed" if compare_expected and comparisons else "untested",
            }
        )
    return dict(
        suite_hash=suite_hash(suite),
        traces=traces,
        passed_cases=passed,
        failed_cases=failed,
        unknown_cases=unknown_cases,
        untested_cases=untested_cases,
        case_comparisons=case_comparisons,
        compared_samples=compared_samples,
        compared_values=compared_values,
        compared_bits=compared_bits,
        unknown_expected=unknown_expected,
        unknown_actual=unknown_actual,
        guard_unknown=guard_unknown,
        mask_unknown=mask_unknown,
        expectation_analysis=analyze_expectations(suite),
        clock=suite.get("clock"),
        clocks=suite.get("clocks"),
        sampling="after_edge_or_settle",
        first_mismatch=first,
        attribution="unverified_mismatch"
        if failed
        else "unknown_values"
        if unknown_cases
        else "self_agreement"
        if compare_expected
        else "observation_only",
    )


from agent.rtl.vivado import (
    executable,
    scratch_directory,
    tool_slot,
    process_output,
    process_status,
    classify_tool_failure,
    classify_functional_failure,
    extract_diagnostics,
)


def simulate(
    ctx, candidate, suite, *, timeout_s=300.0, save_vcd=False, compare_expected=True
):
    """One bounded check, all commands use the caller's managed process service."""
    started = time.monotonic()
    try:
        suite = validate_suite(
            suite, task_text=ctx.task.prompt + "\n" + ctx.task.interface
        )
        if compare_expected and suite["mode"] != "behavior":
            raise SuiteError("expected comparison requires behavior mode")
    except (SuiteError, TypeError, KeyError) as error:
        return CheckResult(
            "error",
            str(error),
            failure_kind="checker",
            details={
                "attribution": "checker_invalid",
                "failure_kind": "checker",
                "suite_hash": suite_hash(suite),
                "traces": [],
                "passed_cases": [],
                "failed_cases": [],
                "first_mismatch": None,
            },
        )
    identity = suite_hash(suite)
    marker = hashlib.sha256((candidate.code_hash + identity).encode()).hexdigest()[:16]
    stem = f"functional/{candidate.id}-{identity[:12]}"
    driver = build_testbench(suite, ctx.task.top, marker)
    analysis = analyze_expectations(suite)
    artifacts = {
        "driver": str(ctx.record.write_text(stem + "/driver.sv", driver)),
        "suite": str(ctx.record.write_json(stem + "/suite.json", suite)),
    }
    base = {
        "suite_hash": identity,
        "candidate_hash": candidate.code_hash,
        "driver_hash": hashlib.sha256(driver.encode()).hexdigest(),
        "expectation_analysis": analysis,
        "artifacts": artifacts,
        "traces": [],
        "passed_cases": [],
        "failed_cases": [],
        "first_mismatch": None,
        "attribution": "environment",
        "failure_kind": "environment",
        "vcd_requested": save_vcd,
    }

    def finish(status, summary, **kwargs):
        details = kwargs.pop("details", base)
        details["artifacts"] = {**artifacts, **details.get("artifacts", {})}
        ctx.record.write_json(
            stem + "/result.json",
            {
                "status": status,
                "summary": summary,
                "details": details,
                "commands": kwargs.get("command", ()),
                "elapsed_s": time.monotonic() - started,
            },
        )
        return CheckResult(
            status,
            summary,
            details=details,
            failure_kind=details.get("failure_kind", "unknown"),
            elapsed_s=time.monotonic() - started,
            **kwargs,
        )

    if compare_expected and not analysis["comparable_values"]:
        return finish(
            "skipped",
            "checker has no comparable expected values; specification-grounded correction required",
            details={
                **base,
                "attribution": "checker_uninformative",
                "failure_kind": "unknown",
                "compared_samples": 0,
                "compared_values": 0,
                "compared_bits": 0,
            },
        )
    tools = {n: executable(n) for n in ("xvlog", "xelab", "xsim")}
    missing = [n for n, executable in tools.items() if not executable]
    if missing:
        return finish(
            "unavailable", "simulation tools unavailable: " + ", ".join(missing)
        )
    timeout = ctx.budget.timeout(timeout_s)
    deadline = started + timeout
    commands, logs = [], []
    scratch = scratch_directory()
    with tool_slot(ctx, timeout) as acquired:
        if not acquired:
            return finish(
                "timeout",
                "Vivado concurrency wait timed out",
                rc=124,
                details={**base, "failure_kind": "timeout"},
            )
        with tempfile.TemporaryDirectory(
            prefix="rtla_functional_", dir=scratch
        ) as work:
            Path(work, "solution.sv").write_text(candidate.code, encoding="utf-8")
            Path(work, "driver.sv").write_text(driver, encoding="utf-8")
            simulation = (tools["xsim"], "rtla_sim", "-runall")
            if save_vcd:
                script = "open_vcd waveform.vcd\nlog_vcd /rtla_tb/*\nrun all\nclose_vcd\nquit\n"
                Path(work, "wave.tcl").write_text(script, encoding="utf-8")
                artifacts["wave_script"] = str(
                    ctx.record.write_text(stem + "/wave.tcl", script)
                )
                simulation = (tools["xsim"], "rtla_sim", "-tclbatch", "wave.tcl")
            elaboration = (
                tools["xelab"],
                "rtla_tb",
                "-s",
                "rtla_sim",
                "-timescale",
                "1ps/1ps",
            )
            if save_vcd:
                elaboration += ("-debug", "typical")
            for index, command in enumerate(
                (
                    (tools["xvlog"], "--sv", "solution.sv", "driver.sv"),
                    elaboration,
                    simulation,
                )
            ):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return finish(
                        "timeout",
                        "simulation exceeded its time limit",
                        rc=124,
                        details={**base, "failure_kind": "timeout"},
                        command=tuple(commands),
                        log_paths=tuple(logs),
                    )
                commands.append(tuple(command))
                result = ctx.processes.run(
                    tuple(command), cwd=work, timeout_s=ctx.budget.timeout(remaining)
                )
                log = ctx.record.write_text(
                    stem + f"/stage-{index}.log", process_output(result)
                )
                logs.append(str(log))
                wave = Path(work, "waveform.vcd")
                if save_vcd and wave.is_file():
                    artifacts["vcd"] = str(
                        ctx.record.write_text(stem + "/waveform.vcd", wave.read_text())
                    )
                if (
                    process_status(result) != "ok"
                    or classify_tool_failure(process_output(result)) == "environment"
                ):
                    status = (
                        "timeout"
                        if process_status(result) == "timeout"
                        else "unavailable"
                        if process_status(result) == "unavailable"
                        or classify_tool_failure(process_output(result))
                        == "environment"
                        else "error"
                    )
                    failure = (
                        "timeout"
                        if status == "timeout"
                        else "environment"
                        if status == "unavailable"
                        else classify_functional_failure(
                            process_output(result),
                            candidate_code=candidate.code,
                            top=ctx.task.top,
                        )
                    )
                    return finish(
                        status,
                        f"functional simulation stage {index} did not complete: "
                        + process_output(result)[-1500:],
                        rc=result.rc,
                        command=tuple(commands),
                        details={
                            **base,
                            "attribution": "candidate"
                            if failure == "code"
                            else "checker"
                            if failure == "checker"
                            else "environment"
                            if failure == "environment"
                            else "simulation_unresolved",
                            "failure_kind": failure,
                            "repair_diagnostics": extract_diagnostics(process_output(result)),
                            "simulation_stage": index,
                        },
                        log_paths=tuple(logs),
                    )
            try:
                details = parse_traces(
                    process_output(result),
                    suite,
                    marker,
                    compare_expected=compare_expected,
                )
            except SuiteError as error:
                return finish(
                    "error",
                    str(error),
                    command=tuple(commands),
                    details={
                        **base,
                        "attribution": "simulation_incomplete",
                        "failure_kind": "unknown",
                    },
                    log_paths=tuple(logs),
                )
            details = {**base, **details, "failure_kind": "unknown"}
            artifacts["traces"] = str(
                ctx.record.write_json(stem + "/traces.json", details)
            )
            status = (
                "failed"
                if details["failed_cases"]
                else "skipped"
                if details["unknown_cases"]
                else "passed"
                if not compare_expected or details["passed_cases"]
                else "skipped"
            )
            summary = (
                "observations collected; no expected behavior checked"
                if not compare_expected
                else f"self-check: {len(details['passed_cases'])} passed, {len(details['failed_cases'])} failed, "
                f"{len(details['unknown_cases'])} unknown cases; {details['compared_bits']} compared bits"
            )
            return finish(
                status,
                summary,
                command=tuple(commands),
                details=details,
                log_paths=tuple(logs),
            )
