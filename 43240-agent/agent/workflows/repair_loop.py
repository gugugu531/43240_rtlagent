"""Optional repair workflow with independent evidence and failure policies."""
from agent.core.budget import BudgetExhausted
from agent.core.components import Component, describe_value
from agent.core.model import ModelCallError
from agent.core.registry import WORKFLOW_REGISTRY, build_node
from agent.nodes.generate import GenerateInput
from agent.nodes.extract import ExtractInput
from agent.nodes.check import CheckInput
from agent.policies.selection import SelectionPolicy
from agent.policies.failure import FailurePolicy, AttemptState
from agent.policies.diagnostics import Diagnostic, classify_check, classify_model_error


@WORKFLOW_REGISTRY.register('repair_loop')
class RepairLoop(Component):
    def __init__(self, max_rounds: int = 3, max_tokens: int = 4096,
                 temperature: float = 0.2, timeout_s: float = 180.0,
                 use_skills: bool = True, max_request_retries: int = 1,
                 max_model_calls: int | None = None, selection_policy=None, failure_policy=None):
        if isinstance(max_rounds, bool) or not isinstance(max_rounds, int) or max_rounds <= 0:
            raise ValueError('max_rounds must be a positive integer')
        self.max_rounds, self.max_tokens = max_rounds, max_tokens
        self.temperature, self.timeout_s, self.use_skills = temperature, timeout_s, use_skills
        self.max_request_retries = max_request_retries
        self.max_model_calls = max_model_calls if max_model_calls is not None else max_rounds + max_request_retries
        self.selection_policy = selection_policy or SelectionPolicy()
        self.failure_policy = failure_policy or FailurePolicy(max_request_retries, self.max_model_calls, max_rounds - 1)
        self.generate = build_node('rtl_generate', max_tokens=max_tokens, temperature=temperature,
                                   timeout_s=timeout_s, prompt_style='repair', use_skills=use_skills)
        self.extract = build_node('rtl_extract')
        self.interface = build_node('interface_check')
        self.lint = build_node('vivado_lint', timeout_s=300.0)
        self.synth = build_node('vivado_synth', timeout_s=900.0)

    def run(self, ctx):
        ctx.emit('policies', selection=describe_value(self.selection_policy),
                 failure=describe_value(self.failure_policy))
        repair_target = None
        feedback, reason = '', 'round_limit'
        calls, repairs = 0, 0

        def select():
            state = ctx.state
            ctx.apply_selection(self.selection_policy.choose(state.candidates, state.checks,
                                                             state.selected_candidate_id))

        def decide(diagnostics, retries=0):
            choice = self.failure_policy.decide(diagnostics, AttemptState(calls, retries, repairs), ctx.budget)
            ctx.emit('failure_decision', action=choice.action, reason=choice.reason,
                     diagnostic_ids=choice.diagnostic_ids,
                     model_calls=calls, request_retries=retries, repairs=repairs)
            return choice

        for round in range(1, self.max_rounds + 1):
            if not ctx.budget.can_start(self.failure_policy.minimum_action_s):
                reason = 'deadline'
                break
            retries = 0
            input = GenerateInput(ctx.task, feedback, repair_target, round)
            while True:
                if calls >= self.max_model_calls:
                    return ctx.finish(reason='model_call_limit', status='stopped')
                try:
                    calls += 1
                    reply = ctx.execute(self.generate, input)
                    break
                except BudgetExhausted:
                    return ctx.finish(reason='deadline', status='stopped')
                except ModelCallError as exc:
                    choice = decide((classify_model_error(exc),), retries)
                    if choice.action != 'retry_request':
                        return ctx.finish(reason='deadline' if choice.reason == 'deadline' else f'model_{exc.kind}',
                                          status='stopped')
                    retries += 1
            result = ctx.execute(self.extract, ExtractInput(reply, round,
                repair_target.id if repair_target else None, 'repair' if repair_target else 'generate'))
            if result.candidate is None:
                feedback = ('上一轮回复没有包含完整的 Verilog 模块。解析结果：' +
                            '; '.join(result.extraction.diagnostics) + '。请输出完整 module/endmodule。')
                choice = decide((Diagnostic('extraction', feedback, 'confirmed', reply.call_id),))
            else:
                latest = result.candidate
                # A complete fallback can survive a blocked verification service.
                select()
                ctx.emit('repair_target', candidate_id=latest.id)
                repair_target = latest
                checks = []
                try:
                    interface = ctx.execute(self.interface, CheckInput(latest))
                    checks.append(interface)
                    select()
                    if not interface.blocking:
                        lint = ctx.execute(self.lint, CheckInput(latest))
                        checks.append(lint)
                        select()
                        if lint.status == 'passed':
                            synth = ctx.execute(self.synth, CheckInput(latest))
                            checks.append(synth)
                            select()
                            if synth.status == 'passed':
                                return ctx.finish(reason='synth_passed')
                except BudgetExhausted:
                    return ctx.finish(reason='deadline', status='stopped')
                last = checks[-1]
                feedback = '\n\n'.join(c.summary for c in checks if c.status != 'passed')
                choice = decide(classify_check(last))
            if choice.action != 'repair':
                reason = ('verification_unavailable' if choice.reason == 'environment' else choice.reason)
                break
            repairs += 1
        return ctx.finish(reason=reason, status='stopped')
