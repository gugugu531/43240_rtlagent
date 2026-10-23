"""Search independent RTL plans using task-grounded, anonymous behavior differences."""
from __future__ import annotations

import hashlib
import json

from agent.core.budget import BudgetExhausted
from agent.core.components import Node, Workflow
from agent.core.extraction import ExtractInput, ExtractionOutput
from agent.core.model import ModelCallError, ModelReply, _thaw
from agent.core.research import FunctionalInput, SuiteBuild, SuiteInput
from agent.core.state import CheckResult
from agent.nodes.check import CheckInput
from agent.nodes.differential import DifferentialDecision, DifferentialInput
from agent.nodes.generate import GenerateInput


_PLAN_HINTS = (
    'Start from observable output changes and derive their exact conditions and latency.',
    'Start from old state, next state, reset and transition priority; check simultaneous controls.',
    'Start from boundaries, widths, signedness and hold conditions; independently derive the implementation.',
    'Start from the task examples and truth or transition tables; preserve unspecified behavior as uncertainty.',
)


def suite_identity(suite):
    return hashlib.sha256(json.dumps(_thaw(suite), ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def stimulus_identity(suite):
    """Renaming a case or requirement is not a newly exercised input sequence."""
    value = _thaw(suite)
    cases = sorted({json.dumps([{'inputs': step['inputs'], 'edge': step.get('edge', True),
                                'sample': step.get('sample', True)} for step in case['steps']],
                               sort_keys=True, separators=(',', ':')) for case in value['cases']})
    return suite_identity({'ports': value['ports'], 'clock': value.get('clock'), 'cases': cases})


class BehaviorSearch(Workflow):
    component_name = 'behavior_search'
    assembly_roles = ['workflow']
    assembly_defaults = {'params': {'pool_size': 3, 'max_search_rounds': 2, 'seed': 17},
        'dependencies': {'generate': {'component': 'rtl_generate', 'id': 'generate'},
                         'extract': {'component': 'rtl_extract', 'id': 'extract'},
                         'interface': {'component': 'interface_check', 'id': 'interface'},
                         'lint': {'component': 'vivado_lint', 'id': 'lint'},
                         'synth': {'component': 'vivado_synth', 'id': 'synth'},
                         'suite_builder': {'component': 'build_functional_suite', 'id': 'suite_builder'},
                         'functional': {'component': 'functional_check', 'id': 'functional'},
                         'differential': {'component': 'behavior_difference', 'id': 'differential'}}}
    dependencies = {'generate': 'node', 'extract': 'node', 'interface': 'node',
                    'lint': 'node', 'synth': 'node', 'suite_builder': 'node',
                    'functional': 'node', 'differential': 'node'}
    dependency_types = {'generate': (GenerateInput, ModelReply),
                        'extract': (ExtractInput, ExtractionOutput),
                        'interface': (CheckInput, CheckResult),
                        'lint': (CheckInput, CheckResult), 'synth': (CheckInput, CheckResult),
                        'suite_builder': (SuiteInput, SuiteBuild),
                        'functional': (FunctionalInput, CheckResult),
                        'differential': (DifferentialInput, DifferentialDecision)}

    def __init__(self, generate: Node[GenerateInput, ModelReply],
                 extract: Node[ExtractInput, ExtractionOutput],
                 interface: Node[CheckInput, CheckResult], lint: Node[CheckInput, CheckResult],
                 synth: Node[CheckInput, CheckResult], suite_builder: Node[SuiteInput, SuiteBuild],
                 functional: Node[FunctionalInput, CheckResult],
                 differential: Node[DifferentialInput, DifferentialDecision], *,
                 pool_size: int = 3, max_search_rounds: int = 2, seed: int = 17):
        if type(pool_size) is not int or not 2 <= pool_size <= 16:
            raise ValueError('pool_size must be an integer from 2 to 16')
        if type(max_search_rounds) is not int or not 0 <= max_search_rounds <= 32:
            raise ValueError('max_search_rounds must be an integer from 0 to 32')
        if type(seed) is not int:
            raise ValueError('seed must be an integer')
        self.generate, self.extract, self.interface = generate, extract, interface
        self.lint, self.synth = lint, synth
        self.suite_builder, self.functional, self.differential = suite_builder, functional, differential
        self.pool_size, self.max_search_rounds, self.seed = pool_size, max_search_rounds, seed

    def run(self, ctx):
        pool, rank, structural_errors = {}, {}, {}
        suites, observations, rejected, hashes, stimulus_hashes = [], {}, set(), set(), set()
        generation_index = 0

        def selected():
            return pool.get(ctx.state.selected_candidate_id)

        def generate_one(*, parent=None, feedback='', independent=False):
            nonlocal generation_index
            generation_index += 1
            hint = _PLAN_HINTS[(generation_index - 1) % len(_PLAN_HINTS)]
            instruction = ('Independently derive a complete RTL implementation from the original task. '
                           'No other candidate is provided. Do not invent defaults for unspecified behavior. '
                           + hint) if independent else feedback
            ctx.emit('behavior_generation_plan', generation=generation_index,
                     independent=independent, plan_hint=hint if independent else None,
                     parent_id=parent.id if parent else None)
            reply = ctx.execute(self.generate, GenerateInput(ctx.task, instruction,
                None if independent else parent, generation_index, seed=self.seed + generation_index))
            extracted = ctx.execute(self.extract, ExtractInput(reply, generation_index,
                None if independent or parent is None else parent.id,
                'independent_plan' if independent else 'behavior_repair'))
            if extracted.candidate is None:
                ctx.emit('behavior_generation', status='extraction_failed', call_id=reply.call_id,
                         diagnostics=extracted.extraction.diagnostics)
                return None, 'extraction'
            candidate = extracted.candidate
            pool[candidate.id], rank[candidate.id] = candidate, 0
            if selected() is None:
                ctx.select_candidate(candidate.id, reason='complete_fallback')
            if candidate.code_hash in hashes:
                ctx.emit('behavior_generation', candidate_id=candidate.id, status='duplicate')
                return candidate, 'duplicate'
            hashes.add(candidate.code_hash)
            for stage, node in (('interface', self.interface), ('lint', self.lint)):
                result = ctx.execute(node, CheckInput(candidate))
                advisory = (stage == 'interface' and not result.blocking and
                            result.status in ('passed', 'failed', 'skipped'))
                if not advisory and (result.blocking or result.status != 'passed'):
                    cause = result.classify()
                    if cause == 'code':
                        structural_errors[candidate.id] = f'[{result.kind}] {result.summary[:12000]}'
                    ctx.emit('behavior_structural', candidate_id=candidate.id, status='failed',
                             stage=stage, failure_kind=cause, evidence_ids=(result.id,))
                    return candidate, cause
                rank[candidate.id] += 1
                if selected() is None or rank[candidate.id] > rank[selected().id]:
                    ctx.select_candidate(candidate.id, reason=f'behavior_{stage}_progress')
            return candidate, 'ready'

        def build_suite(feedback='', previous=None):
            # This boundary never receives candidate code, plans, or output values.
            result = ctx.execute(self.suite_builder, SuiteInput(ctx.task, 'stimulus', feedback, previous))
            if result.status != 'ready':
                ctx.emit('behavior_suite', status=result.status, reason=result.reason, call_id=result.call_id)
                return result.status
            identity = suite_identity(result.suite)
            stimulus_hash = stimulus_identity(result.suite)
            if any(key == identity for key, _suite in suites) or stimulus_hash in stimulus_hashes:
                return 'duplicate_suite'
            suites.append((identity, result.suite))
            stimulus_hashes.add(stimulus_hash)
            ctx.emit('behavior_suite', status='ready', suite_index=len(suites), identity=identity,
                     call_id=result.call_id, source_scope='task_only')
            return 'ready'

        def simulate_pool():
            usable, seen = [], set()
            for candidate in pool.values():
                if rank[candidate.id] == 2 and candidate.code_hash not in seen:
                    usable.append(candidate)
                    seen.add(candidate.code_hash)
            for identity, suite in suites:
                for candidate in usable:
                    key = (identity, candidate.id)
                    if key in observations:
                        continue
                    result = ctx.execute(self.functional, FunctionalInput(candidate, suite, False))
                    observations[key] = result
                    if result.status in ('timeout', 'unavailable', 'error'):
                        return usable, 'functional_' + result.classify()
                    if result.status != 'passed':
                        # A failed stimulus driver is not a functional RTL verdict.
                        return usable, 'functional_unusable'
            return usable, 'ready'

        def final(reason, *, status='completed'):
            answer = selected()
            if answer is None or rank[answer.id] < 2:
                return ctx.finish(reason=reason, status='stopped')
            result = ctx.execute(self.synth, CheckInput(answer))
            if result.status != 'passed' or result.blocking:
                return ctx.finish(reason='final_synth_' + result.classify(), status='stopped')
            ctx.emit('behavior_search_complete', candidate_id=answer.id, search_stop=reason,
                     rejected_candidate_ids=tuple(sorted(rejected)), suite_count=len(suites),
                     correctness_scope='task-grounded model review and finite stimulus, not proof')
            if answer.id in rejected:
                return ctx.finish(reason='unresolved_requirement_failures', status='stopped')
            return ctx.finish(reason=reason, status=status)

        try:
            for _ in range(self.pool_size):
                _candidate, status = generate_one(independent=True)
                if status in ('environment', 'timeout', 'unknown'):
                    return ctx.finish(reason='structural_' + status, status='stopped')
            initial_suite = build_suite()
            if initial_suite != 'ready':
                return final('stimulus_' + initial_suite, status='stopped')
            stop_reason = 'search_round_limit'
            for search_round in range(self.max_search_rounds + 1):
                usable, status = simulate_pool()
                if status != 'ready':
                    return ctx.finish(reason=status, status='stopped')
                decision = None
                if len(usable) >= 2:
                    decisions = []
                    # Revisit every retained suite: new drafts cannot hide an old failure
                    # behind a larger number of easy events in a fresh suite.
                    for identity, _suite in suites:
                        decision = ctx.execute(self.differential, DifferentialInput(ctx.task,
                            tuple(observations[(identity, c.id)] for c in usable), self.seed, search_round))
                        decisions.append(decision)
                        if decision.status == 'ready':
                            rejected.update(decision.rejected_candidate_ids)
                            preferred = pool.get(decision.selected_candidate_id)
                            if preferred is not None and preferred.id not in rejected and rank[preferred.id] == 2:
                                ctx.select_candidate(preferred.id, reason='reviewed_task_behavior')
                            else:
                                ctx.emit('behavior_selection_declined', candidate_id=decision.selected_candidate_id,
                                         reason='conflicts_with_retained_requirement_evidence')
                        elif decision.status == 'invalid':
                            ctx.emit('behavior_decision_unusable', reason=decision.reason,
                                     suite_hash=decision.suite_hash)
                    if selected() and selected().id in rejected:
                        eligible = next((c for c in usable if c.id not in rejected), None)
                        if eligible is not None:
                            ctx.select_candidate(eligible.id, reason='avoid_reviewed_requirement_failure')
                    # An uninformative newer suite cannot erase a concrete,
                    # grounded repair discovered by a retained older suite.
                    decision = next((d for d in reversed(decisions)
                                     if d.status == 'ready' and d.action == 'repair'),
                                    next((d for d in reversed(decisions) if d.status == 'ready'),
                                         decisions[-1]))
                if search_round >= self.max_search_rounds:
                    break
                if len(usable) < 2:
                    target = next((pool[cid] for cid in structural_errors), None)
                    if target is not None:
                        _new, action_status = generate_one(parent=target, feedback=structural_errors[target.id])
                        structural_errors.pop(target.id, None)
                    else:
                        _new, action_status = generate_one(independent=True)
                elif decision is not None and decision.status == 'ready' and decision.action == 'stop':
                    stop_reason = 'reviewed_stop'
                    break
                elif decision is not None and decision.status == 'ready' and decision.action == 'repair':
                    target = next((pool[cid] for cid in decision.rejected_candidate_ids if cid in pool), None)
                    if target is None:
                        stop_reason = 'repair_without_grounded_target'
                        break
                    findings = [f for f in decision.findings if target.id in f['rejected_candidate_ids']]
                    feedback = ('The following model-reviewed findings cite the original task; re-check them '
                                'before editing. They are not a trusted reference. Correct only supported defects '
                                'and preserve all other behavior.\n' + json.dumps(findings, ensure_ascii=False))
                    _new, action_status = generate_one(parent=target, feedback=feedback)
                elif decision is not None and decision.action == 'regenerate':
                    _new, action_status = generate_one(independent=True)
                else:
                    quotes = [] if decision is None else list(dict.fromkeys(
                        (*decision.focus_quotes, *(f['quote'] for f in decision.findings))))
                    feedback = ('Add distinct legal input sequences that exercise previously untested task '
                                'requirements, reset between clock edges when asynchronous reset is specified, '
                                'boundary conditions and simultaneous controls. Preserve old cases or add new '
                                'case IDs. Original-task focus quotes: ' + json.dumps(quotes, ensure_ascii=False))
                    action_status = build_suite(feedback, suites[-1][1])
                ctx.emit('behavior_search_action', round=search_round + 1, status=action_status,
                         action=decision.action if decision else 'structural_repair_or_regenerate')
                if action_status in ('environment', 'timeout', 'unknown'):
                    return ctx.finish(reason='structural_' + action_status, status='stopped')
                if action_status not in ('ready', 'code', 'extraction'):
                    stop_reason = 'no_new_evidence_' + action_status
                    break
            return final(stop_reason)
        except BudgetExhausted:
            return ctx.finish(reason='deadline', status='stopped')
        except ModelCallError as error:
            return ctx.finish(reason='model_' + error.kind, status='stopped')
