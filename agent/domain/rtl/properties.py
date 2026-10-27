"""Bounded public-port properties with strict four-state and obligation accounting."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal, Union

from pydantic import Discriminator, Field, StrictBool, StrictInt, Tag, ValidationError, model_validator

from .observation import SamplingPlan, validate_sampling_plan, validate_trace
from .suite.evaluate import _evaluate_bits
from .suite.schema import Constant, Contract, Name, Requirement, Width
from .suite.semantics import SuiteError, _validate_expr


class Signal(Contract):
    signal: Name
    phase: Literal["pre", "post"]
    past: Annotated[StrictInt, Field(ge=0, le=16)] = 0
    anchor: StrictBool = False

    @model_validator(mode="after")
    def separate_origin(self):
        if self.anchor and self.past:
            raise ValueError("anchor and past cannot be combined")
        return self


class Operation(Contract):
    width: Width
    signed: StrictBool = False


class Unary(Operation):
    op: Literal["not", "bitnot", "neg", "reduce_and", "reduce_or", "reduce_xor"]
    args: Annotated[list["Expression"], Field(min_length=1, max_length=1)]


class Binary(Operation):
    op: Literal["add", "sub", "mul", "and", "or", "xor", "shl", "shr", "asr", "eq", "ne", "lt", "le", "gt", "ge", "land", "lor"]
    args: Annotated[list["Expression"], Field(min_length=2, max_length=2)]


class Conditional(Operation):
    op: Literal["ite"]
    args: Annotated[list["Expression"], Field(min_length=3, max_length=3)]


class Slice(Operation):
    op: Literal["slice"]
    args: Annotated[list["Expression"], Field(min_length=1, max_length=1)]
    lsb: Annotated[StrictInt, Field(ge=0, le=255)]


class Concatenation(Operation):
    op: Literal["concat"]
    args: Annotated[list["Expression"], Field(min_length=1, max_length=32)]


Operator = Annotated[Union[Unary, Binary, Conditional, Slice, Concatenation], Field(discriminator="op")]


def _kind(value):
    if isinstance(value, Signal) or isinstance(value, dict) and "signal" in value:
        return "signal"
    if isinstance(value, Constant) or isinstance(value, dict) and "const" in value:
        return "const"
    return "op"


Expression = Annotated[Union[
    Annotated[Signal, Tag("signal")], Annotated[Constant, Tag("const")],
    Annotated[Operator, Tag("op")],
], Discriminator(_kind)]
for _model in (Unary, Binary, Conditional, Slice, Concatenation):
    _model.model_rebuild()


class Window(Contract):
    min: Annotated[StrictInt, Field(ge=0, le=16)]
    max: Annotated[StrictInt, Field(ge=0, le=16)]

    @model_validator(mode="after")
    def ordered(self):
        if self.min > self.max:
            raise ValueError("response window must have min <= max")
        return self


class Property(Contract):
    id: Annotated[str, Field(min_length=1, max_length=80)]
    requirements: Annotated[list[str], Field(min_length=1, max_length=64)]
    sample_phase: Literal["pre", "post"] = "post"
    warmup_ticks: Annotated[StrictInt, Field(ge=0, le=16)] = 0
    trigger: Expression
    window: Window
    assertion: Expression
    abort: Expression | None = None
    abort_requirements: Annotated[list[str], Field(max_length=64)] = Field(default_factory=list)


class PropertySuite(Contract):
    schema_version: Literal[1]
    sampling: SamplingPlan
    requirements: Annotated[list[Requirement], Field(min_length=1, max_length=64)]
    properties: Annotated[list[Property], Field(min_length=1, max_length=5)]

    @model_validator(mode="before")
    @classmethod
    def exact_version(cls, value):
        if isinstance(value, dict) and type(value.get("schema_version")) is not int:
            raise ValueError("schema_version must be integer 1")
        return value


def _expression(expr, ports, *, sample_phase, allow_anchor, count, depth=0):
    count[0] += 1
    if count[0] > 128 or depth > 32:
        raise SuiteError("property expressions exceed 128 total nodes or depth 32")
    if "signal" in expr:
        name = expr["signal"]
        if name not in ports:
            raise SuiteError("property signal must name a public port")
        if expr["anchor"] and not allow_anchor:
            raise SuiteError("anchor is only allowed in the response assertion")
        if sample_phase == "pre" and expr["phase"] == "post" and not expr["past"]:
            raise SuiteError("pre sampling cannot read the current or trigger event post phase")
        ref = json.dumps(expr, sort_keys=True)
        return {"ref": ref}, {ref: ports[name]["width"]}
    if "const" in expr:
        return expr, {}
    arguments, symbols = [], {}
    for argument in expr["args"]:
        converted, names = _expression(argument, ports, sample_phase=sample_phase,
                                       allow_anchor=allow_anchor, count=count, depth=depth + 1)
        arguments.append(converted)
        symbols.update(names)
    return {**expr, "args": arguments}, symbols


def validate_properties(suite, *, task_text=None, expected_interface=None):
    """Bind schema, public references and fixed sampling before a semantic review."""
    try:
        raw = suite.model_dump(mode="json") if isinstance(suite, PropertySuite) else suite
        value = PropertySuite.model_validate(raw).model_dump(mode="json")
    except (ValidationError, TypeError) as error:
        raise SuiteError(str(error)) from error
    value["sampling"] = validate_sampling_plan(value["sampling"], expected_interface=expected_interface)
    if task_text is not None:
        from .specification import normalize_requirements
        # Optional null fields are not evidence; retain only explicitly populated source fields.
        requirements = [{k: v for k, v in item.items() if v is not None} for item in value["requirements"]]
        try:
            value["requirements"] = normalize_requirements(requirements, task_text)
        except ValueError as error:
            raise SuiteError(str(error)) from error
    ids = set()
    for i, requirement in enumerate(value["requirements"]):
        identity = requirement.get("id") or f"r{i + 1:04d}"
        if identity in ids or not identity.strip():
            raise SuiteError("requirements need unique nonempty ids")
        requirement["id"] = identity
        ids.add(identity)
    property_ids = set()
    for prop in value["properties"]:
        if prop["id"] in property_ids:
            raise SuiteError("property ids must be unique")
        property_ids.add(prop["id"])
        for key in ("requirements", "abort_requirements"):
            names = prop[key]
            if len(set(names)) != len(names) or not set(names).issubset(ids):
                raise SuiteError(f"property {prop['id']} {key} must name unique public requirements")
        if bool(prop["abort"] is not None) != bool(prop["abort_requirements"]):
            raise SuiteError("abort must have its own public requirement binding")
        def output_read(node):
            return ("signal" in node and value["sampling"]["ports"].get(node["signal"], {}).get("direction") == "output") or any(output_read(child) for child in node.get("args", []))
        if not output_read(prop["assertion"]):
            raise SuiteError("property assertion must observe at least one public output")
        count = [0]
        for key in ("trigger", "assertion", "abort"):
            if prop[key] is None:
                continue
            converted, symbols = _expression(prop[key], value["sampling"]["ports"],
                sample_phase=prop["sample_phase"], allow_anchor=key == "assertion", count=count)
            if _validate_expr(converted, symbols) != 1:
                raise SuiteError(f"property {prop['id']} {key} must be one bit")
        if not value["sampling"]["clock"] and prop["window"]["max"]:
            raise SuiteError("combinational properties only support immediate windows")
        if prop["warmup_ticks"] >= max(sum(s["edge"] for s in c["steps"]) if value["sampling"]["clock"] else len(c["steps"]) for c in value["sampling"]["cases"]):
            raise SuiteError("property warmup excludes every available sampling event")
    return value


def property_hash(suite):
    return hashlib.sha256(json.dumps(validate_properties(suite), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _value(expr, events, index, anchor, ports):
    values, widths = {}, {}

    def convert(node):
        if "signal" in node:
            position = anchor if node["anchor"] else index - node["past"]
            name, width = node["signal"], ports[node["signal"]]["width"]
            identity = f"v{len(values)}"
            if position is None or position < 0:
                bits = (0, 0, width)
            else:
                raw = events[position][node["phase"]]["values"][name]
                bits = (raw["bits"], raw["known"], width)
            values[identity], widths[identity] = bits, width
            return {"ref": identity}
        if "const" in node:
            return node
        return {**node, "args": [convert(a) for a in node["args"]]}

    value, known, width = _evaluate_bits(convert(expr), values, widths)
    return bool(value) if known == (1 << width) - 1 else None


_COUNTS = ("triggered", "satisfied", "violated", "unknown", "incomplete", "aborted", "untriggered")


def evaluate_properties(suite, trace):
    """Evaluate finite obligations. Zero triggers and unresolved windows never pass."""
    suite = validate_properties(suite)
    plan = suite["sampling"]
    validate_trace(trace, plan)
    rows = {(r["case_index"], r["step"], r["phase"]): r for r in trace.rows}
    per_property, obligations, unknown_triggers = [], [], []
    for prop in suite["properties"]:
        counts = dict.fromkeys(_COUNTS, 0)
        details = []
        evaluations = warmup = suppressed = 0
        for ci, case in enumerate(plan["cases"]):
            events = [{phase: rows[ci, si, phase] for phase in ("pre", "post")}
                      for si, step in enumerate(case["steps"]) if not plan["clock"] or step["edge"]]
            pending = []
            for index, event in enumerate(events):
                row = event[prop["sample_phase"]]
                aborted = _value(prop["abort"], events, index, None, plan["ports"]) if prop["abort"] is not None else False
                trigger = _value(prop["trigger"], events, index, None, plan["ports"])
                if index < prop["warmup_ticks"]:
                    warmup += 1
                elif not row["sample"]:
                    suppressed += 1
                elif trigger is None:
                    counts["unknown"] += 1
                    unknown_triggers.append({"property_id": prop["id"], "case_id": case["id"], "step": row["step"], "phase": prop["sample_phase"]})
                elif trigger:
                    counts["triggered"] += 1
                    pending.append({"property_id": prop["id"], "case_id": case["id"], "trigger_step": row["step"],
                                    "trigger_tick": index, "phase": prop["sample_phase"], "requirements": prop["requirements"], "unknown_seen": False,
                                    "response_evaluations": 0, "observations": []})
                for obligation in pending[:]:
                    age = index - obligation["trigger_tick"]
                    end = prop["window"]["max"]
                    status = None
                    answer = None
                    if aborted is True:
                        status = "aborted"
                    elif aborted is None:
                        obligation["unknown_seen"] = True
                    if status is None and prop["window"]["min"] <= age <= end:
                        answer = _value(prop["assertion"], events, index, obligation["trigger_tick"], plan["ports"])
                        evaluations += 1
                        obligation["response_evaluations"] += 1
                        obligation["observations"].append({"step": row["step"], "age": age, "value": answer, "abort": aborted})
                        if answer is True and aborted is False:
                            # A past unknown abort means cancellation is unresolved, even after a later response.
                            status = "unknown" if obligation.get("abort_unknown") else "satisfied"
                        elif answer is None:
                            obligation["unknown_seen"] = True
                    if aborted is None:
                        obligation["abort_unknown"] = True
                    if status is None and age >= end:
                        status = "unknown" if obligation["unknown_seen"] else "violated"
                    if status:
                        obligation["status"], obligation["end_step"] = status, row["step"]
                        counts[status] += 1
                        details.append(obligation)
                        pending.remove(obligation)
            for obligation in pending:
                obligation["status"] = "incomplete"
                counts["incomplete"] += 1
                details.append(obligation)
        if counts["triggered"] == 0:
            counts["untriggered"] = 1
        status = ("failed" if counts["violated"] else "unknown" if counts["unknown"] or counts["incomplete"]
                  else "untested" if not counts["satisfied"] else "passed")
        # An entirely aborted property did not compare its behavior.
        result = {"property_id": prop["id"], "requirements": prop["requirements"], "status": status, **counts,
                  "response_evaluations": evaluations, "warmup_events": warmup, "suppressed_events": suppressed,
                  "obligations": details}
        per_property.append(result)
        obligations.extend(details)
    total = {key: sum(p[key] for p in per_property) for key in _COUNTS}
    passed = [p["property_id"] for p in per_property if p["status"] == "passed"]
    failed = [p["property_id"] for p in per_property if p["status"] == "failed"]
    unknown = [p["property_id"] for p in per_property if p["status"] == "unknown"]
    untested = [p["property_id"] for p in per_property if p["status"] == "untested"]
    status = "failed" if failed else "unknown" if unknown else "untested" if untested else "passed"
    first = next((o for o in obligations if o["status"] == "violated"), None)
    return {"kind": "local_properties", "status": status, "candidate_hash": trace.candidate_hash,
            "execution_id": trace.execution_id, "plan_hash": trace.plan_hash, "property_hash": property_hash(suite),
            "counts": total, "per_property": per_property, "passed_properties": passed,
            "failed_properties": failed, "unknown_properties": unknown, "untested_properties": untested,
            "unknown_triggers": unknown_triggers, "first_counterexample": first,
            "semantic_coverage_proven": False, "sampling": "explicit_pre_post", "history_unit": "active_edges" if plan["clock"] else "events"}
