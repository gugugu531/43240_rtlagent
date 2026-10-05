"""Optional multi-round workflow; preserve the previous policy for comparison."""
from ..core.budget import BudgetExhausted
from ..core.components import Component
from ..core.model import ModelCallError
from ..core.registry import WORKFLOW_REGISTRY, build_node
from ..nodes.generate import GenerateInput
from ..nodes.extract import ExtractInput
from ..nodes.check import CheckInput


@WORKFLOW_REGISTRY.register('repair_loop')
class RepairLoop(Component):
    def __init__(self, max_rounds: int = 3, max_tokens: int = 4096,
                 temperature: float = 0.2, timeout_s: float = 180.0,
                 use_skills: bool = True):
        if isinstance(max_rounds, bool) or not isinstance(max_rounds, int) or max_rounds <= 0:
            raise ValueError('max_rounds must be a positive integer')
        self.max_rounds, self.max_tokens = max_rounds, max_tokens
        self.temperature, self.timeout_s, self.use_skills = temperature, timeout_s, use_skills
        self.generate = build_node('rtl_generate', max_tokens=max_tokens, temperature=temperature,
                                   timeout_s=timeout_s, prompt_style='repair', use_skills=use_skills)
        self.extract = build_node('rtl_extract')
        self.interface = build_node('interface_check')
        self.lint = build_node('vivado_lint', timeout_s=300.0)
        self.synth = build_node('vivado_synth', timeout_s=900.0)

    def run(self, ctx):
        best = None
        feedback = ''
        reason = 'round_limit'
        for round in range(1, self.max_rounds + 1):
            if not ctx.budget.can_start():
                reason = 'deadline'
                break
            try:
                reply = ctx.execute(self.generate, GenerateInput(ctx.task, feedback, best, round))
            except BudgetExhausted:
                reason = 'deadline'
                break
            except ModelCallError as exc:
                reason = f'model_{exc.kind}'
                break
            result = ctx.execute(self.extract, ExtractInput(
                reply, round, best.id if best else None, 'repair' if best else 'generate'))
            if result.candidate is None:
                detail = '; '.join(result.extraction.diagnostics)
                feedback = ('上一轮回复没有包含完整的 Verilog 模块。'
                            f'解析结果：{detail}。'
                            '只输出一个包含完整 module/endmodule 的 ```verilog 代码块。')
                continue
            best = result.candidate
            ctx.select_candidate(best.id, reason='latest_extracted')
            interface = ctx.execute(self.interface, CheckInput(best))
            if interface.blocking:
                feedback = interface.summary
                continue
            note = interface.summary if interface.details.get('status') == 'advisory' else ''
            try:
                lint = ctx.execute(self.lint, CheckInput(best))
                if lint.status in ('failed', 'timeout', 'error'):
                    feedback = f'{note}\n\n{lint.summary}' if note else lint.summary
                    continue
                if lint.status == 'unavailable':
                    return ctx.finish(reason='verification_unavailable', status='stopped')
                synth = ctx.execute(self.synth, CheckInput(best))
            except BudgetExhausted:
                reason = 'deadline'
                break
            if synth.status == 'passed':
                ctx.select_candidate(best.id, reason='synth_passed')
                return ctx.finish(reason='synth_passed')
            if synth.status == 'unavailable':
                return ctx.finish(reason='verification_unavailable', status='stopped')
            feedback = f'{note}\n\n{synth.summary}' if note else synth.summary
        return ctx.finish(reason=reason, status='stopped')
