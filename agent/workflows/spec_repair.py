"""Opt-in experiments; shared services are not a shared selection policy."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
import json
import math

from agent.core.budget import BudgetExhausted
from agent.core.components import Component
from agent.core.model import ModelCallError
from agent.core.registry import WORKFLOW_REGISTRY, build_node
from agent.core.replay import load_initial, save_initial
from agent.core.state import SelectionDecision
from agent.core.tokens import TokenCount, TokenLedger
from agent.nodes.behavior import BehaviorInput, PlanResult
from agent.nodes.check import CheckInput
from agent.nodes.extract import ExtractInput
from agent.nodes.generate import GenerateInput
from agent.services.behavior import literal_truth_table_plan
from agent.services.port_signature import port_signature
from agent.services.repair_feedback import (driver_repair_improves, output_driver_feedback,
                                           output_driver_warnings, tool_repair_feedback)
from agent.workflows.spec_selection import choose_spec_candidate


class ModelCallLimit(RuntimeError):
    pass


class ExperimentalRepair(Component):
    """One repair slot; no retry, voting, judge feedback or speculative selection."""

    use_behavior = False
    candidates = 1

    def __init__(self, initial_state=None, max_tokens=8192, timeout_s=300.0,
                 alternative_temperature=0.4):
        if (isinstance(alternative_temperature, bool)
                or not isinstance(alternative_temperature, (int, float))
                or not math.isfinite(alternative_temperature) or alternative_temperature < 0):
            raise ValueError('alternative_temperature must be finite and nonnegative')
        self.initial_state = initial_state
        self.max_tokens, self.timeout_s = max_tokens, timeout_s
        self.alternative_temperature = alternative_temperature
        self.max_calls = self.candidates + 1 + int(self.use_behavior)
        # Match scheme A only at the initial boundary, not its control flow.
        self.generate = build_node('rtl_generate', max_tokens=max_tokens, temperature=0.0,
            top_p=1.0, timeout_s=timeout_s, prompt_style='repair', use_skills=False)
        self.alternative = build_node('rtl_generate', max_tokens=max_tokens,
            temperature=alternative_temperature, top_p=1.0, timeout_s=timeout_s,
            prompt_style='repair', use_skills=False)
        self.extract = build_node('rtl_extract')
        self.interface = build_node('interface_check')
        self.lint = build_node('vivado_lint', timeout_s=45.0)
        self.synth = build_node('vivado_synth', timeout_s=60.0)
        self.plan_node = build_node('spec_test_plan')
        self.behavior = build_node('spec_behavior_check', timeout_s=45.0)

    def _calls(self, ctx):
        # Includes imported initial costs; deterministic plans never add a call.
        return ctx.llm.tokens.snapshot()['calls']

    def _require_call(self, ctx):
        ctx.budget.timeout_s(self.timeout_s)
        if self._calls(ctx) >= self.max_calls:
            raise ModelCallLimit('model_call_limit')

    def _checks(self, ctx, candidate):
        return [c for c in ctx.state.checks if c.candidate_id == candidate.id]

    def _latest(self, ctx, candidate, kind):
        return next((c for c in reversed(self._checks(ctx, candidate)) if c.kind == kind), None)

    def _passed(self, ctx, candidate, kind):
        check = self._latest(ctx, candidate, kind)
        return check is not None and check.status == 'passed'

    def _generate(self, ctx, *, parent=None, feedback='', alternative=False):
        self._require_call(ctx)
        self._round += 1
        reply = ctx.execute(self.alternative if alternative else self.generate,
            GenerateInput(ctx.task, feedback, parent, self._round))
        result = ctx.execute(self.extract, ExtractInput(reply, self._round,
            parent.id if parent else None, 'repair' if feedback else 'alternative' if alternative else 'generate'))
        # Only the first available fallback may be persisted before verification.
        if result.candidate and ctx.state.selected_candidate_id is None:
            ctx.select_candidate(result.candidate.id, reason='initial_complete_fallback')
        return reply, result

    def _compile(self, ctx, candidate):
        interface = self._latest(ctx, candidate, 'interface')
        if interface is None:
            interface = ctx.execute(self.interface, CheckInput(candidate))
        if not interface.blocking and self._latest(ctx, candidate, 'lint') is None:
            ctx.execute(self.lint, CheckInput(candidate))

    def _validate_initial(self, ctx, data, checks):
        requests = data['requests']
        if len(requests) != 1:
            raise ValueError('experimental workflows require exactly one initial request')
        request = requests[0]['request']
        # Reconstruct the first-call allowance with an empty ledger; imported
        # costs remain charged in ctx.llm.tokens. Budgets may clamp the cap.
        prediction = data['tokens']['entries'][requests[0]['call_id']]['prediction']
        initial_cap = TokenLedger(ctx.llm.tokens.policy).allowance(
            TokenCount(**prediction), self.max_tokens)
        if (request['temperature'] != 0 or request['top_p'] != 1
                or request['max_tokens'] != initial_cap or request.get('seed') is not None
                or request['profile'] != 'default'):
            raise ValueError('experimental initial sampling differs')
        if any(c.kind not in ('interface', 'lint', 'synth') for c in checks):
            raise ValueError('initial checkpoint must precede behavioral experiments')

    def _restore_initial(self, ctx, path):
        data, reply, result, checks = load_initial(path, ctx, self.extract)
        self._validate_initial(ctx, data, checks)
        self._round = 1
        if result.candidate:
            ctx.select_candidate(result.candidate.id, reason='initial_replay_fallback')
            self._compile(ctx, result.candidate)
        ctx.emit('experimental_initial', source='validated_checkpoint',
                 calls=self._calls(ctx), official_baseline_equivalent=False)
        return result

    def _initial(self, ctx):
        configured = getattr(ctx, 'configuration', {}).get('effective', {}).get('runtime', {}).get('initial_state')
        path = self.initial_state or configured
        if path:
            return self._restore_initial(ctx, path)
        identity = ctx.tools.identify()
        reply, result = self._generate(ctx)
        if result.candidate:
            self._compile(ctx, result.candidate)
        # Save before planning, alternatives, behavioral checks or repairs.
        save_initial(ctx.output_dir / 'initial.json', ctx, reply, result,
            self._checks(ctx, result.candidate) if result.candidate else [],
            'experimental_initial', identity)
        return result

    def _ensure_plan(self, ctx):
        if not self.use_behavior or self._plan_attempted:
            return self._plan_result
        self._plan_attempted = True
        if literal_truth_table_plan(ctx.task) is None:
            self._require_call(ctx)
        self._plan_result = ctx.execute(self.plan_node, ctx.task)
        self._plan = self._plan_result.plan
        if self._plan is None:
            ctx.emit('functional_fallback', reason=self._plan_result.reason,
                     functional_verified=False, retain_candidate=True, skip_synth=True)
        return self._plan_result

    def _observation(self, check):
        return bool(check and self._plan and check.details.get('valid_observation') is True
            and check.details.get('official_verification') is False
            and check.details.get('oracle_protocol') == 2
            and check.details.get('plan_hash') == self._plan.fingerprint)

    def _verify(self, ctx, candidate):
        if candidate is None:
            return
        self._compile(ctx, candidate)
        if not self._passed(ctx, candidate, 'lint'):
            self._ready.add(candidate.id)
            return
        if self.use_behavior:
            self._ensure_plan(ctx)
            if self._plan is None:
                self._ready.add(candidate.id)
                return
            observed = self._latest(ctx, candidate, 'behavior')
            if observed is None:
                observed = ctx.execute(self.behavior, BehaviorInput(candidate, self._plan))
            # A failed/inconclusive self-test is not a license to skip to synthesis.
            if not (self._observation(observed) and observed.status == 'passed'):
                if self._observation(observed) and observed.status == 'failed':
                    self._ready.add(candidate.id)
                return
        if self._latest(ctx, candidate, 'synth') is None:
            ctx.execute(self.synth, CheckInput(candidate))
        if not self._passed(ctx, candidate, 'synth'):
            return
        warnings = output_driver_warnings(candidate.code, ctx.task.top, self._checks(ctx, candidate))
        if warnings:
            ctx.emit('synthesis_output_warning', candidate_id=candidate.id, warnings=warnings,
                     synthesis_completed=True, functional_verified=False, retain_candidate=True)
        # A deadline inside any step leaves the new candidate out of selection.
        self._ready.add(candidate.id)

    def _choose(self, ctx):
        state = ctx.state
        current = state.candidates.get(state.selected_candidate_id)
        if self.use_behavior:
            return self._choose_spec(ctx, state, current)
        self._choose_tools(ctx, state, current)

    def _choose_spec(self, ctx, state, current):
        # The foundation excludes code-failed candidates before ranking.
        # Do not let a synthesis error make an already compilable incumbent
        # disappear and thereby bypass its strict property protection.
        if current and self._passed(ctx, current, 'lint') and any(
                c.classify() == 'code' for c in self._checks(ctx, current)):
            ctx.emit('selection_decision', candidate_id=current.id, changed=False,
                     reason='protected_compilable_code_failure', evidence_ids=())
            return
        view = replace(state, candidates={k:v for k,v in state.candidates.items()
                                         if k in self._ready or k == state.selected_candidate_id})
        decision = choose_spec_candidate(view, plan_hash=self._plan.fingerprint if self._plan else None)
        if decision.candidate_id is None and current:
            decision = SelectionDecision(current.id, False, 'complete_unverified_fallback', ())
        return ctx.apply_selection(decision)

    def _choose_tools(self, ctx, state, current):
        # Tool-only strategy: latest evidence and stable ties; warnings need their
        # own strict proof. Never use a partial repair or discard a complete fallback.
        eligible = []
        for candidate in state.candidates.values():
            if candidate.id not in self._ready:
                continue
            checks = self._checks(ctx, candidate)
            if any(c.classify() == 'code' for c in checks):
                continue
            rank = tuple(self._passed(ctx, candidate, kind) for kind in ('synth', 'lint', 'interface'))
            if current and candidate.id != current.id and self._passed(ctx, current, 'lint'):
                old_ports = port_signature(current.code, ctx.task.top)
                if old_ports is None or port_signature(candidate.code, ctx.task.top) != old_ports:
                    continue
                old_rank = tuple(self._passed(ctx, current, kind) for kind in ('synth', 'lint', 'interface'))
                if any(old and not new for old, new in zip(old_rank, rank)):
                    continue
                if output_driver_warnings(current.code, ctx.task.top, self._checks(ctx, current)):
                    if not driver_repair_improves(current.code, candidate.code, ctx.task.top,
                                                 self._checks(ctx, current), checks):
                        continue
            eligible.append((candidate, rank, tuple(c.id for c in checks)))
        if not eligible:
            return
        strongest = max(row[1] for row in eligible)
        ties = [r for r in eligible if r[1] == strongest]
        row = next((r for r in ties if r[0].id == state.selected_candidate_id), ties[0])
        # Equal-rank warning repair is accepted only after the strict check above.
        if current and row[0].id == current.id and output_driver_warnings(
                current.code, ctx.task.top, self._checks(ctx, current)):
            row = next((r for r in ties if r[0].id != current.id), row)
        ctx.apply_selection(SelectionDecision(row[0].id, row[0].id != state.selected_candidate_id,
                                              'experimental_tool_evidence', row[2]))

    def _repair_basis(self, ctx, candidate):
        if candidate is None:
            return 'extraction', 'Previous reply had no complete module. Return a complete module.'
        checks = self._checks(ctx, candidate)
        latest = {c.kind:c for c in checks}
        failures = [c for c in latest.values() if c.classify() == 'code']
        if failures:
            if self.use_behavior and self._passed(ctx, candidate, 'lint'):
                # A pure synthesis defect cannot strictly reduce already-passing
                # properties. Leave this case to the tool-only arm, not a bypass.
                return None, ''
            return 'code', tool_repair_feedback(candidate.code, failures)
        observed = latest.get('behavior')
        if self.use_behavior:
            if self._observation(observed) and observed.status == 'failed':
                rows = observed.details.get('property_checks', ())
                supported = {'public_literal_truth_table', 'explicit_reset_literal', 'observed_registered_hold'}
                failures = [r for r in rows if isinstance(r, Mapping)
                            and r.get('source') in supported and r.get('status') == 'failed']
                mismatch = observed.details.get('first_property_mismatch')
                if failures and mismatch:
                    return 'property', ('First supported public property: '
                        + json.dumps(dict(failures[0]), ensure_ascii=False)
                        + '\nPublic specification-contract property violation and full input prefix:\n'
                        + json.dumps(observed.public_dict()['details']['first_property_mismatch'], ensure_ascii=False)
                        + '\nNot official judge feedback. Preserve the interface, reset and existing correct logic. '
                          'Model-derived expected outputs and candidate agreement are not correctness oracles.')
            return None, ''
        warnings = output_driver_warnings(candidate.code, ctx.task.top, checks)
        if warnings:
            return 'output_driver', output_driver_feedback(warnings)
        return None, ''

    def _record_divergence(self, ctx):
        if self.candidates < 2 or self._plan is None:
            return
        # Compare only the latest observation of each independent initial candidate.
        observations = []
        outputs = {name for name,direction,_ in self._plan.ports if direction == 'output'}
        for candidate in ctx.state.candidates.values():
            if candidate.parent_id is not None:
                continue
            check = self._latest(ctx, candidate, 'behavior')
            if not self._observation(check):
                continue
            samples = check.details.get('samples')
            if (not isinstance(samples, (tuple, list)) or len(samples) != len(self._plan.steps)
                    or any(not isinstance(row, Mapping) or set(row) != outputs or any(
                        not isinstance(v, str) or any(ch not in '0123456789abcdefABCDEF' for ch in v)
                        or not v for v in row.values()) for row in samples)):
                continue
            observations.append(check)
        if len(observations) < 2:
            return
        first, second = observations[:2]
        a, b = first.details['samples'], second.details['samples']
        if any(x.keys() != y.keys() for x,y in zip(a,b)):
            return
        difference = next((i for i,(x,y) in enumerate(zip(a,b))
                           if any(int(x[k],16) != int(y[k],16) for k in x)), None)
        ctx.emit('behavior_divergence', plan_hash=self._plan.fingerprint,
                 candidates=(first.candidate_id, second.candidate_id),
                 first_different_step=difference, agreement_is_correctness=False,
                 repair_trigger=False, official_verification=False)

    def _stop(self, ctx, candidate):
        if candidate is None:
            return ctx.finish(reason='no_complete_candidate', status='stopped')
        if self.use_behavior and self._passed(ctx, candidate, 'lint'):
            if self._plan is None:
                reason = self._plan_result.reason
                return ctx.finish(reason=reason if reason.startswith('model_') else 'functional_plan_unavailable',
                                  status='stopped')
            observed = self._latest(ctx, candidate, 'behavior')
            if not (self._observation(observed) and observed.status == 'passed'):
                reason = ('spec_property_failure' if self._repair_basis(ctx, candidate)[0] == 'property'
                          else 'hypothesis_only_mismatch' if self._observation(observed)
                          and observed.details.get('hypothesis_mismatches', 0) else 'verification_unavailable')
                return ctx.finish(reason=reason, status='stopped')
        if self._passed(ctx, candidate, 'synth'):
            if output_driver_warnings(candidate.code, ctx.task.top, self._checks(ctx, candidate)):
                return ctx.finish(reason='synth_output_warning', status='stopped')
            return ctx.finish(reason='self_test_and_synth_passed' if self.use_behavior else 'synth_only_passed')
        if any(c.classify() == 'code' for c in self._checks(ctx, candidate)):
            return ctx.finish(reason='code_failure', status='stopped')
        return ctx.finish(reason='verification_unavailable', status='stopped')

    def run(self, ctx):
        self._round, self._ready = 0, set()
        self._plan, self._plan_attempted = None, False
        self._plan_result = PlanResult(None, '', 'not_attempted')
        try:
            result = self._initial(ctx)
            self._verify(ctx, result.candidate)
            self._choose(ctx)
            if self.use_behavior and self._plan_attempted and self._plan is None:
                state = ctx.state
                return self._stop(ctx, state.candidates.get(state.selected_candidate_id))
            for _ in range(1, self.candidates):
                _, result = self._generate(ctx, alternative=True)
                self._verify(ctx, result.candidate)
                self._choose(ctx)
            self._record_divergence(ctx)
            state = ctx.state
            target = state.candidates.get(state.selected_candidate_id)
            basis, feedback = self._repair_basis(ctx, target)
            if basis:
                ctx.emit('experimental_repair', parent_id=target.id if target else None,
                         repair_basis=basis, repairs=1, max_repairs=1,
                         model_calls=self._calls(ctx), max_model_calls=self.max_calls)
                _, result = self._generate(ctx, parent=target, feedback=feedback)
                # This also enters plan generation when the initial source did not compile.
                self._verify(ctx, result.candidate)
                self._choose(ctx)
            state = ctx.state
            return self._stop(ctx, state.candidates.get(state.selected_candidate_id))
        except ModelCallLimit:
            return ctx.finish(reason='model_call_limit', status='stopped')
        except BudgetExhausted:
            return ctx.finish(reason='deadline', status='stopped')
        except ModelCallError as exc:
            return ctx.finish(reason='model_' + exc.kind, status='stopped')


@WORKFLOW_REGISTRY.register('tool_feedback')
class ToolFeedback(ExperimentalRepair):
    pass


@WORKFLOW_REGISTRY.register('spec_test_repair')
class SpecTestRepair(ExperimentalRepair):
    use_behavior = True


@WORKFLOW_REGISTRY.register('behavior_divergence')
class BehaviorDivergence(ExperimentalRepair):
    use_behavior = True
    candidates = 2
