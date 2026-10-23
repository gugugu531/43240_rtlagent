"""Property checking and counterexample replay exclusively through Vivado."""
from dataclasses import dataclass

from agent.core.components import Tool
from agent.core.property import PropertyCheckInput
from agent.core.tool import CheckOutcome
from agent.services.property_sim import PropertySimulationService


@dataclass(frozen=True)
class PropertySimulationTool(Tool[PropertyCheckInput, CheckOutcome]):
    component_name = 'property_sim_tool'
    assembly_roles = ['property_tool']
    assembly_defaults = {'params': {}, 'dependencies': {}}
    input_type = PropertyCheckInput
    output_type = CheckOutcome
    check_kind = 'property_sim'
    xvlog_bin: str | None = None
    xelab_bin: str | None = None
    xsim_bin: str | None = None

    def __post_init__(self):
        if any(v is not None and (not isinstance(v, str) or not v.strip()) for v in
               (self.xvlog_bin, self.xelab_bin, self.xsim_bin)):
            raise ValueError('Vivado executable overrides must be nonempty paths or null')

    def run(self, ctx, input: PropertyCheckInput) -> CheckOutcome:
        return PropertySimulationService(xvlog_bin=self.xvlog_bin,
            xelab_bin=self.xelab_bin, xsim_bin=self.xsim_bin).run(ctx, input)
