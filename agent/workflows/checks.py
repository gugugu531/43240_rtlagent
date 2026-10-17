"""Shared check order; workflows retain selection and stopping decisions."""
from __future__ import annotations
from collections.abc import Iterator
from typing import TYPE_CHECKING

from agent.core.candidate import Candidate
from agent.core.components import Node
from agent.core.state import CheckResult
from agent.nodes.check import CheckInput

if TYPE_CHECKING:
    from agent.core.context import RunContext


def candidate_checks(ctx: RunContext, candidate: Candidate, *,
                     interface: Node[CheckInput, CheckResult],
                     lint: Node[CheckInput, CheckResult],
                     synth: Node[CheckInput, CheckResult]) -> Iterator[CheckResult]:
    """Yield each completed check before starting the next managed action."""
    check = ctx.execute(interface, CheckInput(candidate))
    yield check
    if check.blocking:
        return
    check = ctx.execute(lint, CheckInput(candidate))
    yield check
    if check.status == 'passed':
        yield ctx.execute(synth, CheckInput(candidate))
