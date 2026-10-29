"""Public checking tools shared by guided verification."""

from agent.kit import Ctx, tool
from agent.domain.rtl.interface import check_interface
from agent.domain.rtl.result import bind_result
from agent.domain.rtl.vivado import lint as run_lint, synth as run_synth


@tool("interface_check")
def interface(ctx: Ctx, candidate_id: str):
    candidate = ctx.candidates.get(candidate_id)
    return bind_result(check_interface(ctx, candidate), candidate, "interface")


@tool("vivado_lint")
def lint(ctx: Ctx, candidate_id: str, *, timeout_s: float = 300):
    candidate = ctx.candidates.get(candidate_id)
    return bind_result(run_lint(ctx, candidate, timeout_s=timeout_s), candidate, "lint")


@tool("vivado_synth")
def synth(ctx: Ctx, candidate_id: str, *, timeout_s: float = 300):
    candidate = ctx.candidates.get(candidate_id)
    return bind_result(run_synth(ctx, candidate, timeout_s=timeout_s), candidate, "synth")
