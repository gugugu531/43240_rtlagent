"""Functional observations from a generated, explicitly scoped suite."""
from agent.core.components import Tool
from agent.core.research import FunctionalInput
from agent.core.tool import CheckOutcome
from agent.services.functional import simulate, suite_hash


class FunctionalSimTool(Tool[FunctionalInput, CheckOutcome]):
    component_name = 'functional_sim_tool'
    assembly_roles = ['functional_tool']
    assembly_defaults = {'params': {}, 'dependencies': {}}
    check_kind = 'functional'
    input_type = FunctionalInput
    output_type = CheckOutcome

    def __init__(self, save_vcd: bool = False):
        if type(save_vcd) is not bool:
            raise ValueError('save_vcd must be boolean')
        self.save_vcd = save_vcd

    def run(self, ctx, input: FunctionalInput) -> CheckOutcome:
        # No cache opt-in: suite, driver, timing and binary identities all matter.
        try:
            return simulate(ctx, input, save_vcd=self.save_vcd)
        except OSError as error:
            return CheckOutcome('unavailable', 'simulation I/O failed: ' + str(error),
                details={'suite_hash': suite_hash(input.suite), 'traces': [],
                         'passed_cases': [], 'failed_cases': [], 'first_mismatch': None,
                         'attribution': 'environment', 'failure_kind': 'environment'})
