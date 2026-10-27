"""One strict model supplies structured-output schemas and runtime validation."""

from __future__ import annotations

import re
from typing import Annotated, Literal, Union
from pydantic import (
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    StrictBool,
    StrictInt,
    Tag,
    field_validator,
    model_validator,
    ValidationError,
)

from .semantics import SuiteError, _validate_semantics

Width = Annotated[StrictInt, Field(ge=1, le=256)]
Name = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_$]*$")]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Reference(Contract):
    ref: Name


class Constant(Contract):
    const: StrictInt
    width: Width

    @model_validator(mode="after")
    def bounds(self):
        if not -(1 << (self.width - 1)) <= self.const < (1 << self.width):
            raise ValueError("constant exceeds declared width")
        return self


class Operation(Contract):
    width: Width
    signed: StrictBool = False


class Unary(Operation):
    op: Literal["not", "bitnot", "neg", "reduce_and", "reduce_or", "reduce_xor"]
    args: Annotated[list["Expression"], Field(min_length=1, max_length=1)]


class Binary(Operation):
    op: Literal[
        "add",
        "sub",
        "mul",
        "and",
        "or",
        "xor",
        "shl",
        "shr",
        "asr",
        "eq",
        "ne",
        "lt",
        "le",
        "gt",
        "ge",
        "land",
        "lor",
    ]
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


Operator = Annotated[
    Union[Unary, Binary, Conditional, Slice, Concatenation], Field(discriminator="op")
]


def _kind(value):
    if isinstance(value, Reference) or isinstance(value, dict) and "ref" in value:
        return "ref"
    if isinstance(value, Constant) or isinstance(value, dict) and "const" in value:
        return "const"
    return "op"


Expression = Annotated[
    Union[
        Annotated[Reference, Tag("ref")],
        Annotated[Constant, Tag("const")],
        Annotated[Operator, Tag("op")],
    ],
    Discriminator(_kind),
]
for _model in (Unary, Binary, Conditional, Slice, Concatenation):
    _model.model_rebuild()


class Port(Contract):
    direction: Literal["input", "output"]
    width: Width
    signed: StrictBool = False


class Clock(Contract):
    edge: Literal["posedge", "negedge"]


class LegacyClock(Clock):
    port: Name


class InitialValue(Contract):
    value: StrictInt
    signal: Name
    quote: Annotated[str, Field(min_length=1, max_length=1000)]


class Register(Contract):
    width: Width
    signed: StrictBool = False
    clock: Name | None = None
    next: Expression
    initial: InitialValue | None = None


class Reset(Contract):
    port: Name
    active: Annotated[StrictInt, Field(ge=0, le=1)]
    values: dict[Name, Expression]


class Requirement(Contract):
    id: str | None = None
    quote: str | None = None
    source_id: str | None = None
    source_span: dict[str, StrictInt] | None = None

    @model_validator(mode="after")
    def evidence(self):
        if not self.quote and not self.source_id:
            raise ValueError("requirement needs quote or source_id")
        return self


class Step(Contract):
    inputs: dict[Name, StrictInt]
    sample: StrictBool = True
    edge: StrictBool = True
    edges: list[Name] | None = None


class Case(Contract):
    id: Annotated[str, Field(min_length=1, max_length=80)]
    steps: Annotated[list[Step], Field(min_length=1, max_length=512)]
    requirements: Annotated[list[str], Field(max_length=64)] = Field(default_factory=list)


class SuiteModel(Contract):
    schema_version: Literal[1]
    mode: Literal["behavior", "stimulus"]
    ports: Annotated[dict[Name, Port], Field(min_length=1, max_length=64)]
    clock: LegacyClock | None = None
    clocks: Annotated[dict[Name, Clock], Field(min_length=1, max_length=8)] | None = (
        None
    )
    state: Annotated[dict[Name, Register], Field(max_length=64)] = Field(
        default_factory=dict
    )
    async_reset: Reset | None = None
    async_resets: Annotated[list[Reset], Field(min_length=1, max_length=8)] | None = (
        None
    )
    outputs: dict[Name, Expression] = Field(default_factory=dict)
    output_valid: dict[Name, Expression] = Field(default_factory=dict)
    output_masks: dict[Name, Expression] = Field(default_factory=dict)
    requirements: Annotated[list[Requirement], Field(min_length=1, max_length=64)]
    cases: Annotated[list[Case], Field(min_length=1, max_length=32)]

    @field_validator("schema_version", mode="before")
    @classmethod
    def exact_version(cls, value):
        if type(value) is not int:
            raise ValueError("schema_version must be integer 1")
        return value

    @model_validator(mode="after")
    def semantic_contract(self):
        value = self.model_dump(exclude_unset=True)
        _validate_initial_values(value)
        _validate_semantics(value)
        return self


_INITIAL_LITERAL = r"(?:\d+'[sS]?[bBoOdDhH][0-9a-fA-F_]+|0[xX][0-9a-fA-F]+|[+-]?\d+)"


def _initial_literal(text):
    if "'" not in text:
        return int(text, 16 if text.lower().startswith("0x") else 10)
    size, digits = text.split("'", 1)
    signed = digits[0].lower() == "s"
    digits = digits[1:] if signed else digits
    radix, number = digits[0].lower(), digits[1:].replace("_", "")
    value = int(number, {"b": 2, "o": 8, "d": 10, "h": 16}[radix])
    width = int(size)
    if not 1 <= width <= 256 or value >= 1 << width:
        raise ValueError("initial literal exceeds its explicit width")
    if signed and value & (1 << (width - 1)):
        value -= 1 << width
    return value


def _validate_initial_values(suite, *, task_text=None):
    """Accept a deliberately small, explicit initialization language, never reset inference."""
    for name, register in suite.get("state", {}).items():
        initial = register.get("initial")
        if initial is None:
            continue
        label = f"state.{name}.initial"
        signal, quote, value = initial["signal"], initial["quote"], initial["value"]
        if name != "model_" + signal:
            raise SuiteError(label + " must bind model_<signal> to the quoted register")
        if not -(1 << (register["width"] - 1)) <= value < (1 << register["width"]):
            raise SuiteError(label + " value exceeds register width")
        if signal in suite["ports"] and suite["ports"][signal]["width"] != register["width"]:
            raise SuiteError(label + " register width differs from the named public signal")
        normalized = " ".join(quote.split()).strip()
        escaped = re.escape(signal)
        if not re.search(rf"(?<![\w$]){escaped}(?![\w$])", normalized):
            raise SuiteError(label + " quoted signal is case-sensitive")
        number = rf"(?P<value>{_INITIAL_LITERAL})"
        patterns = (
            rf"initial\s+{escaped}\s*=\s*{number}\s*;",
            rf"(?:The\s+)?(?:register\s+)?{escaped}(?:\s+register)?\s+"
            rf"(?:is\s+)?initialized\s+to\s+{number}\s+using\s+the\s+initial\s+statement\.?",
            rf"The\s+register\s+is\s+defined\s+as\s+reg\s+\[\d+\s*:\s*\d+\]\s+"
            rf"{escaped}\s+and\s+initialized\s+to\s+{number}\s+using\s+the\s+initial\s+statement\.?",
        )
        match = next((m for p in patterns if (m := re.fullmatch(p, normalized, re.I))), None)
        try:
            literal = _initial_literal(match["value"]) if match else None
        except (ValueError, KeyError) as error:
            raise SuiteError(label + ": " + str(error)) from error
        if literal != value:
            raise SuiteError(
                label + " needs an explicit initial assignment or initialized-to-value initial-statement quote"
            )
        declared_width = re.search(r"\breg\s+\[(\d+)\s*:\s*(\d+)\]", normalized)
        if declared_width and abs(int(declared_width[1]) - int(declared_width[2])) + 1 != register["width"]:
            raise SuiteError(label + " register width differs from its initialization quote")
        if task_text is not None:
            from agent.domain.rtl.specification import resolve_quote

            try:
                evidence = resolve_quote(quote, task_text)
            except ValueError as error:
                raise SuiteError(label + ": " + str(error)) from error
            start, end = (evidence["source_span"][k] for k in ("start", "end"))
            # A substring of a negative or conditional example is not an initialization contract.
            # Keep the preceding paragraph: a line break does not end an if/example scope.
            paragraph_start = task_text.rfind("\n\n", 0, start)
            before = task_text[paragraph_start + 2 if paragraph_start >= 0 else 0:start]
            paragraph_end = task_text.find("\n\n", end)
            after = task_text[end:paragraph_end if paragraph_end >= 0 else len(task_text)]
            after = after.split(".", 1)[0] if not quote.rstrip().endswith(".") else ""
            if re.search(r"\b(?:not|never|reset|if|when|unless|example|optional|conditional)\b", before, re.I) or re.search(
                r"\b(?:not\s+required|if|when|unless|optional|conditional)\b", after, re.I
            ):
                raise SuiteError(label + " citation is conditional, negative or reset-related")


def validate_suite(suite, *, task_text=None):
    """Validate structure, semantics and (when supplied) original prompt evidence."""
    try:
        value = SuiteModel.model_validate(suite).model_dump(exclude_unset=True)
    except ValidationError as error:
        raise SuiteError(str(error)) from error
    _validate_initial_values(value, task_text=task_text)
    return _validate_semantics(value, task_text=task_text)
