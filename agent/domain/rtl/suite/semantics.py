"""Pure cross-field contracts, independent of schema and evaluator modules."""

import re


class SuiteError(ValueError):
    pass


_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


def _integer(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        raise SuiteError(f"{label} must be an integer in {low}..{high}")
    return value


def _name(value):
    if (
        not isinstance(value, str)
        or not _NAME.fullmatch(value)
        or value.startswith("rtla_")
    ):
        raise SuiteError("invalid or reserved signal name")
    return value


def _validate_semantics(value, *, task_text=None):
    ports = value["ports"]
    for name in ports:
        _name(name)
    inputs = {n for n, p in ports.items() if p["direction"] == "input"}
    outputs = set(ports) - inputs
    if not outputs:
        raise SuiteError("at least one output is required")
    clock, clocks = value.get("clock"), value.get("clocks")
    if clock is not None and clocks is not None:
        raise SuiteError("clocks cannot coexist with legacy clock")
    bindings = clocks or ({clock["port"]: clock} if clock else {})
    if any(name not in inputs or ports[name]["width"] != 1 for name in bindings):
        raise SuiteError("every clock must name a one-bit input")
    state = value.setdefault("state", {})
    if state and not bindings:
        raise SuiteError("state requires clocks")
    for name, register in state.items():
        _name(name)
        if name in ports:
            raise SuiteError("state names must be separate from ports")
        if clocks is not None and register.get("clock") not in clocks:
            raise SuiteError(f"state.{name}.clock must name an explicit clock")
        if clocks is None and "clock" in register:
            raise SuiteError(f"state.{name}.clock requires explicit clocks")
    symbols = {n: p["width"] for n, p in ports.items() if n in inputs}
    symbols.update({n: r["width"] for n, r in state.items()})
    diagnostics = _ExpressionDiagnostics()
    for name, register in state.items():
        _validate_expr(
            register["next"],
            symbols,
            path=f"state.{name}.next",
            _diagnostics=diagnostics,
        )
    asynchronous, resets = value.get("async_reset"), value.get("async_resets")
    if asynchronous is not None and resets is not None:
        raise SuiteError("async_resets cannot coexist with legacy async_reset")
    if asynchronous is not None and not clock:
        raise SuiteError("async_reset requires legacy clock")
    if resets is not None and not clocks:
        raise SuiteError("async_resets requires explicit clocks")
    reset_states = set()
    for index, reset in enumerate(resets or ([asynchronous] if asynchronous else [])):
        name = reset["port"]
        if (
            name not in inputs
            or ports[name]["width"] != 1
            or (resets and name in clocks)
        ):
            raise SuiteError("reset must name a one-bit non-clock input")
        values = reset["values"]
        if asynchronous and (
            set(values) != set(state) or not state and value["mode"] != "stimulus"
        ):
            raise SuiteError("legacy reset must map every state register")
        if resets and (
            not values
            or not set(values).issubset(state)
            or reset_states.intersection(values)
        ):
            raise SuiteError("explicit resets require disjoint nonempty state subsets")
        reset_states.update(values)
        for register, expression in values.items():
            _validate_expr(
                expression,
                symbols,
                path=f"resets[{index}].values.{register}",
                _diagnostics=diagnostics,
            )
    expressions = value.setdefault("outputs", {})
    if (
        not set(expressions).issubset(outputs)
        or value["mode"] == "behavior"
        and set(expressions) != outputs
    ):
        raise SuiteError(
            "behavior outputs must define every declared output exactly once"
        )
    for key in ("outputs", "output_valid", "output_masks"):
        mapping = value.get(key, {})
        if not set(mapping).issubset(outputs):
            raise SuiteError(key + " must map declared output names")
        for name, expression in mapping.items():
            width = _validate_expr(
                expression, symbols, path=f"{key}.{name}", _diagnostics=diagnostics
            )
            expected_width = 1 if key == "output_valid" else ports[name]["width"]
            if key != "outputs" and width is not None and width != expected_width:
                diagnostics.add(
                    f"{key}.{name}.width", f"expression width must be {expected_width}"
                )
    diagnostics.raise_if_any()
    if task_text is not None:
        from agent.domain.rtl.specification import normalize_requirements

        try:
            value["requirements"] = normalize_requirements(
                value["requirements"], task_text
            )
        except ValueError as error:
            raise SuiteError(str(error)) from error
    ids = set()
    for index, requirement in enumerate(value["requirements"]):
        identity = requirement.setdefault("id", f"r{index + 1:04d}")
        if not isinstance(identity, str) or not identity.strip() or identity in ids:
            raise SuiteError("requirements need unique nonempty ids")
        ids.add(identity)
    case_ids, events, samples = set(), 0, 0
    driven = inputs - set(bindings)
    for case in value["cases"]:
        if case["id"] in case_ids:
            raise SuiteError("case ids must be unique")
        case_ids.add(case["id"])
        for step in case["steps"]:
            if set(step["inputs"]) != driven:
                raise SuiteError(
                    "each step must drive every non-clock input exactly once"
                )
            if clocks is not None:
                edges = step.get("edges")
                if (
                    "edge" in step
                    or edges is None
                    or len(set(edges)) != len(edges)
                    or not set(edges).issubset(clocks)
                ):
                    raise SuiteError(
                        "explicit clocks needs unique edges list, and no legacy edge field"
                    )
            elif "edges" in step:
                raise SuiteError("edges requires explicit clocks")
            for name, number in step["inputs"].items():
                width = ports[name]["width"]
                _integer(number, -(1 << (width - 1)), (1 << width) - 1, "input value")
            events += 1
            samples += step.get("sample", True)
    if events > 4096 or not samples:
        raise SuiteError("suite needs sampled events and at most 4096 total events")
    return value


class _ExpressionDiagnostics:
    """Collect independent expression errors once, with bounded feedback size."""

    limit = 8

    def __init__(self):
        self.errors = []

    @property
    def full(self):
        return len(self.errors) >= self.limit

    def add(self, path, message):
        if not self.full:
            self.errors.append(f"{path}: {message}")

    def raise_if_any(self):
        if self.errors:
            suffix = (
                f"\ndiagnostic limit {self.limit} reached; further errors may exist"
                if self.full
                else ""
            )
            raise SuiteError("\n".join(self.errors) + suffix)


def _validate_expr(expr, symbols, depth=0, *, path="expression", _diagnostics=None):
    """Validate each node once; no width is inferred for an invalid expression."""
    diagnostics = _diagnostics if _diagnostics is not None else _ExpressionDiagnostics()
    width = _check_expr(expr, symbols, depth, path, diagnostics)
    if _diagnostics is None:
        diagnostics.raise_if_any()
    return width


def _check_expr(expr, symbols, depth, path, diagnostics):
    if diagnostics.full:
        return None
    if depth > 32:
        diagnostics.add(path, "expression depth exceeds 32")
        return None
    if "ref" in expr:
        if expr["ref"] not in symbols:
            diagnostics.add(
                path + ".ref", "unknown expression reference; must name input or state"
            )
            return None
        return symbols[expr["ref"]]
    width = expr["width"]
    if "const" in expr:
        return width
    op = expr["op"]
    if expr.get("signed", False) and op not in (
        "add",
        "sub",
        "mul",
        "and",
        "or",
        "xor",
        "eq",
        "ne",
        "lt",
        "le",
        "gt",
        "ge",
        "shl",
        "asr",
        "bitnot",
        "neg",
    ):
        diagnostics.add(path + ".signed", "signed is unsupported for this operator")
    widths = [
        _check_expr(arg, symbols, depth + 1, f"{path}.args[{index}]", diagnostics)
        for index, arg in enumerate(expr["args"])
    ]
    if op == "slice" and widths[0] is not None and expr["lsb"] + width > widths[0]:
        diagnostics.add(path + ".lsb", "slice exceeds input width")
    if op == "concat" and all(w is not None for w in widths) and sum(widths) != width:
        diagnostics.add(path + ".width", "concat width differs from argument widths")
    if (
        op
        in (
            "eq",
            "ne",
            "lt",
            "le",
            "gt",
            "ge",
            "land",
            "lor",
            "not",
            "reduce_and",
            "reduce_or",
            "reduce_xor",
        )
        and width != 1
    ):
        diagnostics.add(path + ".width", "boolean expression width must be one")
    return width
