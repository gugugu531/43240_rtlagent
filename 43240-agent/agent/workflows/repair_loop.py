"""Optional repair workflow; it owns its candidate selection and failure decisions."""
from dataclasses import dataclass
import math
from agent.core.budget import BudgetExhausted
from agent.core.components import Component
from agent.core.model import ModelCallError
from agent.core.registry import WORKFLOW_REGISTRY, build_node
from agent.core.state import RunStateView, SelectionDecision
from agent.nodes.generate import GenerateInput
from agent.nodes.extract import ExtractInput
from agent.nodes.check import CheckInput


@dataclass(frozen=True)
class AttemptState:
    model_calls: int = 0
    request_retries: int = 0
    repairs: int = 0


@dataclass(frozen=True)
class FailureDecision:
    action: str
    reason: str
    source_id: str


def classify_model_error(error: ModelCallError) -> str:
    retryable = error.retryable and error.kind in ('transport', 'connection', 'timeout', 'http')
    return 'model_retryable' if retryable else 'model_terminal'


@WORKFLOW_REGISTRY.register('repair_loop')
class RepairLoop(Component):
    """Subclasses replace choose() or decide() to try other strategies."""

    def __init__(self, max_rounds: int = 3, max_tokens: int = 4096,
                 temperature: float = 0.2, timeout_s: float = 180.0,
                 use_skills: bool = True, max_request_retries: int = 1,
                 max_model_calls: int | None = None, minimum_action_s: float = 0.05):
        if isinstance(max_rounds, bool) or not isinstance(max_rounds, int) or max_rounds <= 0:
            raise ValueError('max_rounds must be a positive integer')
        if max_model_calls is None:
            max_model_calls = max_rounds + max_request_retries
        for value in (max_request_retries, max_model_calls):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError('attempt limits must be nonnegative integers')
        if max_model_calls < 1:
            raise ValueError('max_model_calls must be positive')
        if not math.isfinite(minimum_action_s) or minimum_action_s < 0:
            raise ValueError('minimum_action_s must be nonnegative')
        self.max_rounds, self.max_tokens = max_rounds, max_tokens
        self.temperature, self.timeout_s, self.use_skills = temperature, timeout_s, use_skills
        self.max_request_retries, self.max_model_calls = max_request_retries, max_model_calls
        self.minimum_action_s = minimum_action_s
        self.generate = build_node('rtl_generate', max_tokens=max_tokens, temperature=temperature,
                                   timeout_s=timeout_s, prompt_style='repair', use_skills=use_skills)
        self.extract = build_node('rtl_extract')
        self.interface = build_node('interface_check')
        self.lint = build_node('vivado_lint', timeout_s=300.0)
        self.synth = build_node('vivado_synth', timeout_s=900.0)

    def choose(self, state: RunStateView) -> SelectionDecision:
        """Compare real evidence without turning unknown checks into passes."""
        eligible = []
        for candidate in state.candidates.values():
            evidence = [c for c in state.checks if c.candidate_id == candidate.id]
            if candidate.extraction_status not in ('ok', 'complete', 'ambiguous'):
                continue
            if any(c.classify() == 'code' for c in evidence):
                continue
            passes = {c.kind for c in evidence if c.status == 'passed'}
            # Lexicographic strength; ties retain the current choice, then creation order.
            rank = ('synth' in passes, 'lint' in passes, 'interface' in passes)
            eligible.append((candidate.id, rank, tuple(c.id for c in evidence if c.status == 'passed')))
        current_id = state.selected_candidate_id
        if not eligible:
            return SelectionDecision(None, current_id is not None, 'no_eligible_candidate', ())
        strongest = max(rank for _, rank, _ in eligible)
        choices = [entry for entry in eligible if entry[1] == strongest]
        chosen = next((entry for entry in choices if entry[0] == current_id), choices[0])
        reason = 'synth_passed' if strongest[0] else 'lint_passed' if strongest[1] else 'complete_fallback'
        return SelectionDecision(chosen[0], chosen[0] != current_id, reason, chosen[2])

    def decide(self, kind: str, source_id: str, attempts: AttemptState, budget) -> FailureDecision:
        """Bounded retry/repair decision for one diagnosed failure."""
        if not budget.can_start(self.minimum_action_s):
            return FailureDecision('stop', 'deadline', source_id)
        if attempts.model_calls >= self.max_model_calls:
            return FailureDecision('stop', 'model_call_limit', source_id)
        if kind == 'model_retryable' and attempts.request_retries < self.max_request_retries:
            return FailureDecision('retry_request', 'retryable_model_error', source_id)
        if kind in ('code', 'extraction') and attempts.repairs < self.max_rounds - 1:
            return FailureDecision('repair', 'code_feedback', source_id)
        return FailureDecision('stop', kind, source_id)

    def build_extraction_feedback(self, ctx, reply, extraction) -> str:
        """Hook for experimental workflows; keep legacy repair_loop text unchanged."""
        return ('上一轮回复没有包含完整的 Verilog 模块。解析结果：' +
                '; '.join(extraction.diagnostics) + '。请输出完整 module/endmodule。')

    def build_check_feedback(self, ctx, checks) -> str:
        """Hook for experimental workflows; default to the existing bounded summaries."""
        return '\n\n'.join(check.summary for check in checks if check.status != 'passed')

    def run(self, ctx):
        repair_target = None
        feedback, reason = '', 'round_limit'
        calls, repairs = 0, 0

        def select():
            ctx.apply_selection(self.choose(ctx.state))

        def decide(kind, source_id, retries=0):
            choice = self.decide(kind, source_id, AttemptState(calls, retries, repairs), ctx.budget)
            ctx.emit('failure_decision', action=choice.action, reason=choice.reason,
                     diagnostic_ids=(choice.source_id,),
                     model_calls=calls, request_retries=retries, repairs=repairs)
            return choice

        for round in range(1, self.max_rounds + 1):
            if not ctx.budget.can_start(self.minimum_action_s):
                reason = 'deadline'
                break
            retries = 0
            input = GenerateInput(ctx.task, feedback, repair_target, round)
            while True:
                # Hard limit, also when a subclass decide() keeps asking for more calls.
                if calls >= self.max_model_calls:
                    return ctx.finish(reason='model_call_limit', status='stopped')
                try:
                    calls += 1
                    reply = ctx.execute(self.generate, input)
                    break
                except BudgetExhausted:
                    return ctx.finish(reason='deadline', status='stopped')
                except ModelCallError as exc:
                    choice = decide(classify_model_error(exc), exc.call_id or '', retries)
                    if choice.action != 'retry_request':
                        return ctx.finish(reason='deadline' if choice.reason == 'deadline' else f'model_{exc.kind}',
                                          status='stopped')
                    retries += 1
            result = ctx.execute(self.extract, ExtractInput(reply, round,
                repair_target.id if repair_target else None, 'repair' if repair_target else 'generate'))
            if result.candidate is None:
                choice = decide('extraction', reply.call_id)
                if choice.action == 'repair':
                    feedback = self.build_extraction_feedback(ctx, reply, result.extraction)
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
                choice = decide(last.classify(), last.id)
                if choice.action == 'repair':
                    feedback = self.build_check_feedback(ctx, checks)
            if choice.action != 'repair':
                reason = ('verification_unavailable' if choice.reason == 'environment' else choice.reason)
                break
            repairs += 1
        return ctx.finish(reason=reason, status='stopped')
