"""RTL compilation capabilities backed by the run's shared toolchain."""
from agent.core.candidate import Candidate
from agent.core.components import Tool
from agent.core.tool import CheckOutcome, ToolResult


def toolchain_identity(ctx, name):
    value = getattr(ctx.toolchain(), name, None)
    return value() if callable(value) else value


def outcome(result: ToolResult) -> CheckOutcome:
    return CheckOutcome('passed' if result.status == 'ok' else result.status,
        result.summary, blocking=result.status == 'failed' and result.failure_kind == 'code',
        rc=result.rc, elapsed_s=result.elapsed_s, command=result.command,
        details={**result.details, 'failure_kind': result.failure_kind,
                 'diagnostic_tool': result.diagnostic_tool, 'tool_version': result.tool_version},
        log_paths=result.log_paths, work_dir=result.work_dir)


class VivadoLintTool(Tool[Candidate, CheckOutcome]):
    component_name = 'vivado_lint_tool'
    check_kind = 'lint'
    input_type = Candidate
    output_type = CheckOutcome

    def cache_identity(self, ctx) -> str | None:
        return toolchain_identity(ctx, 'fingerprint')

    def replay_identity(self, ctx) -> str | None:
        return toolchain_identity(ctx, 'replay_fingerprint')

    def cache_request(self, input: Candidate):
        return {'code_hash': input.code_hash}

    def run(self, ctx, input: Candidate) -> CheckOutcome:
        return outcome(ctx.toolchain().lint(input.code, ctx.task.top, timeout_s=ctx.timeout_s))


class VivadoSynthTool(Tool[Candidate, CheckOutcome]):
    component_name = 'vivado_synth_tool'
    check_kind = 'synth'
    input_type = Candidate
    output_type = CheckOutcome

    def cache_identity(self, ctx) -> str | None:
        return toolchain_identity(ctx, 'fingerprint')

    def replay_identity(self, ctx) -> str | None:
        return toolchain_identity(ctx, 'replay_fingerprint')

    def cache_request(self, input: Candidate):
        return {'code_hash': input.code_hash}

    def run(self, ctx, input: Candidate) -> CheckOutcome:
        return outcome(ctx.toolchain().synth(input.code, ctx.task.top, timeout_s=ctx.timeout_s))
