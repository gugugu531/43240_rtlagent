"""Checks produce evidence; workflows choose what to do with it."""
from dataclasses import dataclass
from ..candidate import Candidate
from ..core.components import Component
from ..core.registry import NODE_REGISTRY
from ..core.state import CheckResult


@dataclass(frozen=True)
class CheckInput:
    candidate: Candidate


@NODE_REGISTRY.register('interface_check')
class InterfaceNode(Component):
    def run(self, ctx, input: CheckInput) -> CheckResult:
        return ctx.tools.check_interface(ctx.task, input.candidate)


@NODE_REGISTRY.register('vivado_lint')
@dataclass(frozen=True)
class LintNode(Component):
    timeout_s: float = 300.0
    minimum_s: float = 0.0

    def run(self, ctx, input: CheckInput) -> CheckResult:
        return ctx.tools.lint(input.candidate, ctx.task.top, timeout_s=ctx.budget.timeout_s(self.timeout_s, self.minimum_s))


@NODE_REGISTRY.register('vivado_synth')
@dataclass(frozen=True)
class SynthNode(Component):
    timeout_s: float = 900.0
    minimum_s: float = 0.0

    def run(self, ctx, input: CheckInput) -> CheckResult:
        return ctx.tools.synth(input.candidate, ctx.task.top, timeout_s=ctx.budget.timeout_s(self.timeout_s, self.minimum_s))
