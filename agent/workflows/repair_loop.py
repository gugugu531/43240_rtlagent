"""Optional repair workflow; it owns its candidate selection and failure decisions."""
from dataclasses import dataclass
import math
from agent.core.budget import BudgetExhausted
from agent.core.components import Component
from agent.core.model import ModelCallError
from agent.core.registry import WORKFLOW_REGISTRY, build_node
from agent.core.state import RunStateView, SelectionDecision, WorkflowResult
from agent.nodes.generate import GenerateInput
from agent.nodes.extract import ExtractInput
from agent.workflows.checks import candidate_checks
from agent.services.repair_feedback import (tool_repair_feedback, output_driver_warnings,
    output_driver_feedback, driver_repair_improves)


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


@dataclass(frozen=True)
class LoopStart:
    target: object
    feedback: str
    calls: int
    start_round: int = 2
    optional_pieces: tuple = ()


def classify_model_error(error: ModelCallError) -> str:
    retryable = error.retryable and error.kind in ('transport', 'connection', 'timeout', 'http')
    return 'model_retryable' if retryable else 'model_terminal'


@WORKFLOW_REGISTRY.register('repair_loop')
class RepairLoop(Component):
    """Subclasses replace choose() or decide() to try other strategies."""

    def __init__(self, max_rounds: int = 3, max_tokens: int = 4096,
                 temperature: float = 0.2, timeout_s: float = 180.0,
                 use_skills: bool = True, max_request_retries: int = 1,
                 max_model_calls: int | None = None, minimum_action_s: float = 0.05,
                 repair_output_drivers: bool = True):
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
        if type(repair_output_drivers) is not bool:
            raise ValueError('repair_output_drivers must be boolean')
        self.repair_output_drivers = repair_output_drivers
        self._output_top = None
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
        current = next((entry for entry in eligible if entry[0] == current_id), None)
        if current and self.repair_output_drivers and self._output_top:
            old_checks = [c for c in state.checks if c.candidate_id == current_id]
            if output_driver_warnings(state.candidates[current_id].code, self._output_top, old_checks):
                improved = [entry for entry in eligible if entry[1] >= current[1] and
                    entry[1][0] and entry[1][1] and driver_repair_improves(
                        state.candidates[current_id].code, state.candidates[entry[0]].code,
                        self._output_top, old_checks,
                        [c for c in state.checks if c.candidate_id == entry[0]])]
                if improved:
                    chosen = max(improved, key=lambda entry: entry[1])
                    return SelectionDecision(chosen[0], True, 'output_driver_improved', chosen[2])
                return SelectionDecision(current_id, False, 'output_driver_fallback', current[2])
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
        """Hook for experiments; default uses bounded own-tool root diagnostics."""
        candidate = ctx.state.candidates.get(checks[-1].candidate_id) if checks else None
        return tool_repair_feedback(candidate.code if candidate else '', checks)

    def restore(self, ctx):
        return None

    def after_round(self, ctx, reply, result, checks, choice, round):
        pass

    def repair_pieces(self, ctx, checks):
        return ()

    def _failure_decision(self, ctx, kind, source_id, attempts):
        choice = self.decide(kind, source_id, attempts, ctx.budget)
        ctx.emit('failure_decision', action=choice.action, reason=choice.reason,
                 diagnostic_ids=(choice.source_id,), model_calls=attempts.model_calls,
                 request_retries=attempts.request_retries, repairs=attempts.repairs)
        return choice

    def _request_reply(self, ctx, input, calls, repairs):
        retries = 0
        while True:
            # Hard limit, also when a subclass decide() keeps asking for more calls.
            if calls >= self.max_model_calls:
                return ctx.finish(reason='model_call_limit', status='stopped'), calls
            try:
                calls += 1
                return ctx.execute(self.generate, input), calls
            except BudgetExhausted:
                return ctx.finish(reason='deadline', status='stopped'), calls
            except ModelCallError as exc:
                choice = self._failure_decision(ctx, classify_model_error(exc), exc.call_id or '',
                                                AttemptState(calls, retries, repairs))
                if choice.action != 'retry_request':
                    reason = 'deadline' if choice.reason == 'deadline' else f'model_{exc.kind}'
                    return ctx.finish(reason=reason, status='stopped'), calls
                retries += 1

    def _check_candidate(self, ctx, candidate, checks):
        # The caller owns checks so completed evidence survives budget exhaustion.
        for check in candidate_checks(ctx, candidate, interface=self.interface,
                                      lint=self.lint, synth=self.synth):
            checks.append(check)
            ctx.apply_selection(self.choose(ctx.state))
        warnings = []
        # All three checks have completed only when synthesis was reached.
        synthesis_passed = len(checks) == 3 and checks[-1].status == 'passed'
        if synthesis_passed:
            warnings = (output_driver_warnings(candidate.code, ctx.task.top, [checks[-1]])
                        if self.repair_output_drivers else [])
            if warnings:
                ctx.emit('synthesis_output_warning', candidate_id=candidate.id,
                         warnings=warnings, synthesis_completed=True,
                         functional_verified=False, retain_candidate=True)
        return warnings, synthesis_passed

    def _synthesis_outcome(self, ctx):
        state = ctx.state
        selected = state.candidates.get(state.selected_candidate_id)
        unresolved = (self.repair_output_drivers and selected and
            output_driver_warnings(selected.code, ctx.task.top,
                [c for c in state.checks if c.candidate_id == selected.id]))
        return ('warning_repair_unverified', 'stopped') if unresolved else ('synth_passed', 'completed')

    def run(self, ctx):
        self._output_top = ctx.task.top
        repair_target = None
        feedback, reason = '', 'round_limit'
        calls, repairs = 0, 0
        start_round, optional_pieces = 1, ()
        restored = self.restore(ctx)
        if isinstance(restored, WorkflowResult):
            return restored
        if restored is not None:
            repair_target, feedback, calls, start_round, optional_pieces = (
                restored.target, restored.feedback, restored.calls, restored.start_round, restored.optional_pieces)
            repairs = start_round - 1

        for round in range(start_round, self.max_rounds + 1):
            if not ctx.budget.can_start(self.minimum_action_s):
                reason = 'deadline'
                break
            input = GenerateInput(ctx.task, feedback, repair_target, round, optional_pieces)
            reply, calls = self._request_reply(ctx, input, calls, repairs)
            if isinstance(reply, WorkflowResult):
                return reply
            result = ctx.execute(self.extract, ExtractInput(reply, round,
                repair_target.id if repair_target else None, 'repair' if repair_target else 'generate'))
            checks = []
            warnings = []
            if result.candidate is None:
                choice = self._failure_decision(ctx, 'extraction', reply.call_id,
                                                AttemptState(calls, 0, repairs))
                if choice.action == 'repair':
                    feedback = self.build_extraction_feedback(ctx, reply, result.extraction)
            else:
                latest = result.candidate
                # A complete fallback can survive a blocked verification service.
                ctx.apply_selection(self.choose(ctx.state))
                ctx.emit('repair_target', candidate_id=latest.id)
                repair_target = latest
                try:
                    warnings, synthesis_passed = self._check_candidate(ctx, latest, checks)
                    if synthesis_passed and not warnings:
                        stop, status = self._synthesis_outcome(ctx)
                        self.after_round(ctx, reply, result, checks,
                            FailureDecision('stop', stop, checks[-1].id), round)
                        return ctx.finish(reason=stop, status=status)
                except BudgetExhausted:
                    self.after_round(ctx, reply, result, checks,
                        FailureDecision('stop', 'deadline', checks[-1].id if checks else reply.call_id), round)
                    return ctx.finish(reason='deadline', status='stopped')
                last = checks[-1]
                choice = self._failure_decision(ctx, 'code' if warnings else last.classify(), last.id,
                                                AttemptState(calls, 0, repairs))
                if choice.action == 'repair':
                    feedback = self.build_check_feedback(ctx, checks)
                    if warnings:
                        feedback += output_driver_feedback(warnings)
                    optional_pieces = self.repair_pieces(ctx, checks)
            self.after_round(ctx, reply, result, checks, choice, round)
            if choice.action != 'repair':
                reason = ('synth_output_warning' if warnings and choice.reason != 'deadline' else
                          'verification_unavailable' if choice.reason == 'environment' else choice.reason)
                break
            repairs += 1
        return ctx.finish(reason=reason, status='stopped')
