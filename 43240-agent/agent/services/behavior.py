"""Specification-derived stimulus data; never execute model-written test code."""
from __future__ import annotations
from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path
import re
import shutil
import time

from agent.core.task import TaskSpec
from agent.services.timing import (TimingContract, parse_timing, specification_quote,
                                   timing_history, validate_timing)
from agent.services.vivado import ToolResult, TOOL_SUMMARY_LIMIT, _build_result, _make_work_dir, _unavailable
from agent.services.plan_format import resolve_basis, cycle_steps
from agent.services.literal_spec import LiteralTruthTable, parse_literal_truth_table
from agent.services.spec_ports import supported_ports, validate_candidate_ports


@dataclass(frozen=True)
class StimulusStep:
    inputs: tuple[tuple[str, int], ...]
    wait_ns: int
    expected: tuple[tuple[str, int], ...]
    basis: str


@dataclass(frozen=True)
class TestPlan:
    top: str
    ports: tuple[tuple[str, str, int], ...]
    steps: tuple[StimulusStep, ...]
    timing: TimingContract = TimingContract()
    literal_table: LiteralTruthTable | None = None

    def public_dict(self):
        result = dict(oracle_protocol=2, top=self.top, ports=[list(p) for p in self.ports], timing=self.timing.public_dict(), steps=[
            dict(inputs=dict(s.inputs), wait_ns=s.wait_ns, expected=dict(s.expected), basis=s.basis)
            for s in self.steps])
        if self.literal_table:
            result['literal_table'] = self.literal_table.public_dict()
        return result

    @property
    def oracle_source(self):
        return 'public_literal_truth_table' if self.literal_table else 'model_spec_hypothesis'

    @property
    def fingerprint(self):
        return hashlib.sha256(json.dumps(self.public_dict(), sort_keys=True).encode()).hexdigest()

    def trace_dict(self):
        return dict(plan_hash=self.fingerprint, steps=len(self.steps),
                    assertions=sum(len(s.expected) for s in self.steps),
                    oracle_protocol=2, oracle_source=self.oracle_source, official_verification=False)


def parse_plan(text: str, task: TaskSpec, *, max_steps=32) -> TestPlan:
    """Reject injection, unsupported interfaces, ungrounded expectations and truncation."""
    if len(text) > 65536:
        raise ValueError('test plan exceeds size limit')
    stripped = text.strip()
    if stripped.startswith('```'):
        match = re.fullmatch(r'```(?:json)?\s*\n(.*?)\n```', stripped, re.S)
        if not match:
            raise ValueError('expected one complete JSON block')
        stripped = match.group(1)
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate JSON key')
            result[key] = value
        return result
    raw = json.loads(stripped, object_pairs_hook=unique)
    if isinstance(raw, dict) and set(raw) == {'unsupported'} and isinstance(raw['unsupported'], str):
        raise ValueError('unsupported plan: ' + raw['unsupported'][:200])
    if not isinstance(raw, dict) or set(raw) not in ({'steps'}, {'steps', 'timing'}, {'cycles', 'timing'}):
        raise ValueError('test plan must contain steps or cycles and a timing contract')
    ports = supported_ports(task)
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', task.top):
        raise ValueError('unsupported top name')
    inputs = {n: w for n, d, w in ports if d == 'input'}
    outputs = {n: w for n, d, w in ports if d == 'output'}
    timing_raw = raw.get('timing')
    if isinstance(timing_raw, dict) and timing_raw.get('kind') == 'sequential':
        timing_raw = dict(timing_raw)
        for field in ('basis', 'reset_basis'):
            timing_raw[field] = resolve_basis(timing_raw.get(field), task.prompt)
    timing = parse_timing(timing_raw, task, inputs, outputs)
    rows = (cycle_steps(raw['cycles'], timing, inputs, max_steps=max_steps,
                        prompt=task.prompt, reset_basis=(timing_raw or {}).get('reset_basis'))
            if 'cycles' in raw else raw['steps'])
    if not isinstance(rows, list) or not 1 <= len(rows) <= max_steps:
        raise ValueError('invalid step count')
    steps = []
    assertions = 0
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != {'inputs', 'wait_ns', 'expected', 'basis'}:
            raise ValueError('invalid step fields')
        def values(field, allowed):
            value = row[field]
            if not isinstance(value, dict) or not set(value) <= set(allowed):
                raise ValueError('unknown signal in ' + field)
            result = []
            for name, number in value.items():
                if isinstance(number, str) and re.fullmatch(r'(?:0|[1-9][0-9]*)', number):
                    number = int(number, 10)
                if isinstance(number, str) and re.fullmatch(r'(?:0[xX][0-9a-fA-F]+|0[bB][01]+|0[oO][0-7]+)', number):
                    number = int(number, 0)
                if type(number) is not int:
                    raise ValueError('signal value must be an unsigned integer literal: ' + name)
                if not 0 <= number < 2 ** allowed[name]:
                    raise ValueError('signal value outside port width')
                result.append((name, number))
            return tuple(sorted(result))
        driven, expected = values('inputs', inputs), values('expected', outputs)
        if index == 0 and set(dict(driven)) != set(inputs):
            raise ValueError('first step must initialize all inputs')
        delay, basis = row['wait_ns'], row['basis']
        if type(delay) is not int or not 1 <= delay <= 1000:
            raise ValueError('wait_ns must be an integer from 1 to 1000')
        if expected:
            # Scheduler-produced reset checks already hold verified source spans.
            if 'cycles' in raw and index == 1:
                basis = timing.reset_basis
            else:
                basis = specification_quote(resolve_basis(basis, task.prompt), task.prompt)
        elif not isinstance(basis, str) or len(basis) > 2000:
            raise ValueError('invalid specification basis')
        assertions += len(expected)
        steps.append(StimulusStep(driven, delay, expected, basis))
    if not assertions:
        raise ValueError('test plan has no expectations')
    table = parse_literal_truth_table(task)
    if table:
        driven = {}
        for step in steps:
            driven.update(step.inputs)
            literal_expected = table.expected(driven)
            if any(literal_expected[name] != value for name, value in step.expected):
                raise ValueError('model expectation contradicts the public literal truth table')
    plan = TestPlan(task.top, tuple(ports), tuple(steps), timing, table)
    validate_timing(plan)
    return plan


def literal_truth_table_plan(task):
    """Enumerate the certified public table; no model call or arithmetic oracle."""
    table = parse_literal_truth_table(task)
    if table is None:
        return None
    ports = tuple((p.name, p.direction, p.width) for p in task.expected_interface.ports)
    steps = tuple(StimulusStep(tuple(zip(table.inputs, ins)), 1,
                              tuple(zip(table.outputs, outs)), table.basis)
                  for ins, outs in table.rows)
    plan = TestPlan(task.top, ports, steps, literal_table=table)
    validate_timing(plan)
    return plan


def render_driver(plan: TestPlan) -> str:
    validate_timing(plan)
    outputs = [n for n, d, _ in plan.ports if d == 'output']
    lines = ['`timescale 1ns/1ps', 'module agent_tb;']
    for name, direction, width in plan.ports:
        lines.append(f"  {'reg' if direction == 'input' else 'wire'} [{width-1}:0] {name};")
    lines.append(f"  {plan.top} dut(" + ', '.join(f'.{n}({n})' for n, _, _ in plan.ports) + ');')
    lines.append('  initial begin')
    widths = {n: w for n, _, w in plan.ports}
    for index, step in enumerate(plan.steps):
        # Establish the inactive clock BEFORE other initial inputs. Subsequent
        # active edges are isolated from data/reset changes by validation.
        ordered = sorted(step.inputs, key=lambda pair: (pair[0] != plan.timing.clock, pair[0]))
        for name, value in ordered:
            lines.append(f"    {name} = {widths[name]}'h{value:x};")
        lines.append(f'    #{step.wait_ns};')
        fmt = f'AGENT_SAMPLE|{index}' + ''.join(f'|{n}=%h' for n in outputs)
        lines.append(f'    $display("{fmt}", ' + ', '.join(outputs) + ');')
    lines.extend([f'    $display("AGENT_DONE|{len(plan.steps)}");', '    $finish;',
                  '  end', 'endmodule', ''])
    return '\n'.join(lines)


def analyze_trace(output: str, plan: TestPlan):
    """Missing/unknown samples are distinct from mismatches with a hypothesis oracle."""
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
    hypothesis_mismatches, hypothesis_assertions, first = 0, 0, None
    properties, first_property = [], None
    initialized = False
    reset_probes = []
    history = timing_history(plan)
    timing = plan.timing
    def known(value):
        return not any(c in value for c in 'xz')
    def mismatch(index, name, expected, actual, basis, source):
        return dict(step=index, time_ns=history[index]['time_ns'], signal=name,
                    expected=expected, actual_hex=actual, basis=basis, oracle_source=source,
                    timing=timing.public_dict(),
                    input_history=[dict(row, sampled_outputs=samples[i])
                                   for i, row in enumerate(history[:index + 1])])
    for index, step in enumerate(plan.steps):
        row = history[index]
        reset_event = (timing.kind == 'sequential' and row['reset_active']
                       and (row['active_edge'] or timing.reset_kind == 'asynchronous'))
        property_names = set()
        if plan.literal_table:
            for name, expected in plan.literal_table.expected(row['inputs']).items():
                actual = samples[index][name]
                status = ('inconclusive' if not known(actual) else
                          'passed' if int(actual, 16) == expected else 'failed')
                property_names.add(name)
                properties.append(dict(id=f'public_literal_truth_table:{index}:{name}',
                    source='public_literal_truth_table', status=status, step=index, signal=name,
                    specification_hash=plan.literal_table.fingerprint))
                if status == 'failed':
                    item = mismatch(index, name, expected, actual, plan.literal_table.basis,
                                    'public_literal_truth_table')
                    if first_property is None:
                        first_property = item
                    if first is None:
                        first = item
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
                    expected = int(previous, 16) if known(previous) else None
                if source:
                    property_names.add(name)
                    status = ('inconclusive' if expected is None or not known(actual) else
                              'passed' if int(actual, 16) == expected else 'failed')
                    properties.append(dict(id=f'{source}:{index}:{name}', source=source,
                                           status=status, step=index, signal=name))
                    if status == 'failed':
                        item = mismatch(index, name, expected, actual,
                                        timing.reset_basis if reset_event else timing.basis,
                                        'spec_contract_property')
                        if first_property is None:
                            first_property = item
                        if first is None:
                            first = item
                if (index and row['reset_active'] and not history[index-1]['reset_active']
                        and not row['active_edge']):
                    previous = samples[index-1][name]
                    reset_probes.append(dict(step=index, signal=name,
                        discriminating=known(previous) and int(previous,16) != reset_value))
        for name, expected in step.expected:
            if name in property_names:
                continue  # Literal reset checks are properties, not model oracles.
            hypothesis_assertions += 1
            actual = samples[index][name]
            equal = known(actual) and int(actual, 16) == expected
            if not equal:
                hypothesis_mismatches += 1
                if first is None:
                    first = mismatch(index, name, expected, actual, step.basis, 'model_spec_hypothesis')
    property_mismatches = sum(p['status'] == 'failed' for p in properties)
    property_assertions = sum(p['status'] != 'inconclusive' for p in properties)
    return dict(plan_hash=plan.fingerprint, oracle_protocol=2, samples=samples,
                assertions=hypothesis_assertions + property_assertions,
                mismatches=hypothesis_mismatches + property_mismatches,
                hypothesis_assertions=hypothesis_assertions, hypothesis_mismatches=hypothesis_mismatches,
                property_assertions=property_assertions, property_mismatches=property_mismatches,
                property_inconclusive=sum(p['status'] == 'inconclusive' for p in properties),
                property_checks=properties, first_property_mismatch=first_property,
                reset_kind_probes=reset_probes,
                first_mismatch=first, valid_observation=True,
                oracle_source=plan.oracle_source, official_verification=False)


def run_behavior(toolchain, source: str, top: str, plan: TestPlan, timeout_s: float) -> ToolResult:
    """Vivado-only simulation through the existing managed executor and deadline."""
    started = time.monotonic()
    try:
        validate_candidate_ports(source, top, plan)
    except ValueError as exc:
        return replace(_unavailable('behavior', str(exc)), failure_kind='test',
                       details=dict(plan_hash=plan.fingerprint, valid_observation=False))
    search = toolchain.config.bin_dir if toolchain.config.bin_dir is not None else None
    xsim = shutil.which('xsim', path=search)
    if not toolchain.available or not xsim:
        return _unavailable('behavior', 'Vivado simulation tools unavailable')
    if top != plan.top:
        return _unavailable('behavior', 'test plan top differs from candidate top')
    work = _make_work_dir('agent_behavior_', toolchain.config.temp_dir)
    outcomes = []
    try:
        Path(work, 'solution.sv').write_text(source, encoding='utf-8')
        Path(work, 'agent_tb.sv').write_text(render_driver(plan), encoding='utf-8')
        commands = [
            [toolchain.xvlog, '--sv', 'solution.sv'],
            [toolchain.xvlog, '--sv', 'agent_tb.sv'],
            [toolchain.xelab, 'agent_tb', '-s', 'agent_snapshot', '-timescale', '1ns/1ps'],
            [xsim, 'agent_snapshot', '-runall'],
        ]
        for index, command in enumerate(commands):
            remaining = timeout_s - (time.monotonic() - started)
            if remaining <= 0:
                result = (_build_result('behavior', outcomes, work, toolchain.config.keep_work,
                                       toolchain.log_dir, toolchain.redactor) if outcomes else
                          _unavailable('behavior', 'self-test budget exhausted before execution'))
                return replace(result, status='timeout', rc=124, failure_kind='timeout',
                    summary='self-test budget exhausted before next simulation stage',
                    details=dict(plan_hash=plan.fingerprint, stage=index, valid_observation=False))
            outcome = toolchain._command(command, work, remaining)
            outcomes.append(outcome)
            if outcome.status != 'ok':
                result = _build_result('behavior', outcomes, work, toolchain.config.keep_work,
                                       toolchain.log_dir, toolchain.redactor)
                # DUT compile errors are source evidence; TB/elaboration failures are not.
                return replace(result, failure_kind=result.failure_kind if index == 0 else 'test',
                               details=dict(plan_hash=plan.fingerprint, stage=index, valid_observation=False))
        result = _build_result('behavior', outcomes, work, toolchain.config.keep_work,
                               toolchain.log_dir, toolchain.redactor)
        try:
            details = analyze_trace(outcomes[-1].output, plan)
        except (ValueError, KeyError, IndexError) as exc:
            return replace(result, status='unavailable', failure_kind='test',
                           summary=f'self-test observation unavailable: {exc}',
                           details=dict(plan_hash=plan.fingerprint, valid_observation=False))
        first = details['first_mismatch']
        summary = ('Self-test against public literals and/or specification-derived HYPOTHESES, not the official TB. '
                   f"Assertions={details['assertions']}, mismatches={details['mismatches']}. "
                   f"Model-hypothesis mismatches={details['hypothesis_mismatches']}; "
                   f"contract-property mismatches={details['property_mismatches']}; "
                   f"inconclusive properties={details['property_inconclusive']}. "
                   'Properties depend on certified public literals or the parsed timing contract; '
                   'this is not a proof of complete specification correctness.')
        if first:
            summary += '\nFirst mismatch: ' + json.dumps(first, ensure_ascii=False)
        if len(summary) > TOOL_SUMMARY_LIMIT:
            summary = summary[:TOOL_SUMMARY_LIMIT] + '\n[self-test summary truncated; structured history retained in details]'
        if not first and details['property_inconclusive']:
            return replace(result, status='unavailable', failure_kind='test',
                           summary=summary + '\nProperty observation is inconclusive, not a self-test pass.',
                           details=details)
        return replace(result, status='failed' if first else 'ok', failure_kind='behavior' if first else 'unknown',
                       summary=summary, details=details)
    finally:
        if not toolchain.config.keep_work:
            shutil.rmtree(work)
