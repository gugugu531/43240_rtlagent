"""Interpret observed samples using public properties and separate model hypotheses."""
from __future__ import annotations
import re
from agent.services.timing import timing_history
from agent.services.behavior_types import TestPlan


def _parse_samples(output: str, plan: TestPlan) -> list[dict[str, str]]:
    output_names = {n for n, d, _ in plan.ports if d == 'output'}
    samples = []
    for line in output.splitlines():
        if not line.startswith('AGENT_SAMPLE|'):
            continue
        parts = line.split('|')
        if int(parts[1]) != len(samples):
            raise ValueError('duplicate, missing or unordered sample')
        values = {}
        for pair in parts[2:]:
            name, value = pair.split('=', 1)
            if name in values or not re.fullmatch(r'[0-9a-fA-FxXzZ]+', value.strip()):
                raise ValueError('invalid sampled output')
            values[name] = value.strip().lower()
        if set(values) != output_names:
            raise ValueError('incomplete output sample')
        samples.append(values)
    if len(samples) != len(plan.steps) or f'AGENT_DONE|{len(plan.steps)}' not in output.splitlines():
        raise ValueError('simulation completion or sample count missing')
    return samples


def _known(value: str) -> bool:
    return not any(c in value for c in 'xz')


def _mismatch(index, name, expected, actual, basis, source, *, history, samples, timing):
    return dict(step=index, time_ns=history[index]['time_ns'], signal=name,
                expected=expected, actual_hex=actual, basis=basis, oracle_source=source,
                timing=timing.public_dict(),
                input_history=[dict(row, sampled_outputs=samples[i])
                               for i, row in enumerate(history[:index + 1])])


def _step_properties(plan: TestPlan, history, samples, index, initialized):
    """Check public literals and timing properties against this observed step."""
    properties, first_property, reset_probes = [], None, []
    row = history[index]
    timing = plan.timing
    reset_event = (timing.kind == 'sequential' and row['reset_active']
                   and (row['active_edge'] or timing.reset_kind == 'asynchronous'))
    if plan.literal_table:
        for name, expected in plan.literal_table.expected(row['inputs']).items():
            actual = samples[index][name]
            status = ('inconclusive' if not _known(actual) else
                      'passed' if int(actual, 16) == expected else 'failed')
            properties.append(dict(id=f'public_literal_truth_table:{index}:{name}',
                source='public_literal_truth_table', status=status, step=index, signal=name,
                specification_hash=plan.literal_table.fingerprint))
            if status == 'failed':
                item = _mismatch(index, name, expected, actual, plan.literal_table.basis,
                                 'public_literal_truth_table', history=history, samples=samples, timing=timing)
                if first_property is None:
                    first_property = item
    if reset_event:
        initialized = True
    if timing.kind == 'sequential' and initialized:
        for name, reset_value in timing.reset_values:
            actual = samples[index][name]
            source, expected = None, None
            if reset_event:
                source, expected = 'explicit_reset_literal', reset_value
            elif index and not row['active_edge']:
                source = 'observed_registered_hold'
                previous = samples[index - 1][name]
                expected = int(previous, 16) if _known(previous) else None
            if source:
                status = ('inconclusive' if expected is None or not _known(actual) else
                          'passed' if int(actual, 16) == expected else 'failed')
                properties.append(dict(id=f'{source}:{index}:{name}', source=source,
                                       status=status, step=index, signal=name))
                if status == 'failed':
                    item = _mismatch(index, name, expected, actual,
                                     timing.reset_basis if reset_event else timing.basis,
                                     'spec_contract_property', history=history, samples=samples, timing=timing)
                    if first_property is None:
                        first_property = item
            if (index and row['reset_active'] and not history[index-1]['reset_active']
                    and not row['active_edge']):
                previous = samples[index-1][name]
                reset_probes.append(dict(step=index, signal=name,
                    discriminating=_known(previous) and int(previous,16) != reset_value))
    return properties, first_property, reset_probes, initialized


def _step_hypotheses(plan: TestPlan, history, samples, index, property_names, first):
    """Count model expectations only for signals not covered by public properties."""
    assertions, mismatches, inconclusive = 0, 0, 0
    step = plan.steps[index]
    for name, expected in step.expected:
        if name in property_names:
            continue  # Literal reset checks are properties, not model oracles.
        actual = samples[index][name]
        if not _known(actual):
            inconclusive += 1
            continue
        assertions += 1
        if int(actual, 16) != expected:
            mismatches += 1
            if first is None:
                first = _mismatch(index, name, expected, actual, step.basis, 'model_spec_hypothesis',
                                  history=history, samples=samples, timing=plan.timing)
    return assertions, mismatches, inconclusive, first


def analyze_trace(output: str, plan: TestPlan) -> dict:
    """Missing/unknown samples are distinct from mismatches with a hypothesis oracle."""
    samples = _parse_samples(output, plan)
    hypothesis_mismatches, hypothesis_assertions, first = 0, 0, None
    hypothesis_inconclusive = 0
    properties, first_property = [], None
    initialized = False
    reset_probes = []
    history = timing_history(plan)
    for index, step in enumerate(plan.steps):
        checks, mismatch, probes, initialized = _step_properties(plan, history, samples, index, initialized)
        properties.extend(checks)
        reset_probes.extend(probes)
        if first_property is None:
            first_property = mismatch
        if first is None:
            first = mismatch
        property_names = {check['signal'] for check in checks}
        assertions, mismatches, inconclusive, first = _step_hypotheses(
            plan, history, samples, index, property_names, first)
        hypothesis_assertions += assertions
        hypothesis_mismatches += mismatches
        hypothesis_inconclusive += inconclusive
    property_mismatches = sum(p['status'] == 'failed' for p in properties)
    property_assertions = sum(p['status'] != 'inconclusive' for p in properties)
    return dict(plan_hash=plan.fingerprint, oracle_protocol=2, samples=samples,
                assertions=hypothesis_assertions + property_assertions,
                mismatches=hypothesis_mismatches + property_mismatches,
                hypothesis_assertions=hypothesis_assertions, hypothesis_mismatches=hypothesis_mismatches,
                hypothesis_inconclusive=hypothesis_inconclusive,
                property_assertions=property_assertions, property_mismatches=property_mismatches,
                property_inconclusive=sum(p['status'] == 'inconclusive' for p in properties),
                property_checks=properties, first_property_mismatch=first_property,
                reset_kind_probes=reset_probes,
                first_mismatch=first, valid_observation=True,
                oracle_source=plan.oracle_source, official_verification=False)
