"""Independent test-plan generation and candidate simulation actions."""
from dataclasses import dataclass
import json
from agent.core.components import Node, Tool
from agent.core.model import ModelRequest, ModelCallError
from agent.core.task import TaskSpec
from agent.services.behavior import parse_plan, literal_truth_table_plan
from agent.services.behavior_types import PlanResult, BehaviorInput
from agent.core.state import CheckResult
from agent.core.tool import CheckOutcome
from agent.services.plan_format import evidence_catalog
from agent.services.literal_spec import plan_kind
from agent.services.spec_ports import supported_ports


COMMON_PROMPT = '''Generate a SMALL self-test plan from the original RTL specification ONLY.
You cannot see candidate code, reference answers, official testbenches or judge feedback.
Return exactly one valid JSON object. No prose, markdown, HDL, Python or extra fields.
JSON numbers MUST be decimal unsigned integers: write 255, NEVER bare 0xff or 8'hff.
You may instead use a JSON STRING such as "255", "0", "0xff", "0b1111" or "0o17" for signal values.
Use actual declared ports, their widths and the original specification. Do not guess.

Evidence paragraphs have zero-based IDs. Each basis is a NONEMPTY
array of those integer IDs. Select the paragraphs that really support the claim;
do not write a quotation, paraphrase or instruction placeholder. Multiple IDs may
be needed because port declarations and behavior are in different paragraphs.
An evidence reference is only grounding, not proof that an expected value is correct.
Do not use candidate agreement, benchmark memories or internal signals as an oracle.
'''

COMBINATIONAL_PROMPT = COMMON_PROMPT + '''This task is routed to the COMBINATIONAL plan format.
Only use the current declared input values and public specification. No clock or
reset is required for a combinational circuit. Do not reject a task merely because
these ports are absent. Do not impose a sequential schema or invent storage.
A wide input may already contain several bytes: inspect its width before inferring
missing input history. Karnaugh maps, case mappings and population count are valid
combinational specifications; choose small unambiguous patterns within port widths.
If the actual specification has unresolved temporal behavior, return only
{"unsupported":"specific ambiguity in the original specification"}.
Top-level fields are timing and steps.
timing is exactly {"kind":"combinational"}.
Each step has exactly inputs (port-value object), wait_ns (positive integer),
expected (output-value object), basis (evidence ID array).
First step initializes ALL inputs. Later inputs retain values when omitted.
Use at most 12 steps with boundaries and contrasting input patterns.
wait_ns is an integer (normally 1), never 0, 0.5 or a string.
Do not write cycles or sequential timing fields.'''

SEQUENTIAL_PROMPT = COMMON_PROMPT + '''This task is routed to the SEQUENTIAL plan format.
reset_values specifically MUST contain decimal integer values, not strings.
reset_basis follows the same nonempty evidence-ID-array rule as basis.
Top-level fields are timing and cycles. Do NOT write steps.
Only a single-clock resettable design with ONE output register bank is supported.
Multiple outputs, even if all are registered, are unsupported in this version.
timing has exactly these fields:
kind = "sequential"; clock = actual clock input name; edge = "posedge" or "negedge";
reset = actual reset input name; reset_active = 0 or 1;
reset_kind = "synchronous" or "asynchronous";
reset_values = object containing the specified decimal reset value of EVERY output;
basis = evidence IDs covering the clock, active edge and ALL registered outputs;
reset_basis = evidence IDs covering reset polarity, sync/async kind and output reset literals.
For a single output register bank, "all DFFs", "the output", or "the counter"
may refer to that unique output. Include the paragraph describing the DFF/counter/
shift register/LFSR as well as clock and reset clauses. Literal "zero" and "one"
are explicit reset values; "cleared" or an omitted reset value are not.
Do not infer an FSM output reset value merely from its reset state name.
If behavioral text says only "the clock", include the paragraph declaring the actual
clock port as well as the paragraph describing its active edge. Include all needed IDs.
Never copy default port names or default reset values; derive them from the specification.
Each cycle has exactly inputs (DATA inputs only), expected (outputs AFTER this cycle's
active edge), basis (supporting evidence IDs). First cycle initializes ALL data inputs.
Later omitted data inputs retain values. NEVER put clock or reset in cycle inputs.
The scheduler asserts reset, applies one effective reset edge, checks reset values,
then releases reset while the clock is inactive, before cycle 0.
The scheduler prepares data while the clock is inactive, applies exactly ONE active
edge per cycle and samples AFTER settling. Do NOT encode half-cycles yourself.
There has been one reset edge before cycle 0, but ZERO functional data bits/cycles.
Track the complete input history from cycle 0. Do not claim a sequence was detected
before enough bits were sampled. For LFSRs, calculate the stated direction and taps.
Use at most 12 cycles. Every nonempty expected needs evidence IDs. If output state
is unspecified, use expected:{} and basis:"" rather than inventing an expectation.

For ambiguous/missing reset or clock, mixed registered/combinational outputs, latches,
multiple clocks or unsupported literals return only {"unsupported":"specific reason"}.
The DUT's internal state encoding is not needed to test specified port behavior;
do not reject solely because the state encoding is not specified.'''

UNCERTAIN_PROMPT = COMMON_PROMPT + '''The public specification cannot safely be routed
to our supported timing formats. Return only {"unsupported":"the specific unresolved
temporal or interface ambiguity"}. Do not guess initialization or invent a clock.'''


def plan_messages(task):
    catalog = [dict(id=index, text=span) for index, span in enumerate(evidence_catalog(task.prompt))]
    prompt = {'combinational': COMBINATIONAL_PROMPT, 'sequential': SEQUENTIAL_PROMPT,
              'uncertain': UNCERTAIN_PROMPT}[plan_kind(task)]
    return [dict(role='system', content=prompt), dict(role='user', content=
        task.prompt + '\n\nParsed interface:\n' + json.dumps(task.expected_interface.public_dict()) +
        '\n\nEvidence catalog (exact original paragraphs):\n' + json.dumps(catalog, ensure_ascii=False))]


@dataclass(frozen=True)
class TestPlanNode(Node[TaskSpec, PlanResult]):
    component_name = 'spec_test_plan'
    input_type = TaskSpec
    output_type = PlanResult
    max_tokens: int = 4096
    timeout_s: float = 90.0
    top_p: float = 1.0

    def __post_init__(self):
        ModelRequest([], max_tokens=self.max_tokens, temperature=0.0,
                     top_p=self.top_p, timeout_s=self.timeout_s)

    def run(self, ctx, task: TaskSpec):
        if task != ctx.task:
            raise ValueError('self-test plan must use the current public task')
        try:
            supported_ports(task)
        except ValueError as exc:
            ctx.emit('test_plan_unavailable', reason=str(exc))
            return PlanResult(None, '', str(exc))
        literal = literal_truth_table_plan(task)
        if literal is not None:
            ctx.emit('test_plan', call_id='', plan_hash=literal.fingerprint,
                     plan=literal.public_dict(), oracle_source=literal.oracle_source,
                     official_verification=False, generation='deterministic_public_literals')
            return PlanResult(literal, '')
        ctx.emit('test_plan_route', kind=plan_kind(task), validator_relaxed=False)
        messages = plan_messages(task)
        try:
            reply = ctx.llm.chat(ModelRequest(messages, max_tokens=self.max_tokens, temperature=0.0,
                top_p=self.top_p, timeout_s=ctx.budget.timeout_s(self.timeout_s), purpose='spec_test_plan'))
        except ModelCallError as exc:
            ctx.emit('test_plan_unavailable', call_id=exc.call_id, reason='model_' + exc.kind)
            return PlanResult(None, exc.call_id or '', 'model_' + exc.kind)
        try:
            if reply.finish_reason == 'length':
                raise ValueError('truncated test plan')
            plan = parse_plan(reply.content, task)
        except (ValueError, TypeError, OverflowError) as exc:
            ctx.emit('test_plan_unavailable', call_id=reply.call_id, reason=str(exc))
            return PlanResult(None, reply.call_id, str(exc))
        ctx.emit('test_plan', call_id=reply.call_id, plan_hash=plan.fingerprint,
                 plan=plan.public_dict(), oracle_source=plan.oracle_source, official_verification=False)
        return PlanResult(plan, reply.call_id)


@dataclass(frozen=True)
class BehaviorNode(Node[BehaviorInput, CheckResult]):
    component_name = 'spec_behavior_check'
    input_type = BehaviorInput
    output_type = CheckResult
    dependencies = {'tool': 'tool'}
    dependency_types = {'tool': (BehaviorInput, CheckOutcome)}
    tool: Tool[BehaviorInput, CheckOutcome]
    timeout_s: float = 60.0

    def __post_init__(self):
        if getattr(self.tool, 'check_kind', None) != 'behavior':
            raise ValueError('behavior node requires a behavior check tool')

    def run(self, ctx, input: BehaviorInput):
        timeout = ctx.budget.timeout_s(self.timeout_s)
        return ctx.check(self.tool, input, candidate=input.candidate, timeout_s=timeout)
