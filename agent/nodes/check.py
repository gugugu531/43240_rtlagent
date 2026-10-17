"""Checks produce evidence; workflows choose what to do with it."""
from dataclasses import dataclass
from agent.core.candidate import Candidate
from agent.core.components import Node, Tool
from agent.core.state import CheckResult
from agent.core.tool import CheckOutcome


@dataclass(frozen=True)
class CheckInput:
    candidate: Candidate


class InterfaceNode(Node[CheckInput, CheckResult]):
    component_name = 'interface_check'
    input_type = CheckInput
    output_type = CheckResult
    dependencies = {'tool': 'tool'}
    dependency_types = {'tool': (Candidate, CheckOutcome)}

    def __init__(self, tool: Tool[Candidate, CheckOutcome]) -> None:
        if getattr(tool, 'check_kind', None) != 'interface':
            raise ValueError('interface node requires an interface check tool')
        self.tool = tool

    def run(self, ctx, input: CheckInput) -> CheckResult:
        return ctx.check(self.tool, input.candidate, candidate=input.candidate, timeout_s=None)


@dataclass(frozen=True)
class LintNode(Node[CheckInput, CheckResult]):
    component_name = 'vivado_lint'
    input_type = CheckInput
    output_type = CheckResult
    dependencies = {'tool': 'tool'}
    dependency_types = {'tool': (Candidate, CheckOutcome)}
    tool: Tool[Candidate, CheckOutcome]
    timeout_s: float = 300.0
    minimum_s: float = 0.0

    def __post_init__(self):
        if getattr(self.tool, 'check_kind', None) != 'lint':
            raise ValueError('lint node requires a lint check tool')

    def run(self, ctx, input: CheckInput) -> CheckResult:
        timeout = ctx.budget.timeout_s(self.timeout_s, self.minimum_s)
        return ctx.check(self.tool, input.candidate, candidate=input.candidate,
                         timeout_s=timeout, minimum_s=self.minimum_s)


@dataclass(frozen=True)
class SynthNode(Node[CheckInput, CheckResult]):
    component_name = 'vivado_synth'
    input_type = CheckInput
    output_type = CheckResult
    dependencies = {'tool': 'tool'}
    dependency_types = {'tool': (Candidate, CheckOutcome)}
    tool: Tool[Candidate, CheckOutcome]
    timeout_s: float = 900.0
    minimum_s: float = 0.0

    def __post_init__(self):
        if getattr(self.tool, 'check_kind', None) != 'synth':
            raise ValueError('synthesis node requires a synthesis check tool')

    def run(self, ctx, input: CheckInput) -> CheckResult:
        timeout = ctx.budget.timeout_s(self.timeout_s, self.minimum_s)
        return ctx.check(self.tool, input.candidate, candidate=input.candidate,
                         timeout_s=timeout, minimum_s=self.minimum_s)
