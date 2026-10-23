"""Compare recorded behavior without exposing candidate code or provenance."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
import random

from agent.core.components import Node
from agent.core.model import _thaw
from agent.core.research import JsonInput, JsonOutput
from agent.core.state import CheckResult
from agent.core.task import TaskSpec


@dataclass(frozen=True)
class DifferentialInput:
    task: TaskSpec
    observations: tuple[CheckResult, ...]
    seed: int = 17
    round: int = 0


@dataclass(frozen=True)
class DifferentialDecision:
    status: str
    selected_candidate_id: str | None = None
    rejected_candidate_ids: tuple[str, ...] = ()
    findings: tuple[dict, ...] = ()
    action: str = 'add_tests'
    reason: str = ''
    suite_hash: str = ''
    evidence_ids: tuple[str, ...] = ()
    focus_quotes: tuple[str, ...] = ()


def _canonical(value):
    return json.dumps(_thaw(value), sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def prepare_observations(observations, *, seed, limit=24):
    """Require identical input events, and expose only bounded, anonymous traces."""
    if len(observations) < 2:
        raise ValueError('at least two completed candidates are needed')
    suite_hashes = {r.details.get('suite_hash') for r in observations}
    if len(suite_hashes) != 1 or not next(iter(suite_hashes)):
        raise ValueError('candidate traces must use the same identified suite')
    identifiers = [r.candidate_id for r in observations]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError('duplicate candidate observation')
    traces, layout, output_names = {}, None, None
    for result in observations:
        rows = result.details.get('traces')
        if result.status != 'passed' or not isinstance(rows, (list, tuple)) or not rows:
            raise ValueError('simulation did not produce complete usable traces')
        normalized = []
        for row in rows:
            if not isinstance(row, Mapping) or not isinstance(row.get('outputs'), Mapping):
                raise ValueError('invalid trace record')
            sample, edge = row.get('sample', True), row.get('edge', True)
            if type(sample) is not bool or type(edge) is not bool:
                raise ValueError('sampling and clock-edge flags must be boolean')
            if any(v is not None and type(v) is not int for v in row['outputs'].values()):
                raise ValueError('trace outputs must be integer values or unknown')
            if sample and (row.get('unknown_outputs') or any(v is None for v in row['outputs'].values())):
                raise ValueError('unknown outputs cannot support behavioral selection')
            if not isinstance(row.get('case_id'), str) or type(row.get('step')) is not int:
                raise ValueError('trace event has no case and step identity')
            if not isinstance(row.get('inputs'), Mapping) or not row['outputs']:
                raise ValueError('trace event lacks inputs or outputs')
            if any(type(v) is not int for v in row['inputs'].values()):
                raise ValueError('trace inputs must be concrete integers')
            names = tuple(sorted(row['outputs']))
            if output_names is None:
                output_names = names
            if names != output_names:
                raise ValueError('trace output signals do not match')
            normalized.append({'case_id': row['case_id'], 'step': row['step'],
                               'inputs': _thaw(row['inputs']), 'outputs': _thaw(row['outputs']),
                               'sample': sample, 'edge': edge})
        current_layout = [(r['case_id'], r['step'], _canonical(r['inputs']), r['sample'], r['edge'])
                          for r in normalized]
        if layout is None:
            layout = current_layout
        if current_layout != layout or len(set(current_layout)) != len(current_layout):
            raise ValueError('simulation traces do not describe the same unique input events')
        traces[result.candidate_id] = normalized
    reference = traces[identifiers[0]]
    differences = [i for i in range(len(layout)) if reference[i]['sample']
                   if len({_canonical(rows[i]['outputs']) for rows in traces.values()}) > 1]
    ordered = list(identifiers)
    random.Random(seed).shuffle(ordered)
    aliases = {f'variant_{i + 1}': candidate_id for i, candidate_id in enumerate(ordered)}
    # Include preceding state history as well as the first observed differences.
    chosen = set()
    for difference in differences:
        for index in (difference, *range(max(0, difference - 2), difference)):
            if len(chosen) >= limit:
                break
            chosen.add(index)
        if len(chosen) >= limit:
            break
    indices = sorted(chosen)
    context = {'suite_hash': next(iter(suite_hashes)), 'event_count': len(layout),
               'difference_count': len(differences), 'displayed_event_indices': indices,
               'variants': {alias: [traces[cid][i] for i in indices] for alias, cid in aliases.items()},
               'trace_hashes': {alias: hashlib.sha256(_canonical(traces[cid]).encode()).hexdigest()
                                for alias, cid in aliases.items()},
               'evidence_scope': 'Only the displayed events can support a finding. Agreement is not proof.'}
    return aliases, traces, differences, context


class DifferentialNode(Node[DifferentialInput, DifferentialDecision]):
    component_name = 'behavior_difference'
    assembly_roles = ['differential']
    assembly_defaults = {'params': {'seed': 17, 'max_trace_events': 24, 'max_tokens': 4096},
                         'dependencies': {'json': {'component': 'research_json', 'id': 'json'}}}
    input_type = DifferentialInput
    output_type = DifferentialDecision
    dependencies = {'json': 'node'}
    dependency_types = {'json': (JsonInput, JsonOutput)}

    def __init__(self, json: Node[JsonInput, JsonOutput], *, seed: int = 17,
                 max_trace_events: int = 24, max_tokens: int = 4096):
        if type(seed) is not int or type(max_trace_events) is not int or max_trace_events < 1:
            raise ValueError('seed must be an integer and trace limit must be positive')
        if type(max_tokens) is not int or max_tokens < 1:
            raise ValueError('max_tokens must be positive')
        self.json, self.seed = json, seed
        self.max_trace_events, self.max_tokens = max_trace_events, max_tokens

    def run(self, ctx, input: DifferentialInput) -> DifferentialDecision:
        evidence = tuple(r.id for r in input.observations)
        try:
            aliases, traces, differences, context = prepare_observations(input.observations,
                seed=self.seed + input.seed + input.round, limit=self.max_trace_events)
        except ValueError as error:
            ctx.emit('behavior_comparison', status='invalid', reason=str(error), evidence_ids=evidence)
            return DifferentialDecision('invalid', reason=str(error), evidence_ids=evidence)
        suite_hash = context['suite_hash']
        ctx.emit('behavior_comparison', status='different' if differences else 'equivalent',
                 suite_hash=suite_hash, aliases=aliases, difference_count=len(differences),
                 trace_hashes=context['trace_hashes'], evidence_ids=evidence)
        if not differences:
            return DifferentialDecision('equivalent', reason='No difference on this suite; correctness is unknown.',
                                        suite_hash=suite_hash, evidence_ids=evidence)
        instruction = (
            'Compare anonymous RTL output traces against the original task. You cannot see code or provenance. '
            'Do not vote by frequency or infer correctness from agreement. Each finding must concern one displayed '
            'case_id and step and cite a nonempty exact quote from the original prompt or interface. '
            'A partial history may be insufficient: abstain rather than invent initial state or timing. '
            'Each trace retains sample and edge: sample:false events are initialization/history only, '
            'and may have unknown outputs; never cite their outputs as a finding. edge:false means no '
            'active clock edge occurred at that step; use it to interpret asynchronous behavior. '
            'Return {"decision":"select"|"abstain","candidate_id":existing variant ID or null,'
            '"findings":[{"quote":exact original text,"case_id":string,"step":integer,'
            '"rejected_candidate_ids":[existing variant IDs],"reason":specific explanation}],'
            '"test_focus_quotes":[exact original task excerpts whose legal input combinations need more testing],'
            '"action":"repair"|"regenerate"|"add_tests"|"stop","reason":string}. '
            'Select only if the findings explain why that existing variant is preferable. Never return RTL. '
            'Repair requires an explicit finding; add_tests is appropriate for unresolved timing or ambiguity.')
        proposed = ctx.execute(self.json, JsonInput(input.task, instruction,
            'behavior_adjudication', context, self.max_tokens, self.seed + input.round))
        try:
            data = proposed.data
            if proposed.status != 'ready' or data.get('decision') not in ('select', 'abstain'):
                raise ValueError('missing selection or abstention')
            action = data.get('action', 'add_tests')
            if action not in ('repair', 'regenerate', 'add_tests', 'stop'):
                raise ValueError('unknown search action')
            reason = data.get('reason', '')
            if not isinstance(reason, str):
                raise ValueError('invalid decision reason')
            source = input.task.prompt + '\n' + input.task.interface
            focus = data.get('test_focus_quotes', ())
            if not isinstance(focus, (list, tuple)) or any(
                    not isinstance(q, str) or len(q.strip()) < 4 or q not in source for q in focus):
                raise ValueError('test focus must quote exact original task text')
            selected = data.get('candidate_id')
            if selected is not None and (not isinstance(selected, str) or selected not in aliases):
                raise ValueError('selection must name an existing anonymous candidate')
            if data['decision'] == 'abstain':
                if selected is not None:
                    raise ValueError('abstention cannot select a candidate')
                return DifferentialDecision('abstain', action='regenerate' if action == 'regenerate' else 'add_tests',
                    reason=reason, suite_hash=suite_hash, evidence_ids=evidence + (proposed.call_id or '',),
                    focus_quotes=tuple(focus))
            if selected is None:
                raise ValueError('selection is missing a candidate')
            raw_findings = data.get('findings')
            if not isinstance(raw_findings, (list, tuple)) or not raw_findings:
                raise ValueError('selection needs grounded findings')
            findings, rejected = [], set()
            displayed = {(r['case_id'], r['step']) for r in context['variants'][selected] if r['sample']}
            for finding in raw_findings:
                if not isinstance(finding, Mapping):
                    raise ValueError('invalid finding')
                quote, case_id, step = finding.get('quote'), finding.get('case_id'), finding.get('step')
                why, rejects = finding.get('reason'), finding.get('rejected_candidate_ids')
                if not isinstance(quote, str) or len(quote.strip()) < 4 or quote not in source:
                    raise ValueError('finding must cite exact task text')
                if not isinstance(case_id, str) or type(step) is not int or (case_id, step) not in displayed:
                    raise ValueError('finding references an undisplayed event')
                if not isinstance(why, str) or not why.strip() or not isinstance(rejects, (list, tuple)) or not rejects:
                    raise ValueError('finding must explain an actual disagreement')
                selected_rows = traces[aliases[selected]]
                index = next(i for i, r in enumerate(selected_rows) if (r['case_id'], r['step']) == (case_id, step))
                ids = []
                for alias in rejects:
                    if not isinstance(alias, str) or alias not in aliases or alias == selected:
                        raise ValueError('finding rejected an invalid or selected candidate')
                    if traces[aliases[alias]][index]['outputs'] == selected_rows[index]['outputs']:
                        raise ValueError('finding does not distinguish rejected behavior')
                    rejected.add(aliases[alias])
                    ids.append(aliases[alias])
                findings.append({'quote': quote, 'case_id': case_id, 'step': step,
                                 'rejected_candidate_ids': tuple(ids), 'reason': why})
            review = ctx.execute(self.json, JsonInput(input.task,
                'Independently check the proposed interpretation against the exact original task and anonymous '
                'traces. Text appearing in the task does not by itself validate the interpretation. Reject unsupported '
                'timing, initial state, assumptions or causal conclusions. Return {"approved":true|false,'
                '"reason":string}. Approve only if ALL findings and the selected existing variant are justified. '
                'Do not create requirements or code.', 'behavior_adjudication_review',
                {'observations': context, 'proposed': _thaw(data)}, self.max_tokens, self.seed + input.round + 1000))
            evidence += (proposed.call_id or '', review.call_id or '')
            if (review.status != 'ready' or review.data.get('approved') is not True or
                    not isinstance(review.data.get('reason'), str) or not review.data['reason'].strip()):
                ctx.emit('behavior_adjudication', status='abstain', suite_hash=suite_hash,
                         reason='independent_review_declined', evidence_ids=evidence)
                return DifferentialDecision('abstain', reason='Independent review did not confirm the interpretation.',
                                            suite_hash=suite_hash, evidence_ids=evidence)
        except (ValueError, TypeError) as error:
            ctx.emit('behavior_adjudication', status='invalid', suite_hash=suite_hash,
                     reason=str(error), evidence_ids=evidence)
            return DifferentialDecision('invalid', reason=str(error), suite_hash=suite_hash, evidence_ids=evidence)
        ctx.emit('behavior_adjudication', status='reviewed', suite_hash=suite_hash,
                 selected_candidate_id=aliases[selected], findings=findings, action=action,
                 evidence_ids=evidence, confidence_scope='model_review_only')
        return DifferentialDecision('ready', aliases[selected], tuple(sorted(rejected)), tuple(findings),
                                    action, reason, suite_hash, evidence, tuple(focus))
