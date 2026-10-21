"""Independent design/check construction with bounded, attributed repairs."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

from agent.core.budget import BudgetExhausted
from agent.core.components import Node, Workflow
from agent.core.extraction import ExtractInput, ExtractionOutput
from agent.core.model import ModelCallError, ModelReply, _thaw
from agent.core.research import FunctionalInput, JsonInput, JsonOutput, SuiteBuild, SuiteInput
from agent.core.state import CheckResult
from agent.core.specification import normalize_requirements, resolve_requirement, source_catalog
from agent.nodes.check import CheckInput
from agent.nodes.generate import GenerateInput
from agent.services.functional import coverage_summary


def _hash(suite):
    return hashlib.sha256(json.dumps(_thaw(suite), sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False).encode()).hexdigest()


def _stimuli(suite):
    """A renamed test is not an independent acceptance scenario."""
    clocks = _thaw(suite.get('clocks', {}))
    if suite.get('clock'):
        clocks = {suite['clock']['port']: {'edge': suite['clock']['edge']}}
    def edges(step):
        return sorted(step.get('edges', clocks if step.get('edge', True) else []))
    return {json.dumps({'clocks': clocks,
            'steps': [{'inputs': {name: number & ((1 << suite['ports'][name]['width']) - 1)
                                  for name, number in step['inputs'].items()}, 'edges': edges(step),
                       'sample': step.get('sample', True)} for step in case['steps']]},
            sort_keys=True, separators=(',', ':')) for case in suite['cases']}


def _quoted(data, task):
    try:
        resolve_requirement(data, task.prompt + '\n' + task.interface)
        return True
    except (TypeError, ValueError):
        return False


def _repair_feedback(check):
    """Use structured roots before the display summary loses later signals."""
    diagnostics = _thaw(check.details.get('repair_diagnostics', {}))
    return json.dumps({'kind': check.kind, 'check_id': check.id,
        'candidate_id': check.candidate_id, 'status': check.status,
        'diagnostics': diagnostics, 'summary': check.summary[:8000] if not diagnostics.get('items') else '',
        'log_paths': list(check.log_paths),
        'instruction': 'Apply the required changes to the complete RTL. Check declaration types and every procedural writer together; do not only describe a fix.'}, ensure_ascii=False)


def _normalized_plan(data, task):
    if not isinstance(data, Mapping) or not isinstance(data.get('plan'), (tuple, list)) or not data['plan']:
        raise ValueError('plan needs nonempty implementation steps')
    return {'requirements': normalize_requirements(data.get('requirements'), task.prompt + '\n' + task.interface),
            'plan': _thaw(data['plan']), 'uncertain': _thaw(data.get('uncertain', []))}


class DesignVerifyLoop(Workflow):
    component_name = 'design_verify_loop'
    assembly_roles = ['workflow']
    assembly_defaults = {'params': {'max_rounds': 3, 'checker_revisions': 1,
        'plan_retries': 1, 'unchanged_retries': 1, 'plan_max_tokens': 4096, 'review_max_tokens': 4096},
        'dependencies': {'generate': {'component': 'rtl_generate', 'id': 'generate'},
        'extract': {'component': 'rtl_extract', 'id': 'extract'},
        'interface': {'component': 'interface_check', 'id': 'interface'},
        'lint': {'component': 'vivado_lint', 'id': 'lint'},
        'synth': {'component': 'vivado_synth', 'id': 'synth'},
        'json': {'component': 'research_json', 'id': 'json'},
        'suite_builder': {'component': 'build_functional_suite', 'id': 'suite_builder'},
        'functional': {'component': 'functional_check', 'id': 'functional'}}}
    dependencies = {'generate': 'node', 'extract': 'node', 'interface': 'node',
        'lint': 'node', 'synth': 'node', 'json': 'node', 'suite_builder': 'node', 'functional': 'node'}
    dependency_types = {'generate': (GenerateInput, ModelReply),
        'extract': (ExtractInput, ExtractionOutput), 'interface': (CheckInput, CheckResult),
        'lint': (CheckInput, CheckResult), 'synth': (CheckInput, CheckResult),
        'json': (JsonInput, JsonOutput), 'suite_builder': (SuiteInput, SuiteBuild),
        'functional': (FunctionalInput, CheckResult)}

    def __init__(self, generate: Node[GenerateInput, ModelReply],
                 extract: Node[ExtractInput, ExtractionOutput],
                 interface: Node[CheckInput, CheckResult], lint: Node[CheckInput, CheckResult],
                 synth: Node[CheckInput, CheckResult], json: Node[JsonInput, JsonOutput],
                 suite_builder: Node[SuiteInput, SuiteBuild],
                 functional: Node[FunctionalInput, CheckResult], *,
                 max_rounds: int = 3, checker_revisions: int = 1,
                 plan_retries: int = 1, unchanged_retries: int = 1,
                 plan_max_tokens: int = 4096, review_max_tokens: int = 4096):
        if type(max_rounds) is not int or not 1 <= max_rounds <= 20:
            raise ValueError('max_rounds must be in 1..20')
        if type(checker_revisions) is not int or not 0 <= checker_revisions <= 5:
            raise ValueError('checker_revisions must be in 0..5')
        for name, value in (('plan_retries', plan_retries), ('unchanged_retries', unchanged_retries)):
            if type(value) is not int or not 0 <= value <= 2:
                raise ValueError(name + ' must be in 0..2')
        for value in (plan_max_tokens, review_max_tokens):
            if type(value) is not int or not 256 <= value <= 16384:
                raise ValueError('plan/review token cap must be in 256..16384')
        self.generate, self.extract, self.interface = generate, extract, interface
        self.lint, self.synth, self.json = lint, synth, json
        self.suite_builder, self.functional = suite_builder, functional
        self.max_rounds, self.checker_revisions = max_rounds, checker_revisions
        self.plan_retries, self.unchanged_retries = plan_retries, unchanged_retries
        self.plan_max_tokens, self.review_max_tokens = plan_max_tokens, review_max_tokens

    def _request(self, ctx, instruction, purpose, context, max_tokens=None):
        return ctx.execute(self.json, JsonInput(ctx.task, instruction, purpose, context, max_tokens=max_tokens))

    def _plan(self, ctx, previous=None, feedback=''):
        catalog = source_catalog(ctx.task.prompt + '\n' + ctx.task.interface)
        for attempt in range(self.plan_retries + 1):
            result = self._request(ctx,
                'Prepare a compact design plan. Return requirements:[{id,source_id,quote,meaning}], '
                'plan:[steps], uncertain:[items]. A public source_id may replace quote; if both are supplied '
                'the quote must come from that source. Preserve exact source text; whitespace may be normalized. '
                'Explain clock/reset, priority, widths, old/new state, hold, latency and required implementation structure. '
                'Use small numeric or edge-by-edge checks for arithmetic/scaling and latency. '
                'Do not turn unspecified behavior into a requirement. Do not write RTL. Prefer at most 8 concise steps. '
                'Use feedback only where justified by the original task.', 'design_plan',
                {'previous': previous, 'feedback': feedback, 'sources': catalog}, self.plan_max_tokens)
            try:
                if result.status != 'ready':
                    raise ValueError(result.reason)
                plan = _normalized_plan(result.data, ctx.task)
                previous = plan
                audit = self._request(ctx,
                    'Review this plan against the original task. Return decision:"accept"|"revise"|"reject", '
                    'reason:string. For accept, do not return a changed plan. For revise, return the full corrected '
                    'requirements, plan and uncertain fields with source references. For reject explain what remains unresolved. '
                    'An identified contradiction requires revise or reject, never accept. Check small numeric examples, '
                    'old/new state, cycle latency, and explicit structural requirements. Do not invent initialization, '
                    'priority or latency, or resolve assumptions merely by calling them reasonable.',
                    'design_plan_review', {'plan': plan, 'sources': catalog}, self.review_max_tokens)
                if audit.status != 'ready':
                    raise ValueError(audit.reason)
                data = audit.data
                decision = data.get('decision')
                if decision is not None and 'accepted' in data and (
                        type(data['accepted']) is not bool or data['accepted'] != (decision == 'accept')):
                    raise ValueError('review decision conflicts with accepted; return one consistent verdict')
                if decision is None and type(data.get('accepted')) is bool:
                    decision = 'accept' if data['accepted'] else 'revise'
                if decision == 'accept':
                    if 'plan' in data and _thaw(data['plan']) != plan['plan']:
                        raise ValueError('review accepts but changes the implementation plan; use decision=revise')
                    if 'requirements' in data and normalize_requirements(data['requirements'],
                            ctx.task.prompt + '\n' + ctx.task.interface) != plan['requirements']:
                        raise ValueError('review accepts but changes requirements; use decision=revise')
                    if 'uncertain' in data and _thaw(data['uncertain']) != plan['uncertain']:
                        raise ValueError('review accepts but changes uncertain items; use decision=revise')
                    chosen = plan
                elif decision == 'revise':
                    chosen = _normalized_plan(data, ctx.task)
                else:
                    raise ValueError('review rejected or unresolved: ' + str(data.get('reason', 'missing decision'))[:1000])
                ctx.emit('design_plan_attempt', attempt=attempt + 1, status='ready', decision=decision,
                    call_id=result.call_id, review_call_id=audit.call_id)
                return chosen
            except (ValueError, TypeError) as error:
                feedback = str(error)
                ctx.emit('design_plan_attempt', attempt=attempt + 1, status='invalid',
                         call_id=result.call_id, reason=feedback, retry=attempt < self.plan_retries)
        return None

    def run(self, ctx):
        candidates, structural, evidence, suites = {}, {}, {}, {}
        seen, revisions, acceptance_attempted = set(), 0, False
        unchanged_attempts, acceptance_outcome = 0, None
        target, feedback = None, ''
        try:
            plan = self._plan(ctx)
            # Invalid auxiliary replies do not prevent an initial RTL fallback.
            ctx.emit('design_plan_status', status='ready' if plan else 'invalid', plan=plan)
            build = ctx.execute(self.suite_builder, SuiteInput(ctx.task))
            if build.status == 'ready':
                suites[_hash(build.suite)] = build.suite
            else:
                ctx.emit('functional_support', status=build.status, reason=build.reason)
            for round in range(1, self.max_rounds + 1):
                generation_feedback = 'Design plan (fallible; original task is authoritative):\n' + json.dumps(plan, ensure_ascii=False) + '\n' + feedback
                reply = ctx.execute(self.generate, GenerateInput(ctx.task, generation_feedback, target, round))
                extracted = ctx.execute(self.extract, ExtractInput(reply, round,
                    target.id if target else None, 'repair' if target else 'generate'))
                candidate = extracted.candidate
                if candidate is None:
                    feedback = '[extraction] ' + '; '.join(extracted.extraction.diagnostics)
                    continue
                target = candidate
                candidates[candidate.id] = candidate
                if ctx.state.selected_candidate_id is None:
                    ctx.select_candidate(candidate.id, reason='complete_fallback')
                if candidate.code_hash in seen:
                    if unchanged_attempts < self.unchanged_retries and round < self.max_rounds:
                        unchanged_attempts += 1
                        ctx.emit('unchanged_repair', candidate_id=candidate.id, parent_id=candidate.parent_id,
                            attempt=unchanged_attempts, remaining_rounds=self.max_rounds - round,
                            code_hash=candidate.code_hash, action='feedback_without_rechecking')
                        feedback = ('[modification_not_applied] This complete RTL repeats an earlier candidate exactly. '
                            'Apply a real localized correction to the returned code, not just an explanation. '
                            'If removing a duplicate declaration, also preserve the required variable type for procedural assignments.\n'
                            + feedback)
                        continue
                    return ctx.finish(reason='repeated_candidate', status='stopped')
                seen.add(candidate.code_hash)
                failed = None
                structural[candidate.id] = 0
                for kind, node in (('interface', self.interface), ('lint', self.lint)):
                    check = ctx.execute(node, CheckInput(candidate))
                    if kind == 'interface' and not check.blocking and check.status in ('passed', 'failed', 'skipped'):
                        continue
                    if check.status != 'passed' or check.blocking:
                        failed = check
                        break
                if failed:
                    if failed.classify() != 'code':
                        return ctx.finish(reason='structure_' + failed.classify(), status='stopped')
                    feedback = _repair_feedback(failed)
                    ctx.emit('repair_feedback', check_id=failed.id, candidate_id=candidate.id,
                             diagnostics=_thaw(failed.details.get('repair_diagnostics', {})),
                             feedback_hash=hashlib.sha256(feedback.encode()).hexdigest())
                    continue
                structural[candidate.id] = 1
                selected = ctx.state.selected_candidate_id
                if structural.get(selected, 0) < 1:
                    ctx.select_candidate(candidate.id, reason='compiled_fallback')
                if not suites:
                    synthesis = ctx.execute(self.synth, CheckInput(candidate))
                    if synthesis.status == 'passed':
                        ctx.select_candidate(candidate.id, reason='structure_only_checker_' + build.status)
                        return ctx.finish(reason='functional_' + build.status, status='stopped')
                    if synthesis.classify() == 'code':
                        feedback = _repair_feedback(synthesis)
                        continue
                    return ctx.finish(reason='synth_' + synthesis.classify(), status='stopped')

                # Checker revision and independent acceptance may restart checking,
                # but never grant an unbounded model or simulation loop.
                for _ in range(self.checker_revisions + 3):
                    for cid, old in candidates.items():
                        if not structural.get(cid):
                            continue
                        for key, suite in suites.items():
                            if (cid, key) not in evidence:
                                evidence[cid, key] = ctx.execute(self.functional, FunctionalInput(old, suite))
                    checks = [evidence[candidate.id, key] for key in suites]
                    unresolved = next((c for c in checks if c.status not in ('passed', 'failed')), None)
                    checker_unknown = unresolved and unresolved.status == 'skipped' and (
                        unresolved.details.get('attribution') == 'checker_uninformative' or
                        any(unresolved.details.get(name, 0) for name in ('unknown_expected', 'guard_unknown', 'mask_unknown')))
                    if unresolved and not checker_unknown:
                        return ctx.finish(reason='functional_' + unresolved.status, status='stopped')
                    self._select(ctx, candidates, structural, evidence, suites)
                    failing = unresolved if checker_unknown else next((c for c in checks if c.status == 'failed'), None)
                    if failing:
                        key = str(failing.details.get('suite_hash', ''))
                        suite = suites.get(key)
                        if suite is None:
                            return ctx.finish(reason='missing_suite_identity', status='stopped')
                        traces = _thaw(failing.details.get('traces', ()))
                        first = _thaw(failing.details.get('first_mismatch'))
                        window = self._window(traces, first)
                        diagnosis = self._request(ctx,
                            'Analyze the earliest mismatch. Neither RTL nor generated checker is trusted. '
                            'Return {attribution:"rtl"|"plan"|"checker"|"uncertain",quote:<exact task excerpt>, '
                            'reason:<specific causal explanation>,repair_feedback:<localized change>, '
                            'revision:{target:"outputs"|"state_next"|"async_reset_values",names:[existing model signals]}}. '
                            'Revision identifies only which expression to re-derive from the quoted requirement; '
                            'never send actual values, RTL snippets or proposed replacement behavior to the suite builder. '
                            'Do not weaken tests to pass. '
                            'For skipped checks with unknown expected values, choose checker only with a public requirement '
                            'proving the omitted transition; otherwise choose uncertain. Unknown expectations alone never justify an RTL repair. '
                            'Use uncertain when task evidence cannot identify the wrong side.', 'functional_diagnosis',
                            {'plan': plan, 'rtl': candidate.code, 'suite': suite, 'first_mismatch': first, 'trace_window': window,
                             'check_status': failing.status,
                             'expectation_analysis': _thaw(failing.details.get('expectation_analysis', {}))})
                        if diagnosis.status != 'ready' or not _quoted(diagnosis.data, ctx.task) or not diagnosis.data.get('reason'):
                            return ctx.finish(reason='diagnosis_unresolved', status='stopped')
                        cause = diagnosis.data.get('attribution')
                        if checker_unknown and cause != 'checker':
                            return ctx.finish(reason='checker_unknown_unresolved', status='stopped')
                        ctx.emit('functional_diagnosis', candidate_id=candidate.id,
                                 check_id=failing.id, suite_hash=key, diagnosis=_thaw(diagnosis.data))
                        if cause == 'checker' and revisions < self.checker_revisions:
                            proposed_revision = diagnosis.data.get('revision')
                            if not isinstance(proposed_revision, Mapping):
                                return ctx.finish(reason='checker_correction_missing', status='stopped')
                            revision_target = proposed_revision.get('target')
                            revision_names = proposed_revision.get('names')
                            signals = suite.get('outputs', {}) if revision_target == 'outputs' else suite.get('state', {})
                            if (revision_target not in ('outputs', 'state_next', 'async_reset_values') or
                                    not isinstance(revision_names, (tuple, list)) or not revision_names or
                                    any(not isinstance(name, str) or name not in signals for name in revision_names)):
                                return ctx.finish(reason='checker_correction_invalid', status='stopped')
                            correction = json.dumps({'kind': 'specification_revision',
                                'origin': 'code_aware_diagnosis', 'quote': resolve_requirement(diagnosis.data,
                                    ctx.task.prompt + '\n' + ctx.task.interface)['quote'],
                                'target': revision_target, 'names': list(revision_names)}, ensure_ascii=False)
                            revised = ctx.execute(self.suite_builder, SuiteInput(ctx.task,
                                feedback=correction, previous=suite))
                            revisions += 1
                            if revised.status != 'ready' or _hash(revised.suite) == key:
                                return ctx.finish(reason='checker_revision_invalid', status='stopped')
                            newkey = _hash(revised.suite)
                            suites.pop(key)
                            suites[newkey] = revised.suite
                            acceptance_attempted = False
                            acceptance_outcome = None
                            ctx.emit('suite_retired', suite_hash=key, replacement=newkey,
                                     diagnosis_call_id=diagnosis.call_id, reason=diagnosis.data['reason'])
                            # Every compiled candidate is re-evaluated under the
                            # new version, so selection cannot compare unlike suites.
                            continue
                        if cause == 'plan':
                            revised_plan = self._plan(ctx, plan, str(diagnosis.data.get('repair_feedback', '')))
                            if revised_plan is None:
                                return ctx.finish(reason='plan_revision_invalid', status='stopped')
                            plan = revised_plan
                        if cause not in ('rtl', 'plan'):
                            return ctx.finish(reason='diagnosis_' + str(cause), status='stopped')
                        feedback = json.dumps({'diagnosis': _thaw(diagnosis.data), 'first_mismatch': first,
                                               'trace_window': window}, ensure_ascii=False)
                        break
                    if not acceptance_attempted:
                        acceptance_attempted = True
                        coverage = coverage_summary(suites.values())
                        ctx.emit('functional_coverage', **coverage)
                        if coverage['stateless_exhaustive']:
                            acceptance_outcome = 'exhaustive_combinational_domain'
                            ctx.emit('acceptance_exhaustive', reason='every_binary_input_has_all_output_bits_compared',
                                     **coverage)
                        else:
                            acceptance = ctx.execute(self.suite_builder, SuiteInput(ctx.task,
                                feedback='Independent final acceptance: prepare new directed scenarios for omitted requirements and boundaries. '
                                         'Do not read implementation, plans, past failures, or existing suite.'))
                            if acceptance.status != 'ready':
                                acceptance_outcome = 'acceptance_' + acceptance.status
                            else:
                                key = _hash(acceptance.suite)
                                known_stimuli = set().union(*(_stimuli(s) for s in suites.values()))
                                fresh = _stimuli(acceptance.suite) - known_stimuli
                                if key in suites or not fresh:
                                    acceptance_outcome = 'acceptance_repeated_suite'
                                else:
                                    suites[key] = acceptance.suite
                                    ctx.emit('acceptance_promoted', suite_hash=key, new_stimulus_sequences=len(fresh),
                                        coverage=coverage_summary(suites.values()),
                                        reason='will_become_known_regression_if_used_for_repair')
                                    continue
                            ctx.emit('acceptance_incomplete', reason=acceptance_outcome,
                                     action='synthesize_existing_checked_candidate')
                    # Equal functional coverage must still permit a synthesis
                    # repair. Keep the saved old answer until this actual new
                    # draft also passes synthesis, then commit the promotion.
                    final_candidate = candidate
                    synthesis = ctx.execute(self.synth, CheckInput(final_candidate))
                    if synthesis.status == 'passed':
                        ctx.select_candidate(final_candidate.id, reason='all_active_self_checks_and_synth_passed')
                        if acceptance_outcome and acceptance_outcome != 'exhaustive_combinational_domain':
                            return ctx.finish(reason=acceptance_outcome, status='stopped')
                        return ctx.finish(reason='self_checks_exhaustive_and_synth_passed'
                            if acceptance_outcome else 'self_checks_and_synth_passed')
                    if synthesis.classify() == 'code':
                        target = final_candidate
                        feedback = _repair_feedback(synthesis)
                        break
                    return ctx.finish(reason='synth_' + synthesis.classify(), status='stopped')
                else:
                    return ctx.finish(reason='verification_action_limit', status='stopped')
            return ctx.finish(reason='round_limit', status='stopped')
        except BudgetExhausted:
            return ctx.finish(reason='deadline', status='stopped')
        except ModelCallError as error:
            return ctx.finish(reason='model_' + error.kind, status='stopped')

    @staticmethod
    def _window(traces, mismatch):
        if not mismatch:
            return traces[:5]
        return [t for t in traces if t['case_id'] == mismatch['case_id'] and
                mismatch['step'] - 3 <= t['step'] <= mismatch['step'] + 2]

    @staticmethod
    def _select(ctx, candidates, structural, evidence, suites):
        selected = ctx.state.selected_candidate_id
        def passed(cid):
            return {(key, case) for key in suites for case in
                    evidence[cid, key].details.get('passed_cases', ())}
        for cid in candidates:
            if not structural.get(cid) or cid == selected:
                continue
            checks = [evidence[cid, key] for key in suites]
            if any(c.status not in ('passed', 'failed') for c in checks):
                continue
            old = passed(selected) if structural.get(selected) else set()
            new = passed(cid)
            if old < new:
                ctx.select_candidate(cid, reason='same_active_suites_preserved_cases_and_improved')
                selected = cid
