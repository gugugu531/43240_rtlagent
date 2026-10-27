"""Specification-only suite construction with preserved revision and coverage gates."""

from dataclasses import dataclass
import copy
import re
import math
import json
import hashlib
from types import SimpleNamespace
from agent.kit import Ctx, State, node
from agent.domain.rtl.specification import (
    normalize_requirements,
    resolve_quote,
    resolve_requirement,
    source_catalog,
)
from agent.domain.rtl.suite.model import (
    SuiteError,
    suite_hash,
    validate_revision,
    validate_suite,
)
from agent.domain.rtl.suite.evaluate import (
    analyze_expectations,
    require_comparable_expectations,
    require_requirement_coverage,
)
from agent.domain.rtl.suite.revision import apply_expression_patch
from agent.orchestration.nodes.structured import request


def _thaw(value):
    return copy.deepcopy(value)


@dataclass
class SuiteBuild:
    status: str
    suite: dict | None = None
    call_id: str | None = None
    reason: str = ""


SUITE_RESPONSE_INSTRUCTION = """Return one complete response object:
{"status":"ready","suite":<suite>} or {"status":"unsupported","reason":"..."}.
This outer response is required for BOTH initial construction and every correction.
Never return a bare suite, a patch, or only the corrected expression. The suite schema
below describes the value of response.suite, not the top-level response.
"""

SUITE_SCHEMA_INSTRUCTION = """Build independent checks only from the task, never from an RTL implementation.
Do not invent unspecified initialization, port widths, signedness, priority, or latency.
Unsupported: inout/tri-state, real arithmetic, unresolvable parameters,
unsupported operators, or uncertain output-sampling semantics. State unsupported honestly.
Suite schema:
{"schema_version":1,"mode":"behavior" or "stimulus",
 "ports":{"signal":{"direction":"input" or "output","width":positive integer,"signed":false}},
 "clock":null or {"port":"clock input","edge":"posedge" or "negedge"},
 "requirements":[{"id":"r1","quote":"exact verbatim excerpt from task"}],
 "state":{"model_register":{"width":integer,"next":expression}},
 "outputs":{"output_port":expression},
 "cases":[{"id":"case1","requirements":["r1"],"steps":[{"inputs":{"every non-clock input":integer},"edge":true,"sample":true}]}]}
Use model_ as the prefix for EVERY model state name, separate from input/output ports.
For mode=behavior, state and outputs are required JSON objects, never null.
For stateless logic use "state":{}; never use "state":null. For combinational logic use
"clock":null. Whenever outputs is present, it must be an object mapping output port names
to expression objects, never null, an array, or a string.
Each case starts in a fresh DUT instance. Initial register values are UNKNOWN unless
the task explicitly gives an initial assignment. Only then state.model_<signal> may add
"initial":{"value":integer,"signal":"<signal>","quote":"exact initialization excerpt"}.
The host must recognize an explicit Verilog initial assignment or an explicit sentence
saying the signal is initialized to that number in an initial statement. Reset values
and plausible defaults do not establish initialization. All other states remain UNKNOWN. No implicit reset exists: merely driving reset never changes model state;
synchronous reset MUST be an explicit condition in state.next. Drive a reset explicitly
before sampling state-dependent outputs; sample:false
still executes the step but excludes it from comparison. Every step specifies ALL non-clock
inputs. Clock pulses are produced by the fixed driver, one effective edge per step by default;
edge:false changes inputs and samples without a clock edge. Read outputs after the transition.
Triggered state.next expressions see one OLD state snapshot and update together; outputs
see NEW state. Any newly asserted asynchronous reset settles before this edge snapshot.
With the single "clock" format, OMIT state.clock and use step.edge (not step.edges).
For asynchronous reset in this format add "async_reset":{"port":"reset input","active":0 or 1,
"values":{"every model_register":expression}}. A reset assertion (including an active
first drive) evaluates reset values and settles immediately after inputs change, even with
edge:false. While reset stays active, reset values are evaluated again only at an effective
edge of the affected state clock; without such an edge the state holds. Reset has priority
over next at that clock edge. Include a reset assertion with edge:false after non-reset
clocked operation of each affected domain, so
synchronous-only reset implementations can be distinguished. Quote the reset requirement.
Expressions must be objects: {"ref":"input or model_register"},
{"const":integer,"width":integer}, or {"op":"operator","args":[expressions],"width":integer}.
Operator argument counts are exact:
- TWO args: add sub mul and or xor shl shr asr eq ne lt le gt ge land lor.
- ONE arg: not bitnot neg slice reduce_and reduce_or reduce_xor.
- THREE args: ite (condition, true value, false value).
- ONE TO 32 args: concat.
add is binary, not a variadic sum or a unary wrapper. To sum several terms, use nested
binary add objects, each with an explicit result width chosen from the task semantics.
Do not introduce a one-argument add to widen a value; use an explicitly sized constant
and concat for zero extension when unsigned semantics require it.
and/or/xor/bitnot are bitwise; land/lor/not
are logical. not/land/lor MUST explicitly set result width=1, even for wider operands.
All comparisons and reductions also require explicit width=1. Do not infer missing widths.
ite takes condition,true,false.
slice takes one arg and lsb plus width; concat width is the sum of its arg widths.
Signed comparison/asr may add signed:true; arithmetic results are masked to explicit width.
No strings as executable expressions, no arbitrary Python, no code, no declarations.
For bounded multiple clocks, replace clock with "clocks":{"clk_a":{"edge":"posedge"},
"clk_b":{"edge":"negedge"}} (never both). Each state entry MUST set "clock":"clk_a";
each step sets "edges":["clk_a"] or [] or multiple clock names. The listed effective
edges happen simultaneously using OLD state; separate steps specify event order/frequency.
Clock inputs are omitted from inputs. After each step clocks return to inactive levels.
When using "clocks", even for ONE clock, use state.clock and step.edges; OMIT step.edge.
For asynchronous reset with "clocks", use "async_resets" even for ONE reset, never
"async_reset". Conversely, "async_resets" requires "clocks", not the single "clock" format.
Use "async_resets":[{"port":"rst","active":1,
"values":{"model_register":expression}}]; state subsets must not overlap. Async reset
assertion acts even on steps with no affected-domain edges; an unrelated clock edge
does not update reset-held state. Never infer initialization, synchronization or CDC safety.
For outputs defined only in a public validity domain, use "output_valid":{"out":one_bit_expr}
and/or "output_masks":{"out":output_width_expr}. Both evaluate after state transitions;
missing validity means true and missing mask means all bits. Compare only true validity
and mask bits set to 1; unknown validity/mask/value stays uncertain, never coerced to zero.
Mask/validity must follow quoted task requirements, never hide an inconvenient scenario.
Only whitespace differences in source quotations may be normalized; do not change punctuation
or content. A requirement may instead identify a provided source fragment via source_id.
Limits: 64 ports, 256 bits each, 64 state entries, 32 cases, 512 steps per case,
4096 total steps. Prefer 4..10 directed cases covering requirements, reset, priority,
boundary and hold; keep the result compact. For mode=stimulus, omit state and outputs;
provide only legal inputs and sampling times. For asynchronous reset in stimulus mode use
the single clock format with async_reset values:{} and include sampled edge:false reset
after inactive-reset clocked operation.
Each behavior case must list requirement ids in case.requirements. Every declared requirement
needs at least one bound case with a comparable output; every behavior case needs a comparison.
This mapping declares test intent, not proof of semantic coverage.
This mode observes outputs, not correctness.
For additional acceptance tests use new cases targeting omitted boundaries. Do not read or
infer from generated RTL, and do not relax a requirement merely because a prior check failed.
"""

SUITE_INSTRUCTION = SUITE_RESPONSE_INSTRUCTION + SUITE_SCHEMA_INSTRUCTION

PATCH_INSTRUCTION = (
    """Return only {"replacements":{"approved_name":expression,...}}.
Return exactly the names authorized in feedback, using the expression schema below.
Do not return a whole suite or change any other field. The host merges this patch into
previous_suite and revalidates all old cases, masks, validity and state metadata.
Derive changes only from the quoted public specification; no RTL or observations are provided.
"""
    + SUITE_SCHEMA_INSTRUCTION
)


def _normalize_state_names(suite):
    """Only rename output collisions: output ports are never expression symbols."""
    value = _thaw(suite)
    if not isinstance(value, dict) or not isinstance(value.get("state"), dict):
        return value, {}
    ports, state = value.get("ports"), value["state"]
    if not isinstance(ports, dict):
        return value, {}
    mapping, occupied = {}, set(ports) | set(state)
    for name in state:
        if name not in ports:
            continue
        if (
            not isinstance(ports[name], dict)
            or ports[name].get("direction") != "output"
        ):
            raise SuiteError(
                "model state collides with an input; expression references are ambiguous"
            )
        replacement = "model_" + name
        suffix = 2
        while replacement in occupied:
            replacement = "model_" + name + "_" + str(suffix)
            suffix += 1
        mapping[name] = replacement
        occupied.add(replacement)
    if not mapping:
        return value, {}

    def expression(expr):
        if not isinstance(expr, dict):
            return expr
        if set(expr) == {"ref"}:
            return {"ref": mapping.get(expr["ref"], expr["ref"])}
        return {
            key: [expression(a) for a in item]
            if key == "args" and isinstance(item, list)
            else item
            for key, item in expr.items()
        }

    value["state"] = {
        mapping.get(name, name): {**register, "next": expression(register.get("next"))}
        if isinstance(register, dict)
        else register
        for name, register in state.items()
    }
    for key in ("outputs", "output_valid", "output_masks"):
        if isinstance(value.get(key), dict):
            value[key] = {name: expression(expr) for name, expr in value[key].items()}
    resets = (
        [value["async_reset"]] if isinstance(value.get("async_reset"), dict) else []
    )
    if isinstance(value.get("async_resets"), list):
        resets += value["async_resets"]
    for reset in resets:
        if isinstance(reset, dict) and isinstance(reset.get("values"), dict):
            reset["values"] = {
                mapping.get(name, name): expression(expr)
                for name, expr in reset["values"].items()
            }
    return value, mapping


_REVISION_CONSTRAINTS = (
    "Retain every original case id, input sequence, clock edges and sample. "
    "Retain ports, state names, clocks, reset bindings/polarity, output validity/masks "
    "and source quotations, including explicit initial metadata. Only edit expressions named by target/names. "
    "These same restrictions apply to every local correction; never delete old stimuli, "
    "weaken requirements, invent initialization, or replace unknown values with zero."
)


class SuiteBuilder:
    def __init__(
        self,
        construction_retries=1,
        generation_max_tokens=8192,
        review_max_tokens=4096,
        reserve_s=120,
    ):
        if any(
            type(cap) is not int or not 1 <= cap <= 32768
            for cap in (generation_max_tokens, review_max_tokens)
        ):
            raise ValueError("suite/review token cap must be in 1..32768")
        if not math.isfinite(reserve_s) or reserve_s < 0:
            raise ValueError("reserve_s must be finite and nonnegative")
        self.construction_retries = construction_retries
        self.generation_max_tokens = generation_max_tokens
        self.review_max_tokens = review_max_tokens
        self.reserve_s = reserve_s
        if type(construction_retries) is not int or not 0 <= construction_retries <= 2:
            raise ValueError("construction_retries must be in 0..2")

    @staticmethod
    def _validate_async_coverage(suite, task_text):
        # Clock domains may be asynchronous while their resets remain synchronous.
        # Enforce this host gate only for an explicit reset/clear phrase; semantic
        # ambiguities and names such as rst_n remain the independent review's job.
        async_word = r"async(?:hronous(?:ly)?)?"
        reset_phrase = (
            r"\b" + async_word + r"\b(?:[\s-]+(?:active|low|high|level|sensitive))*"
            r"[\s-]+(?:reset|clear)(?:s|ting|ing)?\b|"
            r"\b(?:reset|clear)(?:[\s-]+(?:is|must|be|shall|an|a|signal|input|active|low|high|and))*"
            r"[\s-]+"
            + async_word
            + r"\b|异步(?:的|低电平|高电平|有效|\s)*(?:复位|清零)|"
            r"(?:复位|清零)(?:为|是|采用|使用|\s)*异步"
        )
        explicit_reset = lambda text: bool(re.search(reset_phrase, text, re.IGNORECASE))
        if not explicit_reset(task_text):
            return
        resets = suite.get("async_resets") or (
            [suite["async_reset"]] if suite.get("async_reset") else []
        )
        quoted = any(explicit_reset(r["quote"]) for r in suite["requirements"])
        clocks = set(suite.get("clocks", {}))
        if suite.get("clock"):
            clocks = {suite["clock"]["port"]}
        for reset in resets:
            affected = (
                {suite["state"][name]["clock"] for name in reset["values"]}
                if suite.get("clocks")
                else clocks
            )
            # Stimulus mode has no model state to identify a reset's domain;
            # conservatively require inactive-reset operation of every clock.
            affected = affected or clocks
            covered = False
            for case in suite["cases"]:
                clocked_inactive, previously_inactive = set(), False
                for step in case["steps"]:
                    active = step["inputs"][reset["port"]] == reset["active"]
                    edges = (
                        set(step["edges"])
                        if suite.get("clocks")
                        else (clocks if step.get("edge", True) else set())
                    )
                    covered |= (
                        not (edges & affected)
                        and step.get("sample", True)
                        and active
                        and previously_inactive
                        and affected <= clocked_inactive
                    )
                    if not active:
                        clocked_inactive.update(edges & affected)
                    previously_inactive = not active
            if not covered:
                raise SuiteError(
                    "asynchronous reset requires an off-edge sampled reset scenario "
                    "after inactive-reset clocking of every affected domain"
                )
        if not resets or not quoted:
            raise SuiteError(
                "asynchronous reset requires a quoted explicit reset model"
            )

    def run(self, ctx, input):
        task_text = input.task.prompt + "\n" + input.task.interface
        revision = None
        source_scope = "task_only"
        if input.mode == "behavior" and input.previous is not None:
            try:
                revision = json.loads(input.feedback)
                if (
                    not isinstance(revision, dict)
                    or set(revision) != {"kind", "origin", "quote", "target", "names"}
                    or revision["kind"] != "specification_revision"
                    or revision["origin"] != "code_aware_diagnosis"
                    or revision["target"]
                    not in ("outputs", "state_next", "async_reset_values")
                ):
                    raise SuiteError("checker revision request has unknown fields")
                revision["quote"] = resolve_quote(revision["quote"], task_text)["quote"]
                signals = (
                    input.previous.get("outputs", {})
                    if revision["target"] == "outputs"
                    else input.previous.get("state", {})
                )
                if (
                    not isinstance(revision["names"], list)
                    or not revision["names"]
                    or any(
                        not isinstance(n, str) or n not in signals
                        for n in revision["names"]
                    )
                ):
                    raise SuiteError(
                        "checker revision names must refer to existing model signals"
                    )
                source_scope = "specification_revision_after_code_aware_diagnosis"
            except (ValueError, TypeError, KeyError) as error:
                ctx.record.emit(
                    "suite",
                    "functional_suite",
                    status="invalid",
                    attempt=0,
                    reason=str(error),
                    source_scope=source_scope,
                )
                return SuiteBuild("invalid", reason=str(error))
        feedback = (
            json.dumps(revision, ensure_ascii=False) if revision else input.feedback
        )
        failure, draft, call_id = None, None, None
        rejected = set()
        previous_response = None
        raw_text, raw_metadata = None, {}
        for attempt in range(1, self.construction_retries + 2):
            context = {
                "mode": input.mode,
                "feedback": feedback,
                "previous_suite": input.previous,
                "source_scope": source_scope,
                "source_catalog": source_catalog(task_text),
                "revision_constraints": _REVISION_CONSTRAINTS if revision else None,
                "construction_attempt": attempt,
            }
            if failure:
                context.update(
                    construction_feedback=failure,
                    previous_draft=draft,
                    previous_response=previous_response,
                    response_contract=PATCH_INSTRUCTION
                    if revision
                    else SUITE_RESPONSE_INSTRUCTION,
                    correction_constraints="Correct only the stated construction/review defects using the task. "
                    "Preserve every existing case id, input sequence, clock edge and sample, and all "
                    "behavior not implicated by the stated defect, including reset and update phase. "
                    "Do not infer reset or unspecified values. Preserve every original revision constraint. "
                    "previous_response is the entire prior parsed response, even if its envelope is invalid. "
                    "previous_draft is only its suite field, NOT the response format to return. "
                    "Return the authorized replacements object for a revision, otherwise the complete status/suite response. "
                    "previous_raw_text, if present, is unparsed invalid "
                    "reply content and may be a truncated prefix as its metadata states, never an accepted suite.",
                )
                if raw_text is not None:
                    context.update(
                        previous_raw_text=raw_text,
                        previous_raw_text_metadata=raw_metadata,
                    )
            result = request(
                ctx,
                PATCH_INSTRUCTION if revision else SUITE_INSTRUCTION,
                "functional_suite_patch" if revision else "functional_suite",
                context,
                max_tokens=self.generation_max_tokens,
                reserve_s=self.reserve_s,
            )
            call_id, review_id, preflight, mapping, changes = (
                result.call_id,
                None,
                None,
                {},
                [],
            )
            raw_text, raw_metadata = result.raw_text, _thaw(result.raw_text_metadata)
            previous_response = _thaw(result.data) if result.status == "ready" else None
            stage = "json"
            if result.status != "ready":
                reason = result.reason or "structured suite reply is invalid"
                draft = None
            elif result.data.get("status") == "unsupported":
                reason = str(result.data.get("reason", "unsupported"))[:1000]
                stage = "unsupported_review"
                audit = request(
                    ctx,
                    SUITE_SCHEMA_INSTRUCTION
                    + "\nReview the claimed inability independently. "
                    "Distinguish a missing checker capability, genuinely missing task semantics, "
                    "and difficulty generating the model. Complexity alone is not unsupported. "
                    "Return confirmed:boolean, kind:capability|specification|model_limitation, "
                    "quote or source_id from the task, and a concrete reason. Only confirm if a "
                    "necessary public behavior cannot be represented by the supported semantics. "
                    "If representable, reject and explain an available construction strategy.",
                    "functional_unsupported_review",
                    {"claim": reason, "source_catalog": source_catalog(task_text)},
                    max_tokens=self.review_max_tokens,
                    reserve_s=self.reserve_s,
                )
                review_id = audit.call_id
                if (
                    audit.status == "ready"
                    and audit.data.get("confirmed")
                    and audit.data.get("kind") != "model_limitation"
                ):
                    ctx.record.emit(
                        "suite",
                        "functional_suite",
                        status="unsupported",
                        attempt=attempt,
                        call_id=call_id,
                        review_call_id=review_id,
                        reason=reason,
                        unsupported_kind=audit.data["kind"],
                        review_reason=audit.data["reason"],
                        review_source=resolve_requirement(audit.data, task_text),
                        source_scope=source_scope,
                    )
                    return SuiteBuild("unsupported", call_id=call_id, reason=reason)
                reason = "unsupported claim not confirmed: " + str(
                    audit.data.get("reason", audit.reason)
                )
                draft = None
            else:
                draft = _thaw(result.data.get("suite"))
                try:
                    stage = "revision" if revision else "validator"
                    if revision:
                        draft = apply_expression_patch(
                            input.previous, result.data, revision, task_text=task_text
                        )
                    stage = "validator"
                    if not revision and result.data.get("status") != "ready":
                        raise SuiteError(
                            "suite response status must be ready or unsupported"
                        )
                    suite, mapping = _normalize_state_names(draft)
                    if isinstance(suite, dict):
                        suite["requirements"] = normalize_requirements(
                            suite.get("requirements"), task_text
                        )
                    suite = validate_suite(suite, task_text=task_text)
                    if suite["mode"] != input.mode:
                        raise SuiteError("suite mode differs from requested mode")
                    changes = (
                        validate_revision(input.previous, suite, revision)
                        if revision
                        else []
                    )
                    expected = input.task.expected_interface
                    for port in expected.ports:
                        actual = suite["ports"].get(port.name)
                        if (
                            actual is None
                            or port.direction
                            and actual["direction"] != port.direction
                            or port.width
                            and actual["width"] != port.width
                        ):
                            raise SuiteError(
                                "suite disagrees with task-declared port " + port.name
                            )
                    if getattr(expected, "complete", True) and set(suite["ports"]) != {
                        p.name for p in expected.ports
                    }:
                        raise SuiteError(
                            "suite must use exactly the task-declared ports"
                        )
                    self._validate_async_coverage(suite, task_text)
                    stage = "expectation_selfcheck"
                    preflight = (
                        require_comparable_expectations(suite, task_text=task_text)
                        if input.mode == "behavior"
                        else analyze_expectations(suite)
                    )
                    coverage = (
                        require_requirement_coverage(suite)
                        if input.mode == "behavior"
                        else None
                    )
                    stage = "review"
                    review = request(
                        ctx,
                        SUITE_SCHEMA_INSTRUCTION + "\n"
                        "Independently review this fallible suite against the original task and the FULL "
                        "execution semantics above. No implicit reset exists. Inspect the independent "
                        "expectation_preflight, widths, output validity/masks and unknown counts; partial "
                        "uncertainty limits coverage and is never a pass. Check each transition, quotation, "
                        "priority and old/new state sampling. Reject invented defaults or weakened checks. "
                        "For revisions enforce all revision_constraints. Return "
                        '{"accepted":boolean,"quote":"task excerpt","reason":"specific explanation"}. '
                        "Do not accept merely because JSON is valid or the suite agrees with an implementation. "
                        "For stimulus mode review legality and coverage without claiming correctness.",
                        "functional_suite_review",
                        {
                            "mode": input.mode,
                            "suite": suite,
                            "expectation_preflight": {
                                k: v
                                for k, v in preflight.items()
                                if k != "comparison_events"
                            },
                            "requirement_coverage": coverage,
                            "widths": {
                                n: p["width"] for n, p in suite["ports"].items()
                            },
                            "state_widths": {
                                n: p["width"] for n, p in suite["state"].items()
                            },
                            "source_catalog": source_catalog(task_text),
                            "previous_suite": input.previous,
                            "revision_reason": feedback,
                            "revision_constraints": _REVISION_CONSTRAINTS
                            if revision
                            else None,
                        },
                        max_tokens=self.review_max_tokens,
                        reserve_s=self.reserve_s,
                    )
                    review_id = review.call_id
                    if (
                        review.status != "ready"
                        or review.data.get("accepted") is not True
                        or not isinstance(review.data.get("reason"), str)
                        or not review.data["reason"].strip()
                    ):
                        raise SuiteError(
                            "independent suite review did not accept: "
                            + str(review.data.get("reason", review.reason))[:800]
                        )
                    review_source = resolve_requirement(review.data, task_text)
                    ctx.record.emit(
                        "suite",
                        "functional_suite",
                        status="ready",
                        attempt=attempt,
                        construction_retries_used=attempt - 1,
                        suite_hash=suite_hash(suite),
                        call_id=call_id,
                        review_call_id=review_id,
                        mode=input.mode,
                        suite=suite,
                        source_scope=source_scope,
                        requirement_sources=suite["requirements"],
                        review_source=review_source,
                        revision_changes=changes,
                        state_name_mapping=mapping,
                        expectation_preflight=preflight,
                        requirement_coverage=coverage,
                    )
                    return SuiteBuild("ready", suite, call_id)
                except (ValueError, KeyError, TypeError, AttributeError) as error:
                    reason = str(error)
            rejected_key = hashlib.sha256(
                json.dumps(
                    [
                        stage,
                        result.data,
                        result.raw_text_metadata.get("original_sha256"),
                        reason,
                    ],
                    sort_keys=True,
                ).encode()
            ).hexdigest()
            no_progress = rejected_key in rejected or result.raw_text_metadata.get(
                "no_progress", False
            )
            rejected.add(rejected_key)
            if no_progress:
                reason = "repeated rejected construction: no progress; " + reason
            failure = {
                "stage": stage,
                "reason": reason,
                "attempt": attempt,
                "call_id": call_id,
                "review_call_id": review_id,
            }
            if preflight is not None:
                failure["expectation_preflight"] = preflight
            ctx.record.emit(
                "suite",
                "functional_suite",
                status="invalid",
                **failure,
                source_scope=source_scope,
                state_name_mapping=mapping,
                recovery_remaining=self.construction_retries + 1 - attempt,
                no_progress=no_progress,
            )
            if no_progress:
                break
        return SuiteBuild("invalid", call_id=call_id, reason=reason)


def build_suite(
    ctx,
    *,
    feedback="",
    previous=None,
    construction_retries=1,
    generation_max_tokens=8192,
    review_max_tokens=4096,
    reserve_s=120,
):
    return SuiteBuilder(
        construction_retries, generation_max_tokens, review_max_tokens, reserve_s
    ).run(
        ctx,
        SimpleNamespace(
            task=ctx.task, mode="behavior", feedback=feedback, previous=previous
        ),
    )


@node("build_suite", reads=[], writes=["suite_status"])
def initial_suite(
    ctx: Ctx,
    state: State,
    *,
    construction_retries: int = 1,
    generation_max_tokens: int = 8192,
    review_max_tokens: int = 4096,
    reserve_s: float = 120,
) -> State:
    build = build_suite(
        ctx,
        construction_retries=construction_retries,
        generation_max_tokens=generation_max_tokens,
        review_max_tokens=review_max_tokens,
        reserve_s=reserve_s,
    )
    ctx.store["suite_options"] = dict(
        construction_retries=construction_retries,
        generation_max_tokens=generation_max_tokens,
        review_max_tokens=review_max_tokens,
        reserve_s=reserve_s,
    )
    ctx.store["suites"] = (
        {suite_hash(build.suite): build.suite} if build.status == "ready" else {}
    )
    ctx.store["candidates"] = {}
    ctx.store["structural"] = {}
    ctx.store["evidence"] = {}
    ctx.store["seen"] = set()
    return state.update(suite_status=build.status)
