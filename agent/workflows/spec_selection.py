"""Optional pure selection helper; no workflow is registered or enabled here."""
from collections.abc import Mapping
from agent.core.state import SelectionDecision
from agent.core.interface import parse_module_interface
from agent.services.port_signature import port_signature

_PROPERTY_SOURCES = frozenset(('public_literal_truth_table', 'explicit_reset_literal',
                               'observed_registered_hold'))
_TOOL_PASSES = frozenset(('interface', 'lint', 'synth'))


def _properties(check, plan_hash):
    if (check is None or check.status not in ('passed', 'failed')
            or check.details.get('valid_observation') is not True
            or check.details.get('official_verification') is not False
            or check.details.get('oracle_protocol') != 2
            or not plan_hash or check.details.get('plan_hash') != plan_hash):
        return None
    rows = check.details.get('property_checks')
    if not isinstance(rows, (tuple, list)) or not rows:
        return None
    result = {}
    for row in rows:
        if (not isinstance(row, Mapping) or row.get('source') not in _PROPERTY_SOURCES
                or not isinstance(row.get('id'), str) or not row['id'] or row['id'] in result
                or row.get('status') not in ('passed', 'failed')):
            return None
        result[row['id']] = row['status']
    return result


def _probe_coverage(check):
    probes = check.details.get('reset_kind_probes', ())
    if not isinstance(probes, (tuple, list)):
        return None
    result = {}
    for probe in probes:
        if (not isinstance(probe, Mapping) or type(probe.get('step')) is not int
                or not isinstance(probe.get('signal'), str)
                or type(probe.get('discriminating')) is not bool):
            return None
        key = (probe['step'], probe['signal'])
        if key in result:
            return None
        result[key] = probe['discriminating']
    return result


def choose_spec_candidate(state, *, plan_hash):
    """Only strict same-property improvement can displace a compilable answer.

    Model expectation scores never enter ranking. Preserve all tool passes,
    complete port semantics and property IDs; unknown/missing coverage keeps
    the old candidate. The calling workflow must explicitly apply this result.
    """
    eligible = []
    for candidate in state.candidates.values():
        evidence = [c for c in state.checks if c.candidate_id == candidate.id]
        if (candidate.extraction_status not in ('ok', 'complete', 'ambiguous')
                or any(c.classify() == 'code' for c in evidence)):
            continue
        latest = {c.kind:c for c in evidence if c.kind in _TOOL_PASSES}
        passed = frozenset(kind for kind, check in latest.items() if check.status == 'passed')
        observation = next((c for c in reversed(evidence) if c.kind == 'behavior'), None)
        rank = ('synth' in passed, 'lint' in passed, 'interface' in passed)
        eligible.append((candidate, passed, rank, observation, tuple(c.id for c in evidence)))
    current = next((r for r in eligible if r[0].id == state.selected_candidate_id), None)
    if current and 'lint' in current[1]:
        old_properties = _properties(current[3], plan_hash)
        old_coverage = _probe_coverage(current[3]) if old_properties is not None else None
        top = parse_module_interface(current[0].code).module_name
        old_ports = port_signature(current[0].code, top) if top else None
        for row in sorted(eligible, key=lambda r: r[2], reverse=True):
            new_properties = _properties(row[3], plan_hash)
            new_coverage = _probe_coverage(row[3]) if new_properties is not None else None
            if (old_properties is None or new_properties is None or old_ports is None
                    or old_coverage is None or new_coverage is None
                    or old_coverage.keys() != new_coverage.keys()
                    or any(not new_coverage[k] for k in old_coverage if old_coverage[k])
                    or not current[1] <= row[1]
                    or port_signature(row[0].code, top) != old_ports
                    or old_properties.keys() != new_properties.keys()
                    or any(new_properties[k] != 'passed' for k in old_properties if old_properties[k] == 'passed')):
                continue
            old_failed = {k for k in old_properties if old_properties[k] == 'failed'}
            new_failed = {k for k in new_properties if new_properties[k] == 'failed'}
            if new_failed < old_failed:
                return SelectionDecision(row[0].id, True, 'spec_property_improved', row[4])
        return SelectionDecision(current[0].id, False, 'protected_compilable_candidate', current[4])
    if not eligible:
        return SelectionDecision(None, state.selected_candidate_id is not None, 'no_eligible_candidate', ())
    strongest = max(r[2] for r in eligible)
    ties = [r for r in eligible if r[2] == strongest]
    chosen = next((r for r in ties if r[0].id == state.selected_candidate_id), ties[0])
    return SelectionDecision(chosen[0].id, chosen[0].id != state.selected_candidate_id,
                             'best_tool_evidence', chosen[4])
