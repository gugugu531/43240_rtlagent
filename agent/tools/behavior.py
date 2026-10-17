"""Public self-test simulation capability."""
from agent.core.components import Tool
from agent.core.tool import CheckOutcome
from agent.services.behavior_types import BehaviorInput
from agent.tools.vivado import outcome, toolchain_identity


class BehaviorCheckTool(Tool[BehaviorInput, CheckOutcome]):
    component_name = 'spec_behavior_check_tool'
    assembly_roles = ['behavior_tool']
    assembly_defaults = {'params': {}, 'dependencies': {}}
    check_kind = 'behavior'
    input_type = BehaviorInput
    output_type = CheckOutcome

    def cache_identity(self, ctx) -> str | None:
        return toolchain_identity(ctx, 'behavior_fingerprint')

    def replay_identity(self, ctx) -> str | None:
        return toolchain_identity(ctx, 'replay_fingerprint')

    def cache_request(self, input: BehaviorInput):
        return {'code_hash': input.candidate.code_hash,
                'plan_hash': input.plan.fingerprint, 'top': input.plan.top}

    def run(self, ctx, input: BehaviorInput) -> CheckOutcome:
        return outcome(ctx.toolchain().behavior(input.candidate.code, input.plan.top,
                                                input.plan, timeout_s=ctx.timeout_s))
