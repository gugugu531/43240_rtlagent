"""Review grounded properties, repeat Vivado counterexamples, then repair RTL."""
import json

from agent.core.budget import BudgetExhausted
from agent.core.components import Node, Workflow
from agent.core.extraction import ExtractInput, ExtractionOutput
from agent.core.model import ModelCallError, ModelReply, _thaw
from agent.core.property import PropertyCheckInput, PropertyBuildInput, PropertyBuild
from agent.core.research import JsonInput, JsonOutput
from agent.core.state import CheckResult
from agent.nodes.check import CheckInput
from agent.nodes.generate import GenerateInput


REVIEW = '''Review this task-only property suite independently. Check exact source
support, unsigned widths, sampling BEFORE active edges, reset startup, all input
assumptions, omitted requirements and whether each property is exercised by the explicit stimuli. A finite test does not prove reachability. A reset quote does not justify
arbitrary startup values. Never approve an assumption merely because it makes
the checker pass. Return {"approved_property_ids":[ids],"assumptions_valid":bool,
"startup_valid":bool,"issues":[strings]}. Approve a property only when its
trigger and expected relation follow from the quoted task. If ambiguous, leave
it out. This is model review, not a proof. No RTL candidate is provided.'''

DIAGNOSE = '''Classify the concrete property failure using the task, frozen suite,
RTL and REPLAYED counterexample. Return {"target":"rtl"/"plan"/"property"/
"uncertain","property_ids":[ids],"quote":"exact task substring",
"reason":"specific evidence","repair_instruction":"what to change"}.
Choose rtl/plan only when the property faithfully expresses the task and its
concrete trace shows an implementation or interpretation defect. Choose
property when source evidence shows the property/startup/assumption is wrong.
Do not weaken a property just to match an RTL output. An unknown result or an incomplete Vivado run cannot establish an RTL defect.'''


def strictly_improves(new: CheckResult, old: CheckResult) -> bool:
    """Compare only the exact same properties, assumptions and stimuli version."""
    if new.details.get('suite_hash') != old.details.get('suite_hash'):
        return False
    passed = set(new.details.get('passed_property_ids', ()))
    previous = set(old.details.get('passed_property_ids', ()))
    failures = set(new.details.get('failed_property_ids', ()))
    old_failures = set(old.details.get('failed_property_ids', ()))
    return passed > previous and failures <= old_failures


class PropertyRepairLoop(Workflow):
    component_name = 'property_repair_loop'
    assembly_roles = ['workflow']
    assembly_defaults = {'params': {'max_rounds': 3, 'max_property_revisions': 1},
        'dependencies': {
            'generate': {'component': 'rtl_generate', 'id': 'generate'},
            'extract': {'component': 'rtl_extract', 'id': 'extract'},
            'interface': {'component': 'interface_check', 'id': 'interface'},
            'lint': {'component': 'vivado_lint', 'id': 'lint'},
            'synth': {'component': 'vivado_synth', 'id': 'synth'},
            'build': {'component': 'property_build', 'id': 'property_build'},
            'json': {'component': 'research_json', 'id': 'json'},
            'property_check': {'component': 'property_sim_check', 'id': 'property_check'}}}
    dependencies = {'generate': 'node', 'extract': 'node', 'interface': 'node',
                    'lint': 'node', 'synth': 'node', 'build': 'node',
                    'json': 'node', 'property_check': 'node'}
    dependency_types = {'generate': (GenerateInput, ModelReply),
        'extract': (ExtractInput, ExtractionOutput),
        'interface': (CheckInput, CheckResult), 'lint': (CheckInput, CheckResult),
        'synth': (CheckInput, CheckResult),
        'build': (PropertyBuildInput, PropertyBuild),
        'json': (JsonInput, JsonOutput), 'property_check': (PropertyCheckInput, CheckResult)}

    def __init__(self, generate: Node[GenerateInput, ModelReply],
                 extract: Node[ExtractInput, ExtractionOutput],
                 interface: Node[CheckInput, CheckResult],
                 lint: Node[CheckInput, CheckResult],
                 synth: Node[CheckInput, CheckResult],
                 build: Node[PropertyBuildInput, PropertyBuild],
                 json: Node[JsonInput, JsonOutput],
                 property_check: Node[PropertyCheckInput, CheckResult], *,
                 max_rounds: int = 3, max_property_revisions: int = 1):
        if type(max_rounds) is not int or max_rounds <= 0:
            raise ValueError('max_rounds must be positive')
        if type(max_property_revisions) is not int or max_property_revisions < 0:
            raise ValueError('max_property_revisions must be nonnegative')
        self.generate, self.extract, self.interface = generate, extract, interface
        self.lint, self.synth, self.build = lint, synth, build
        self.json, self.property_check = json, property_check
        self.max_rounds, self.max_property_revisions = max_rounds, max_property_revisions

    def _build(self, ctx, feedback='', previous=None):
        built = ctx.execute(self.build, PropertyBuildInput(ctx.task, feedback, previous))
        if built.status != 'ready':
            ctx.emit('property_suite', status=built.status, reason=built.reason,
                     source_call_id=built.call_id)
            return None
        suite = built.suite
        if previous is not None and suite['version'] <= previous['version']:
            ctx.emit('property_suite', status='invalid', reason='version did not increase')
            return None
        review = ctx.execute(self.json, JsonInput(ctx.task, REVIEW,
            'property_review', {'suite': suite}))
        approved_value = review.data.get('approved_property_ids', ())
        approved = (set(approved_value) if isinstance(approved_value, (list, tuple)) and
                    all(isinstance(x, str) for x in approved_value) else set())
        required = {p['id'] for p in suite['properties']}
        accepted = (review.status == 'ready' and required == approved and
                    review.data.get('assumptions_valid') is True and
                    review.data.get('startup_valid') is True and
                    review.data.get('issues') in ([], ()))
        ctx.emit('property_review', status='accepted' if accepted else 'rejected',
            suite_version=suite['version'], source_call_id=review.call_id,
            review=_thaw(review.data), independently_proven=False)
        return suite if accepted else None

    def run(self, ctx):
        parent, feedback, suite = None, '', None
        checked_candidates = []
        best, best_check = None, None
        revisions = 0
        stop_reason = 'round_limit'
        try:
            # This request sees no candidate or design reasoning.
            suite = self._build(ctx)
            for round in range(1, self.max_rounds + 1):
                reply = ctx.execute(self.generate, GenerateInput(ctx.task, feedback, parent, round))
                extraction = ctx.execute(self.extract, ExtractInput(reply, round,
                    parent.id if parent else None, 'property_repair' if parent else 'generate'))
                candidate = extraction.candidate
                if candidate is None:
                    feedback = '[extraction] ' + '; '.join(extraction.extraction.diagnostics)
                    continue
                parent = candidate
                if ctx.state.selected_candidate_id is None:
                    ctx.select_candidate(candidate.id, reason='complete_fallback')
                if any(c.code_hash == candidate.code_hash for c in checked_candidates):
                    stop_reason = 'duplicate_candidate'
                    break
                failed = None
                for stage, node in (('interface', self.interface), ('lint', self.lint)):
                    check = ctx.execute(node, CheckInput(candidate))
                    if (stage == 'interface' and not check.blocking and
                            check.status in ('passed', 'failed', 'skipped') and
                            check.classify() not in ('environment', 'timeout')):
                        continue
                    if check.status != 'passed' or check.blocking:
                        failed = check
                        break
                if failed is not None:
                    if failed.classify() != 'code':
                        stop_reason = 'structure_' + failed.classify()
                        break
                    feedback = '[' + failed.kind + '] ' + failed.summary[:12000]
                    continue
                checked_candidates.append(candidate)
                if best is None:
                    best = candidate
                    ctx.select_candidate(best.id, reason='structural_fallback')
                if suite is None:
                    stop_reason = 'properties_unavailable_or_rejected'
                    break
                property_result = ctx.execute(self.property_check, PropertyCheckInput(candidate, suite))
                if best_check is None:
                    best, best_check = candidate, property_result
                elif strictly_improves(property_result, best_check):
                    best, best_check = candidate, property_result
                    ctx.select_candidate(candidate.id, reason='same_properties_strict_improvement')
                else:
                    ctx.emit('property_selection', candidate_id=candidate.id,
                        reason='no_strict_improvement', retained_candidate_id=best.id)
                if property_result.status == 'passed' and property_result.details.get('classification') == 'simulation_checked':
                    stop_reason = 'properties_simulation_checked'
                    break
                failed_ids = set(property_result.details.get('failed_property_ids', ()))
                if not failed_ids or property_result.status != 'failed':
                    stop_reason = 'property_' + property_result.details.get('classification', property_result.status)
                    break
                diagnosis = ctx.execute(self.json, JsonInput(ctx.task, DIAGNOSE,
                    'property_diagnosis', {'suite': suite, 'rtl': candidate.code,
                    'property_result': property_result.public_dict()}))
                data = diagnosis.data
                quote = data.get('quote')
                cited = data.get('property_ids', ())
                source = ctx.task.prompt + '\n' + ctx.task.interface
                supported = (diagnosis.status == 'ready' and isinstance(quote, str) and
                    bool(quote.strip()) and quote in source and
                    isinstance(cited, (tuple, list)) and bool(cited) and
                    all(isinstance(x, str) for x in cited) and
                    set(cited) <= failed_ids and isinstance(data.get('reason'), str) and
                    bool(data['reason'].strip()))
                target = data.get('target') if supported else 'uncertain'
                ctx.emit('property_diagnosis', candidate_id=candidate.id,
                    source_call_id=diagnosis.call_id, target=target, evidence=_thaw(data))
                if target in ('rtl', 'plan'):
                    feedback = json.dumps({'scope': 'finite Vivado stimuli only',
                        'diagnosis': _thaw(data), 'suite': _thaw(suite),
                        'replayed_counterexamples': _thaw(property_result.details.get('properties', {})),
                        'instruction': 'Preserve every valid prior behavior; return complete RTL. '
                        'Correct the design plan first if its interpretation is wrong.'}, ensure_ascii=False)
                    continue
                if target == 'property' and revisions < self.max_property_revisions:
                    previous = suite
                    # The builder receives source-only facts, never the code-aware
                    # diagnosis, observed values or a free-form repair proposal.
                    revision_request = {'origin': 'exact_task_quote_property_review',
                        'quote': quote, 'property_ids': list(cited)}
                    revised = self._build(ctx, json.dumps(revision_request, ensure_ascii=False), previous)
                    revisions += 1
                    if revised is None:
                        stop_reason = 'property_revision_rejected'
                        break
                    old_properties = {p['id']: p for p in previous['properties']}
                    new_properties = {p['id']: p for p in revised['properties']}
                    frozen_fields = set(previous) - {'version', 'properties'}
                    changed_domain = (set(revised) != set(previous) or
                        any(_thaw(previous[k]) != _thaw(revised[k]) for k in frozen_fields))
                    changed_ids = tuple(identifier for identifier, prop in old_properties.items()
                        if identifier in new_properties and _thaw(prop) != _thaw(new_properties[identifier]))
                    unsafe_properties = (list(old_properties) != list(new_properties) or
                        any(identifier not in cited for identifier in changed_ids) or
                        any(identifier not in new_properties or
                            new_properties[identifier]['quote'] != prop['quote'] or
                            new_properties[identifier]['id'] != prop['id']
                            for identifier, prop in old_properties.items()))
                    if changed_domain or unsafe_properties:
                        stop_reason = 'property_revision_changed_unattributed_obligations'
                        break
                    if not changed_ids:
                        stop_reason = 'property_revision_no_change'
                        break
                    suite = revised
                    ctx.emit('property_version_replaced', previous_version=previous['version'],
                        version=suite['version'], reason=revision_request,
                        property_changes={identifier: {'before': _thaw(old_properties[identifier]),
                            'after': _thaw(new_properties[identifier])} for identifier in changed_ids},
                        source_call_id=diagnosis.call_id)
                    # A new suite invalidates ALL previous comparisons. Recheck
                    # every structurally valid retained candidate before selecting.
                    best_check = None
                    for old in checked_candidates:
                        reevaluated = ctx.execute(self.property_check, PropertyCheckInput(old, suite))
                        if best_check is None or strictly_improves(reevaluated, best_check):
                            best, best_check = old, reevaluated
                    ctx.select_candidate(best.id, reason='property_revision_retested_all')
                    if best_check.status == 'passed':
                        stop_reason = 'properties_simulation_checked_after_revision'
                        break
                    # The old trace is retired. Diagnose only the NEW check;
                    # changing a checker never directly licenses an RTL edit.
                    if best_check.status == 'failed' and best_check.details.get('failed_property_ids'):
                        refreshed = ctx.execute(self.json, JsonInput(ctx.task, DIAGNOSE,
                            'property_diagnosis_after_revision', {'suite': suite,
                            'rtl': best.code, 'property_result': best_check.public_dict()}))
                        updated = refreshed.data
                        new_quote, new_ids = updated.get('quote'), updated.get('property_ids', ())
                        authorized = (refreshed.status == 'ready' and
                            updated.get('target') in ('rtl', 'plan') and
                            isinstance(new_quote, str) and bool(new_quote.strip()) and new_quote in source and
                            isinstance(new_ids, (list, tuple)) and bool(new_ids) and
                            all(isinstance(x, str) for x in new_ids) and
                            set(new_ids) <= set(best_check.details['failed_property_ids']) and
                            isinstance(updated.get('reason'), str) and bool(updated['reason'].strip()))
                        ctx.emit('property_diagnosis', candidate_id=best.id,
                            source_call_id=refreshed.call_id,
                            target=updated.get('target') if authorized else 'uncertain',
                            evidence=_thaw(updated))
                        if authorized:
                            parent = best
                            feedback = json.dumps({'diagnosis': _thaw(updated),
                                'suite': _thaw(suite),
                                'replayed_counterexamples': _thaw(best_check.details['properties'])}, ensure_ascii=False)
                            continue
                    stop_reason = 'property_revision_unresolved'
                    break
                stop_reason = 'property_failure_uncertain'
                break
            selected_id = ctx.state.selected_candidate_id
            if selected_id is not None:
                final = ctx.execute(self.synth, CheckInput(ctx.state.candidates[selected_id]))
                ctx.emit('property_final_synthesis', candidate_id=selected_id,
                         status=final.status, check_id=final.id, official_functional_level=False)
                if final.status != 'passed':
                    stop_reason += '_synthesis_' + final.status
            return ctx.finish(reason=stop_reason,
                status='completed' if stop_reason in ('properties_simulation_checked',
                    'properties_simulation_checked_after_revision') else 'stopped')
        except BudgetExhausted:
            return ctx.finish(reason='deadline', status='stopped')
        except ModelCallError as exc:
            return ctx.finish(reason='model_' + exc.kind, status='stopped')
