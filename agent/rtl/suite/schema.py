"""One strict model supplies structured-output schemas and runtime validation."""

from __future__ import annotations

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


class Register(Contract):
    width: Width
    signed: StrictBool = False
    clock: Name | None = None
    next: Expression


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
        _validate_semantics(self.model_dump(exclude_unset=True))
        return self


def validate_suite(suite, *, task_text=None):
    """Validate structure, semantics and (when supplied) original prompt evidence."""
    try:
        value = SuiteModel.model_validate(suite).model_dump(exclude_unset=True)
    except ValidationError as error:
        raise SuiteError(str(error)) from error
    return _validate_semantics(value, task_text=task_text)
