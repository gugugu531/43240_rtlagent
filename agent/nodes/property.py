"""Source-only property construction and finite Vivado checks as recorded actions."""
from dataclasses import dataclass
import math

from agent.core.components import Node, Tool
from agent.core.property import PropertyCheckInput, PropertyBuild, PropertyBuildInput
from agent.core.research import JsonInput, JsonOutput
from agent.core.state import CheckResult
from agent.core.tool import CheckOutcome
from agent.services.property_sim import validate_suite


PROPERTY_INSTRUCTION = '''Build a restricted property suite from the task ONLY.
Return {"status":"ready","suite":{...}} or {"status":"unsupported","reason":"..."}.
Do not infer unspecified behavior. Unsigned fixed-width ports only, no inout,
multiple clocks, arbitrary internal states or code strings. Describe all ports.
Suite fields: version (positive integer), ports:[{name,direction,width}],
clock:null or {name,edge:"posedge"/"negedge"}, startup:[], warmup:0,
assumptions:[], properties:[], cases:[], unsupported_requirements:[strings].
Each assumption/property: {id,quote,when,assert}; quote must be an EXACT task
substring, when/assert are one-bit expression trees. Signals are name strings;
constants are {"const":unsigned integer,"width":integer}. Expression objects:
{"op":name,"args":[...]}. Allowed binary ops eq/ne/lt/le/gt/ge/add/sub/and/or/xor/
land/lor/shl/shr; unary not/lnot/reduce_or/reduce_and/reduce_xor; mux has 3 args;
concat has multiple args; slice has one arg plus hi/lo integers. Widths must
match for binary ops except shifts. Logical ops require one-bit values. No
implicit signed casts. A single non-nested past op is supported for sequential
properties. Properties are sampled immediately BEFORE each active clock edge;
past reads the previous such sample. E.g. q after clear at previous edge means
when=past(clear), assert=eq(q,zero). Explicitly use correct widths.
For sequential tasks provide a SOURCE-GROUNDED reset input sequence as startup:
[{"values":{"reset":1},"quote":"exact reset wording"},...]; no clock or output
assignment. warmup must be at least len(startup)+1, leaving at least one checked step in every case.
No arbitrary initialization assumptions; unsupported if reset cannot establish
known state. Assumptions restrict INPUTS ONLY and need explicit task support;
normally leave assumptions empty. Do not constrain outputs to hide failures.
At most 8 properties and 8 assumptions. Include stimuli that actually trigger each property.
cases is a nonempty list of {id,inputs:[maps]}. Each map explicitly assigns
EVERY non-clock input using unsigned integers; do not assign outputs or the
clock. Sequential cases must start with the declared reset startup sequence,
then exercise reset overlap, hold, priority and boundaries. Combinational cases
should include boundary values and distinguishing combinations. At most 16
cases and 2048 total sampled steps. This is FINITE SIMULATION ONLY, not proof.
Version increments when revising; retain valid properties and existing cases.
When previous is supplied, change ONLY when/assert of the property ids named
in feedback. Keep all ids, source quotes, ports, clock, startup, assumptions,
cases and unsupported requirements exactly unchanged; do not add or delete
properties. Increment only the version alongside those named expressions.
Previous suite/feedback may describe a CHECKER defect; correct only with task
evidence, never to agree with an RTL output. Do not include executable code.'''


class PropertyBuildNode(Node[PropertyBuildInput, PropertyBuild]):
    component_name = 'property_build'
    assembly_roles = ['property_build']
    assembly_defaults = {'params': {}, 'dependencies': {
        'json': {'component': 'research_json', 'id': 'json'}}}
    input_type = PropertyBuildInput
    output_type = PropertyBuild
    dependencies = {'json': 'node'}
    dependency_types = {'json': (JsonInput, JsonOutput)}

    def __init__(self, json: Node[JsonInput, JsonOutput]):
        self.json = json

    def run(self, ctx, input: PropertyBuildInput) -> PropertyBuild:
        answer = ctx.execute(self.json, JsonInput(input.task, PROPERTY_INSTRUCTION,
            'property_build', {'feedback': input.feedback, 'previous': input.previous}))
        if answer.status != 'ready':
            return PropertyBuild('invalid', call_id=answer.call_id, reason=answer.reason)
        if answer.data.get('status') == 'unsupported':
            return PropertyBuild('unsupported', call_id=answer.call_id,
                                 reason=str(answer.data.get('reason', 'unsupported')))
        if answer.data.get('status') != 'ready':
            return PropertyBuild('invalid', call_id=answer.call_id, reason='missing ready status')
        try:
            suite = validate_suite(answer.data.get('suite'), input.task)
        except (ValueError, KeyError, TypeError) as exc:
            return PropertyBuild('invalid', call_id=answer.call_id, reason=str(exc))
        return PropertyBuild('ready', suite, answer.call_id)


@dataclass(frozen=True)
class PropertySimulationNode(Node[PropertyCheckInput, CheckResult]):
    component_name = 'property_sim_check'
    assembly_roles = ['property_check']
    assembly_defaults = {'params': {'timeout_s': 600.0}, 'dependencies': {
        'tool': {'component': 'property_sim_tool', 'id': 'property_tool'}}}
    input_type = PropertyCheckInput
    output_type = CheckResult
    dependencies = {'tool': 'tool'}
    dependency_types = {'tool': (PropertyCheckInput, CheckOutcome)}
    tool: Tool[PropertyCheckInput, CheckOutcome]
    timeout_s: float = 600.0

    def __post_init__(self):
        if getattr(self.tool, 'check_kind', None) != 'property_sim':
            raise ValueError('property node requires a Vivado property tool')
        if not math.isfinite(self.timeout_s) or self.timeout_s <= 0:
            raise ValueError('property timeout must be positive and finite')

    def run(self, ctx, input: PropertyCheckInput) -> CheckResult:
        return ctx.check(self.tool, input, candidate=input.candidate,
                         timeout_s=ctx.budget.timeout_s(self.timeout_s))
