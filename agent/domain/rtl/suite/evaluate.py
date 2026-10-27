"""Pure behavior evaluation; unknown bits remain unknown."""

from __future__ import annotations
import hashlib
import json
from .schema import validate_suite
from .semantics import SuiteError
from agent.domain.rtl.identity import suite_hash


def evaluate(expr, values, widths):
    """Return (unsigned bits or None, width), without evaluating source code."""
    if "ref" in expr:
        return values[expr["ref"]], widths[expr["ref"]]
    width = expr["width"]
    mask = (1 << width) - 1
    if "const" in expr:
        return expr["const"] & mask, width
    op = expr["op"]
    args = [evaluate(arg, values, widths) for arg in expr["args"]]
    numbers = [v for v, _ in args]
    if op == "ite":
        if numbers[0] is None:
            result = numbers[1] if numbers[1] == numbers[2] else None
        else:
            result = numbers[1] if numbers[0] else numbers[2]
        return (result & mask if result is not None else None), width
    if any(number is None for number in numbers):
        return None, width
    if expr.get("signed", False):
        numbers = [
            v - (1 << w)
            if v & (1 << (w - 1)) and (op not in ("shl", "asr") or i == 0)
            else v
            for i, (v, w) in enumerate(args)
        ]
    a = numbers[0]
    b = numbers[1] if len(numbers) > 1 else 0
    if op == "add":
        result = a + b
    elif op == "sub":
        result = a - b
    elif op == "mul":
        result = a * b
    elif op == "and":
        result = a & b
    elif op == "or":
        result = a | b
    elif op == "xor":
        result = a ^ b
    elif op == "shl":
        result = a << min(b, 512)
    elif op in ("shr", "asr"):
        result = a >> min(max(b, 0), 512)
    elif op == "eq":
        result = a == b
    elif op == "ne":
        result = a != b
    elif op == "lt":
        result = a < b
    elif op == "le":
        result = a <= b
    elif op == "gt":
        result = a > b
    elif op == "ge":
        result = a >= b
    elif op == "land":
        result = bool(a) and bool(b)
    elif op == "lor":
        result = bool(a) or bool(b)
    elif op == "not":
        result = not a
    elif op == "bitnot":
        result = ~a
    elif op == "neg":
        result = -a
    elif op == "slice":
        result = a >> expr["lsb"]
    elif op == "reduce_and":
        result = a == (1 << args[0][1]) - 1
    elif op == "reduce_or":
        result = bool(a)
    elif op == "reduce_xor":
        result = a.bit_count() % 2
    elif op == "concat":
        result = 0
        for number, bits in args:
            result = (result << bits) | number
    else:
        raise SuiteError("unsupported expression operator")
    return int(result) & mask, width


def _resize(bits, width, signed=False):
    value, known, old_width = bits
    mask = (1 << width) - 1
    if width > old_width:
        extra = mask ^ ((1 << old_width) - 1)
        if not signed:
            known |= extra
        elif known & (1 << (old_width - 1)):
            known |= extra
            if value & (1 << (old_width - 1)):
                value |= extra
    return value & mask, known & mask, width


def _evaluate_bits(expr, values, widths):
    """Conservative bit knowledge; never invent an initial or arithmetic bit."""
    if "ref" in expr:
        return values[expr["ref"]]
    width = expr["width"]
    full = (1 << width) - 1
    if "const" in expr:
        return expr["const"] & full, full, width
    args = [_evaluate_bits(arg, values, widths) for arg in expr["args"]]
    op = expr["op"]
    if op == "slice":
        a, known, _ = args[0]
        return (a >> expr["lsb"]) & full, (known >> expr["lsb"]) & full, width
    if op == "concat":
        value = known = 0
        for a, k, w in args:
            value, known = (value << w) | a, (known << w) | k
        return value & full, known & full, width
    if op == "ite":
        c, ck, cw = args[0]
        a = _resize(args[1], width)
        b = _resize(args[2], width)
        if c & ck:
            return a
        if ck == (1 << cw) - 1:
            return b
        known = a[1] & b[1] & ~(a[0] ^ b[0]) & full
        return a[0] & known, known, width
    if op in ("and", "or", "xor", "bitnot"):
        expanded = [_resize(a, width, expr.get("signed", False)) for a in args]
        a, ak, _ = expanded[0]
        if op == "bitnot":
            return (~a) & ak & full, ak, width
        b, bk, _ = expanded[1]
        if op == "and":
            known = (ak & bk) | (ak & ~a) | (bk & ~b)
            value = a & b
        elif op == "or":
            known = (ak & bk) | (ak & a) | (bk & b)
            value = a | b
        else:
            known, value = ak & bk, a ^ b
        return value & known & full, known & full, width
    if op in ("shl", "shr", "asr"):
        amount, amount_known, amount_width = args[1]
        if amount_known != (1 << amount_width) - 1:
            return 0, 0, width
        amount = min(amount, 512)
        signed = expr.get("signed", False) and op != "shr"
        expanded_width = max(args[0][2], width)
        a, known, _ = _resize(args[0], expanded_width, signed)
        if op == "shl":
            zeros = (1 << min(amount, width)) - 1
            return (a << amount) & full, ((known << amount) | zeros) & full, width
        # Preserve each known source bit; shifted-in zeros or a known sign are also known.
        retained = min(width, max(0, expanded_width - amount))
        fill = full ^ ((1 << retained) - 1)
        value, known_result = a >> amount, known >> amount
        sign = 1 << (expanded_width - 1)
        if not signed or known & sign:
            known_result |= fill
            if signed and a & sign:
                value |= fill
        return value & known_result & full, known_result & full, width
    if all(k == (1 << w) - 1 for _, k, w in args):
        concrete = {**expr, "args": [{"const": a, "width": w} for a, _, w in args]}
        result, _ = evaluate(concrete, {}, {})
        return result, full, width
    return 0, 0, width


def _clocks(suite):
    if suite.get("clock"):
        return {suite["clock"]["port"]: {"edge": suite["clock"]["edge"]}}
    return suite.get("clocks", {})


def _edges(suite, step):
    if suite.get("clocks"):
        return step["edges"]
    return list(_clocks(suite)) if step.get("edge", True) else []


def expected_traces(suite):
    suite = validate_suite(suite)
    ports, registers = suite["ports"], suite["state"]
    widths = {n: p["width"] for n, p in ports.items()}
    widths.update({n: p["width"] for n, p in registers.items()})
    clocks = _clocks(suite)
    resets = suite.get(
        "async_resets", [suite["async_reset"]] if suite.get("async_reset") else []
    )
    result = []
    for case in suite["cases"]:
        state = {
            n: (
                r["initial"]["value"] & ((1 << r["width"]) - 1),
                (1 << r["width"]) - 1,
                r["width"],
            )
            if r.get("initial") is not None
            else (0, 0, r["width"])
            for n, r in registers.items()
        }
        previous_inputs = {}
        for index, step in enumerate(case["steps"]):
            values = {
                n: (v & ((1 << widths[n]) - 1), (1 << widths[n]) - 1, widths[n])
                for n, v in step["inputs"].items()
            }
            edges = _edges(suite, step)
            for name, clock in clocks.items():
                values[name] = (int(clock["edge"] != "posedge"), 1, 1)
            values.update(state)
            reset_values, asserted_values = {}, {}
            for reset in resets:
                if values[reset["port"]][0] == reset["active"]:
                    reset_values.update(reset["values"])
                    if previous_inputs.get(reset["port"]) != reset["active"]:
                        asserted_values.update(reset["values"])
            # Reset is driven before edges and settles before other domains sample it.
            state.update(
                {
                    n: _resize(_evaluate_bits(e, values, widths), widths[n])
                    for n, e in asserted_values.items()
                }
            )
            values.update(state)
            for name in edges:
                values[name] = (int(clocks[name]["edge"] == "posedge"), 1, 1)
            # Every triggered domain reads this one snapshot, including cross-domain reads.
            updates = {
                n: _resize(
                    _evaluate_bits(reset_values.get(n, r["next"]), values, widths),
                    r["width"],
                )
                for n, r in registers.items()
                if r.get("clock", next(iter(clocks), None)) in edges
            }
            state.update(updates)
            previous_inputs = dict(step["inputs"])
            values.update(state)
            expected, expected_known, valid, masks, mask_known, partial = (
                {},
                {},
                {},
                {},
                {},
                {},
            )
            for n, e in suite["outputs"].items():
                full = (1 << ports[n]["width"]) - 1
                v, known, _ = _resize(
                    _evaluate_bits(e, values, widths), ports[n]["width"]
                )
                expected[n], expected_known[n], partial[n] = (
                    v if known == full else None,
                    known,
                    v,
                )
                # Partial values remain available separately; None retains the old public convention.
                guard = suite.get("output_valid", {}).get(n, {"const": 1, "width": 1})
                g, gk, _ = _evaluate_bits(guard, values, widths)
                valid[n] = bool(g) if gk else None
                mask_expr = suite.get("output_masks", {}).get(
                    n, {"const": full, "width": ports[n]["width"]}
                )
                masks[n], mask_known[n], _ = _evaluate_bits(mask_expr, values, widths)
            result.append(
                {
                    "case_id": case["id"],
                    "step": index,
                    "inputs": dict(step["inputs"]),
                    "sample": step.get("sample", True),
                    "edge": step.get("edge", True),
                    "edges": edges,
                    "expected": expected,
                    "expected_bits": partial,
                    "expected_known": expected_known,
                    "valid": valid,
                    "masks": masks,
                    "mask_known": mask_known,
                }
            )
    return result


_COUNT_KEYS = (
    "sampled_events",
    "comparable_samples",
    "comparable_values",
    "comparable_bits",
    "unknown_expected",
    "guard_unknown",
    "mask_unknown",
    "excluded_values",
    "excluded_bits",
)


def _expectation_counts(row, suite):
    counts = dict.fromkeys(_COUNT_KEYS, 0)
    if not row["sample"]:
        return counts
    counts["sampled_events"] = 1
    for name in row["expected"]:
        full = (1 << suite["ports"][name]["width"]) - 1
        if row["valid"][name] is False:
            counts["excluded_values"] += 1
            counts["excluded_bits"] += full.bit_count()
            continue
        if row["valid"][name] is None:
            counts["guard_unknown"] += 1
            continue
        if row["mask_known"][name] != full:
            counts["mask_unknown"] += 1
            continue
        mask = row["masks"][name]
        counts["excluded_bits"] += (full ^ mask).bit_count()
        if not mask:
            counts["excluded_values"] += 1
            continue
        known = row["expected_known"][name] & mask
        counts["comparable_bits"] += known.bit_count()
        counts["comparable_values"] += bool(known)
        counts["unknown_expected"] += known != mask
    counts["comparable_samples"] = int(bool(counts["comparable_bits"]))
    return counts


def analyze_expectations(suite):
    """Preflight only: counts model knowledge, without RTL or simulator outputs."""
    suite = validate_suite(suite)
    total = dict.fromkeys(_COUNT_KEYS, 0)
    cases = {
        c["id"]: dict(case_id=c["id"], **dict.fromkeys(_COUNT_KEYS, 0))
        for c in suite["cases"]
    }
    comparison_events = []
    clock_signature = json.dumps(_clocks(suite), sort_keys=True, separators=(",", ":"))
    prefixes = {}
    for row in expected_traces(suite):
        prior = prefixes.get(row["case_id"], hashlib.sha256(clock_signature.encode()).hexdigest())
        event = {
            "inputs": {
                n: v & ((1 << suite["ports"][n]["width"]) - 1)
                for n, v in row["inputs"].items()
            },
            "edges": sorted(row["edges"]),
        }
        prefix = hashlib.sha256(
            (prior + json.dumps(event, sort_keys=True, separators=(",", ":"))).encode()
        ).hexdigest()
        prefixes[row["case_id"]] = prefix
        counts = _expectation_counts(row, suite)
        for key, count in counts.items():
            total[key] += count
            cases[row["case_id"]][key] += count
        if counts["comparable_bits"]:
            masks = {
                name: row["masks"][name] & row["expected_known"][name]
                for name in row["expected"]
                if row["valid"][name] is True
                and row["mask_known"][name] == (1 << suite["ports"][name]["width"]) - 1
                and row["masks"][name] & row["expected_known"][name]
            }
            comparison_events.append(
                {
                    "case_id": row["case_id"],
                    "step": row["step"],
                    "inputs": row["inputs"],
                    "edges": row["edges"],
                    "output_masks": masks,
                    "stimulus_prefix_sha256": prefix,
                    "comparison_signature": hashlib.sha256(
                        (prefix + json.dumps(masks, sort_keys=True, separators=(",", ":"))).encode()
                    ).hexdigest(),
                }
            )
    return {
        **total,
        "per_case": list(cases.values()),
        "comparison_events": comparison_events,
        "suite_hash": suite_hash(suite),
    }


def require_comparable_expectations(suite, *, task_text=None):
    """Reject a behavior draft that cannot finish strict comparison, before invoking RTL tools."""
    suite = validate_suite(suite, task_text=task_text)
    if suite["mode"] != "behavior":
        raise SuiteError("comparable expectations require behavior mode")
    analysis = analyze_expectations(suite)
    failures = []
    for case in analysis["per_case"]:
        reasons = [
            f"{key}={case[key]}"
            for key in ("unknown_expected", "guard_unknown", "mask_unknown")
            if case[key]
        ]
        if not case["comparable_values"]:
            reasons.append("no comparable expected output values")
        if reasons:
            failures.append(f"case {case['case_id']}: " + ", ".join(reasons))
    if failures:
        raise SuiteError(
            "expectation selfcheck cannot complete strict comparison: "
            + "; ".join(failures[:8])
            + (f"; {len(failures) - 8} further cases" if len(failures) > 8 else "")
            + ". Derive valid initialization, warm-up and sampling from the public task; "
            "do not coerce unknowns, disable required samples or weaken validity/masks."
        )
    return analysis


def require_requirement_coverage(suite):
    """Check declared requirement bindings and predicted comparisons, not semantic sufficiency."""
    suite = validate_suite(suite)
    analysis = analyze_expectations(suite)
    counts = {case["case_id"]: case for case in analysis["per_case"]}
    requirements = {r["id"]: r for r in suite["requirements"]}
    bindings = {name: [] for name in requirements}
    for case in suite["cases"]:
        names = case.get("requirements", [])
        if not names or len(set(names)) != len(names) or any(n not in requirements for n in names):
            raise SuiteError(
                f"case {case['id']} requirements must uniquely name existing requirement ids"
            )
        if not counts[case["id"]]["comparable_values"]:
            raise SuiteError(f"case {case['id']} requirement binding has no predicted comparison")
        for name in names:
            bindings[name].append(case["id"])
    missing = [name for name, cases in bindings.items() if not cases]
    if missing:
        raise SuiteError("requirements lack a case with predicted comparisons: " + ", ".join(missing))
    return {
        "kind": "declared_requirement_comparison_coverage",
        "semantic_coverage_proven": False,
        "suite_hash": suite_hash(suite),
        "requirements": [
            {
                "requirement_id": name,
                "quote": requirements[name].get("quote"),
                "source_id": requirements[name].get("source_id"),
                "case_ids": cases,
                "predicted_comparable_bits": sum(counts[c]["comparable_bits"] for c in cases),
            }
            for name, cases in bindings.items()
        ],
    }


def coverage_summary(suites):
    """Report stimulus diversity; exhaustiveness applies only to small combinational domains."""
    suites = [validate_suite(s) for s in suites]
    stimuli, inputs, complete_inputs = set(), set(), set()
    input_bits = None
    compatible = bool(suites)
    signature = None
    for suite in suites:
        ports = suite["ports"]
        sig = {
            n: (p["direction"], p["width"], p.get("signed", False))
            for n, p in ports.items()
        }
        compatible &= signature is None or signature == sig
        signature = sig
        bits = sum(p["width"] for p in ports.values() if p["direction"] == "input")
        input_bits = bits if input_bits is None else input_bits
        compatible &= (
            not suite["state"]
            and not _clocks(suite)
            and suite["mode"] == "behavior"
            and bits <= 12
        )
        for case in suite["cases"]:
            steps = [
                {
                    "inputs": {
                        n: v & ((1 << ports[n]["width"]) - 1)
                        for n, v in step["inputs"].items()
                    },
                    "edges": _edges(suite, step),
                    "sample": step.get("sample", True),
                }
                for step in case["steps"]
            ]
            stimuli.add(
                json.dumps({"clocks": _clocks(suite), "steps": steps}, sort_keys=True)
            )
        for row in expected_traces(suite):
            key = json.dumps(
                {
                    n: v & ((1 << ports[n]["width"]) - 1)
                    for n, v in row["inputs"].items()
                },
                sort_keys=True,
            )
            inputs.add(key)
            full = all(
                row["valid"][n] is True
                and row["masks"][n] == (1 << ports[n]["width"]) - 1
                and row["mask_known"][n] == (1 << ports[n]["width"]) - 1
                and row["expected_known"][n] == (1 << ports[n]["width"]) - 1
                for n, p in ports.items()
                if p["direction"] == "output" and n in row["expected"]
            )
            if row["sample"] and full and suite["mode"] == "behavior":
                complete_inputs.add(key)
    domain = (1 << input_bits) if compatible else None
    return {
        "unique_stimuli": len(stimuli),
        "unique_inputs": len(inputs),
        "fully_comparable_inputs": len(complete_inputs),
        "input_domain_size": domain,
        "stateless_exhaustive": bool(compatible and len(complete_inputs) == domain),
    }
