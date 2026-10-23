"""Restricted source-grounded properties checked only by Vivado simulation.

Only data is accepted from the model. The simulator testbench and command
arguments are written here, never supplied by a model. No formal proof or
unbounded claim follows from these finite stimuli.
"""
from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile
import time

from agent.core.interface import parse_module_interface
from agent.core.model import _thaw
from agent.core.process import ProcessRequest
from agent.core.tool import CheckOutcome


VERSION = 'vivado_properties_v1'
_IDENT = re.compile(r'[A-Za-z_][A-Za-z0-9_]*\Z')
_BINARY = {'eq': '==', 'ne': '!=', 'lt': '<', 'le': '<=', 'gt': '>',
           'ge': '>=', 'add': '+', 'sub': '-', 'and': '&', 'or': '|',
           'xor': '^', 'land': '&&', 'lor': '||', 'shl': '<<', 'shr': '>>'}
_UNARY = {'not': '~', 'lnot': '!', 'reduce_or': '|', 'reduce_and': '&',
          'reduce_xor': '^'}
_BOOL = {'eq', 'ne', 'lt', 'le', 'gt', 'ge', 'land', 'lor', 'lnot',
         'reduce_or', 'reduce_and', 'reduce_xor'}


def suite_hash(suite) -> str:
    return hashlib.sha256(json.dumps(_thaw(suite), sort_keys=True,
        separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def mask_comments(text, *, mask_strings=False):
    """Preserve offsets and strings while masking only actual Verilog comments."""
    chars, index, mode = list(text), 0, 'code'
    while index < len(text):
        pair = text[index:index + 2]
        char = text[index]
        if mode == 'line':
            if char == '\n':
                mode = 'code'
            else:
                chars[index] = ' '
        elif mode == 'block':
            if pair == '*/':
                chars[index:index + 2] = [' ', ' ']
                index += 1
                mode = 'code'
            elif char != '\n':
                chars[index] = ' '
        elif mode == 'string':
            if mask_strings and char != '\n':
                chars[index] = ' '
            if char == '\\' and index + 1 < len(text):
                if mask_strings:
                    chars[index + 1] = ' '
                index += 1
            elif char == '"':
                mode = 'code'
        elif pair in ('//', '/*'):
            chars[index:index + 2] = [' ', ' ']
            index += 1
            mode = 'line' if pair == '//' else 'block'
        elif char == '"':
            mode = 'string'
            if mask_strings:
                chars[index] = ' '
        index += 1
    return ''.join(chars)


def selected_module_text(code, top):
    """The public parser reads one module; locate exactly the requested one."""
    cleaned = mask_comments(code, mask_strings=True)
    declarations = list(re.finditer(r'\bmodule\s+([A-Za-z_][A-Za-z0-9_]*)\b', cleaned))
    selected = [m for m in declarations if m.group(1) == top]
    if len(selected) != 1:
        return ''
    start = selected[0].start()
    end = re.search(r'\bendmodule\b', cleaned[selected[0].end():])
    if end is None:
        return ''
    return code[start:selected[0].end() + end.end()]


def expression(expr, ports, *, inputs_only=False, sequential=False, depth=0,
               past=False) -> tuple[str, int]:
    """Compile an unsigned, explicitly sized expression; reject Verilog text."""
    if depth > 16:
        raise ValueError('property expression is too deep')
    if isinstance(expr, str):
        if expr not in ports or (inputs_only and ports[expr]['direction'] != 'input'):
            raise ValueError('unknown signal or output constrained by an assumption')
        return 'p_' + expr, ports[expr]['width']
    if not isinstance(expr, Mapping):
        raise ValueError('expression must be a signal or an expression object')
    if 'const' in expr:
        if set(expr) != {'const', 'width'}:
            raise ValueError('constant needs only const and width')
        value, width = expr['const'], expr['width']
        if type(width) is not int or not 1 <= width <= 256:
            raise ValueError('constant width must be between 1 and 256')
        if type(value) is not int or not 0 <= value < (1 << width):
            raise ValueError('constant must fit its unsigned width')
        return f"{width}'d{value}", width
    op, args = expr.get('op'), expr.get('args')
    if not isinstance(args, (tuple, list)) or len(args) > 32:
        raise ValueError('operator args must be a short list')
    if set(expr) - {'op', 'args', 'hi', 'lo'}:
        raise ValueError('unknown expression field')
    if op == 'past':
        if not sequential or past or len(args) != 1:
            raise ValueError('past requires one argument, one clock and no nested past')
        text, width = expression(args[0], ports, inputs_only=inputs_only,
                                sequential=sequential, depth=depth + 1, past=True)
        return f'$past({text})', width
    compiled = [expression(x, ports, inputs_only=inputs_only,
        sequential=sequential, depth=depth + 1, past=past) for x in args]
    if op in _BINARY:
        if len(args) != 2:
            raise ValueError('binary operator needs two arguments')
        (a, wa), (b, wb) = compiled
        if op in ('land', 'lor') and (wa != 1 or wb != 1):
            raise ValueError('logical operators require one-bit operands')
        if op not in ('shl', 'shr') and wa != wb:
            raise ValueError('operator operands need equal explicit widths')
        return f'({a} {_BINARY[op]} {b})', 1 if op in _BOOL else wa
    if op in _UNARY:
        if len(args) != 1:
            raise ValueError('unary operator needs one argument')
        a, width = compiled[0]
        return f'({_UNARY[op]}{a})', 1 if op in _BOOL else width
    if op == 'mux':
        if len(args) != 3 or compiled[0][1] != 1 or compiled[1][1] != compiled[2][1]:
            raise ValueError('mux needs a one-bit condition and equal arm widths')
        return f'({compiled[0][0]} ? {compiled[1][0]} : {compiled[2][0]})', compiled[1][1]
    if op == 'concat':
        width = sum(w for _, w in compiled)
        if not compiled or width > 256:
            raise ValueError('concat needs arguments with total width at most 256')
        return '{' + ', '.join(t for t, _ in compiled) + '}', width
    if op == 'slice':
        hi, lo = expr.get('hi'), expr.get('lo')
        if (len(args) != 1 or type(hi) is not int or type(lo) is not int or
                not 0 <= lo <= hi < compiled[0][1]):
            raise ValueError('invalid slice')
        # A shift followed by a sized cast also works for compound expressions.
        return f"{hi - lo + 1}'(({compiled[0][0]}) >> {lo})", hi - lo + 1
    raise ValueError('unsupported property operator')


def validate_suite(raw, task):
    if not isinstance(raw, Mapping):
        raise ValueError('property suite must be an object')
    suite = _thaw(raw)
    allowed = {'version', 'ports', 'clock', 'startup', 'warmup', 'assumptions',
               'properties', 'cases', 'unsupported_requirements'}
    if set(suite) - allowed:
        raise ValueError('unknown property suite field')
    if not _IDENT.fullmatch(task.top):
        raise ValueError('unsupported top module name')
    if type(suite.get('version')) is not int or suite['version'] <= 0:
        raise ValueError('suite version must be a positive integer')
    port_list = suite.get('ports')
    if not isinstance(port_list, list) or not 1 <= len(port_list) <= 32:
        raise ValueError('suite needs between 1 and 32 ports')
    ports = {}
    for port in port_list:
        if not isinstance(port, dict) or set(port) != {'name', 'direction', 'width'}:
            raise ValueError('port needs name, direction and width')
        name = port['name']
        if not isinstance(name, str) or len(name) > 64 or not _IDENT.fullmatch(name) or name in ports:
            raise ValueError('invalid or duplicate port name')
        if port['direction'] not in ('input', 'output'):
            raise ValueError('only input and output ports are supported')
        if type(port['width']) is not int or not 1 <= port['width'] <= 256:
            raise ValueError('port width must be between 1 and 256')
        ports[name] = port
    if not any(p['direction'] == 'output' for p in ports.values()):
        raise ValueError('at least one output is required')
    if task.expected_interface.parsed:
        want = {p.name: (p.direction, p.width) for p in task.expected_interface.ports}
        got = {p['name']: (p['direction'], p['width']) for p in port_list}
        if want != got:
            raise ValueError('property ports do not match the task interface')
    source = task.prompt + '\n' + task.interface
    if any(not re.search(r'\b' + re.escape(name) + r'\b', source) for name in ports):
        raise ValueError('property signal does not occur in the task')
    clock = suite.get('clock')
    if clock is not None:
        if (not isinstance(clock, dict) or set(clock) != {'name', 'edge'} or
                clock.get('name') not in ports or clock.get('edge') not in ('posedge', 'negedge')):
            raise ValueError('clock needs an input name and posedge/negedge edge')
        if ports[clock['name']]['direction'] != 'input' or ports[clock['name']]['width'] != 1:
            raise ValueError('clock must be a one-bit input')
    warmup, startup = suite.get('warmup', 0), suite.get('startup', [])
    if type(warmup) is not int or not 0 <= warmup <= 32:
        raise ValueError('warmup must be between 0 and 32')
    if not isinstance(startup, list) or len(startup) > 8:
        raise ValueError('startup must have at most eight phases')
    if clock is None and (warmup or startup):
        raise ValueError('combinational checks do not have startup or warmup')
    if clock is not None and (not startup or warmup < len(startup) + 1):
        raise ValueError('sequential checks require source-grounded reset startup and warmup')

    def quote(item):
        text = item.get('quote')
        if not isinstance(text, str) or not text.strip() or text not in source:
            raise ValueError('each property, assumption and startup phase needs an exact source quote')

    inputs = {n: p for n, p in ports.items() if p['direction'] == 'input' and
              (clock is None or n != clock['name'])}
    for phase in startup:
        if not isinstance(phase, dict) or set(phase) != {'values', 'quote'}:
            raise ValueError('startup phase needs values and quote')
        quote(phase)
        if not isinstance(phase['values'], dict) or not phase['values']:
            raise ValueError('startup needs explicit reset input values')
        for name, val in phase['values'].items():
            if name not in inputs or type(val) is not int or not 0 <= val < 1 << inputs[name]['width']:
                raise ValueError('startup may only assign non-clock input values')
    assumptions, properties = suite.get('assumptions', []), suite.get('properties')
    if not isinstance(assumptions, list) or len(assumptions) > 8:
        raise ValueError('at most eight assumptions are supported')
    if not isinstance(properties, list) or not 1 <= len(properties) <= 8:
        raise ValueError('between one and eight properties are required')
    identifiers = set()
    for index, item in enumerate(assumptions + properties):
        if not isinstance(item, dict) or set(item) != {'id', 'quote', 'when', 'assert'}:
            raise ValueError('condition needs id, quote, when and assert')
        if (not isinstance(item['id'], str) or len(item['id']) > 64 or not _IDENT.fullmatch(item['id']) or
                item['id'] in identifiers):
            raise ValueError('condition ids must be distinct identifiers')
        identifiers.add(item['id'])
        quote(item)
        for key in ('when', 'assert'):
            text, width = expression(item[key], ports, inputs_only=index < len(assumptions),
                                     sequential=clock is not None)
            if width != 1:
                raise ValueError('trigger and assertion must have one-bit results')
            if clock and re.search(r'\bp_' + re.escape(clock['name']) + r'\b', text):
                raise ValueError('properties must not constrain or inspect the sampled clock')
    cases = suite.get('cases')
    if not isinstance(cases, list) or not 1 <= len(cases) <= 16:
        raise ValueError('between one and sixteen stimulus cases are required')
    case_ids, total = set(), 0
    for case in cases:
        if not isinstance(case, dict) or set(case) != {'id', 'inputs'}:
            raise ValueError('stimulus case needs id and inputs')
        identifier = case['id']
        if not isinstance(identifier, str) or len(identifier) > 64 or not _IDENT.fullmatch(identifier) or identifier in case_ids:
            raise ValueError('stimulus case ids must be distinct identifiers')
        case_ids.add(identifier)
        frames = case['inputs']
        if not isinstance(frames, list) or not warmup < len(frames) <= 512:
            raise ValueError('each case needs checked samples and at most 512 steps')
        total += len(frames)
        for frame in frames:
            if not isinstance(frame, dict) or set(frame) != set(inputs):
                raise ValueError('each stimulus step must assign all non-clock inputs only')
            for name, val in frame.items():
                if type(val) is not int or not 0 <= val < 1 << inputs[name]['width']:
                    raise ValueError('stimulus value does not fit its unsigned port')
        for step, phase in enumerate(startup):
            if any(frames[step][n] != v for n, v in phase['values'].items()):
                raise ValueError('every case must begin with the declared reset sequence')
    if total > 2048 or len(json.dumps(suite)) > 200000:
        raise ValueError('property stimuli exceed the supported size')
    suite.update(clock=clock, startup=startup, warmup=warmup, assumptions=assumptions,
                 unsupported_requirements=suite.get('unsupported_requirements', []))
    return suite


def _decl(width):
    return '' if width == 1 else f'[{width - 1}:0] '


def _history_expressions(suite):
    """Translate past into registers updated after checking a sampled step."""
    ports = {p['name']: p for p in suite['ports']}
    history = {}

    def replace(expr):
        if isinstance(expr, Mapping) and expr.get('op') == 'past':
            key = json.dumps(_thaw(expr['args'][0]), sort_keys=True)
            if key not in history:
                text, width = expression(expr['args'][0], ports, sequential=True)
                number = len(history)
                while f'history_{number}' in ports or any(n == f'history_{number}' for n, _text, _width in history.values()):
                    number += 1
                history[key] = (f'history_{number}', text, width)
            return history[key][0]
        if isinstance(expr, Mapping) and 'args' in expr:
            return {**_thaw(expr), 'args': [replace(x) for x in expr['args']]}
        return expr

    items = [{**_thaw(p), 'when': replace(p['when']), 'assert': replace(p['assert'])}
             for p in suite['assumptions'] + suite['properties']]
    extended = {**ports, **{n: {'width': w, 'direction': 'output'} for n, _text, w in history.values()}}
    compiled = {p['id']: (expression(p['when'], extended)[0], expression(p['assert'], extended)[0])
                for p in items}
    return history, compiled


def build_testbench(suite, top, marker):
    if not _IDENT.fullmatch(marker):
        raise ValueError('invalid simulation marker')
    prefix, clock = 'RTLA_' + marker, suite['clock']
    ports = {p['name']: p for p in suite['ports']}
    history, expressions = _history_expressions(suite)
    lines = ['`timescale 1ns/1ps', 'module rtla_property_driver;']
    for ci, _case in enumerate(suite['cases']):
        lines += [f'wire done_{ci};', f'rtla_property_case_{ci} c{ci}(done_{ci});']
    lines += ['initial begin', f'$display("{prefix}|BEGIN");',
              'wait (&{' + ','.join('done_' + str(i) for i in range(len(suite['cases']))) + '});',
              '#1;', f'$display("{prefix}|END");', '$finish;', 'end', 'endmodule']
    for ci, case in enumerate(suite['cases']):
        case_id = case['id']
        lines.append(f'module rtla_property_case_{ci}(output reg done);')
        for name, port in ports.items():
            lines.append(('reg ' if port['direction'] == 'input' else 'wire ') + _decl(port['width']) + 'p_' + name + ';')
        for name, _text, width in history.values():
            lines.append('reg ' + _decl(width) + 'p_' + name + ';')
        lines.append(top + ' dut (' + ', '.join(f'.{n}(p_{n})' for n in ports) + ');')
        lines += ['reg eligible;', 'initial begin', 'done = 0;']
        if clock:
            lines.append(f'p_{clock["name"]} = {0 if clock["edge"] == "posedge" else 1};')
        for step, frame in enumerate(case['inputs']):
            for name, val in frame.items():
                lines.append(f"p_{name} = {ports[name]['width']}'d{val};")
            lines.append('#2;')
            fmt = ' '.join(n + '=%h' for n in ports)
            signals = ', '.join('p_' + n for n in ports)
            lines.append(f'$display("{prefix}|SAMPLE|{case_id}|{step}|{fmt}", {signals});')
            if step >= suite['warmup']:
                predicates = []
                for assumption in suite['assumptions']:
                    when, pred = expressions[assumption['id']]
                    predicates.append(f'((!({when})) || ({pred}))')
                lines.append('eligible = ' + (' && '.join(predicates) if predicates else "1'b1") + ';')
                lines.append(f'$display("{prefix}|ASSUME|{case_id}|{step}|%b", eligible);')
                for prop in suite['properties']:
                    identifier = prop['id']
                    when, pred = expressions[identifier]
                    event = prefix + '|CHECK|' + case_id + '|' + str(step) + '|' + identifier + '|'
                    lines += [f'if (eligible !== 1\'b1) $display("{event}SKIP");',
                        f'else if (({when}) === 1\'b0) $display("{event}INACTIVE");',
                        f'else if (({when}) !== 1\'b1) $display("{event}UNKNOWN");',
                        f'else if (({pred}) === 1\'b1) $display("{event}PASS");',
                        f'else if (({pred}) === 1\'b0) $display("{event}FAIL");',
                        f'else $display("{event}UNKNOWN");']
            # Nonblocking history updates preserve simultaneous old values.
            for name, text, _width in history.values():
                lines.append(f'p_{name} <= {text};')
            if clock:
                active = 1 if clock['edge'] == 'posedge' else 0
                lines += [f'p_{clock["name"]} = {active};', '#2;',
                          f'p_{clock["name"]} = {1 - active};', '#2;']
        lines += [f'$display("{prefix}|CASE_END|{case_id}");', 'done = 1;', 'end', 'endmodule']
    return '\n'.join(lines) + '\n'


def parse_events(output, suite, marker):
    prefix = 'RTLA_' + marker + '|'
    events = [line.strip()[len(prefix):] for line in output.splitlines()
              if line.strip().startswith(prefix)]
    if events.count('BEGIN') != 1 or events.count('END') != 1 or not events or events[-1] != 'END':
        raise ValueError('property simulation begin/end events missing or duplicated')
    cases = {c['id']: c for c in suite['cases']}
    properties = {p['id']: p for p in suite['properties']}
    samples, assumptions, checks, ended = {}, {}, {}, set()
    ports = {p['name']: p for p in suite['ports']}
    for event in events:
        if event in ('BEGIN', 'END'):
            continue
        parts = event.split('|')
        if parts[0] == 'CASE_END' and len(parts) == 2 and parts[1] in cases:
            if parts[1] in ended:
                raise ValueError('duplicate case end')
            ended.add(parts[1])
            continue
        if len(parts) < 4 or parts[1] not in cases or not parts[2].isdigit():
            raise ValueError('invalid property event')
        name, case_id, step = parts[0], parts[1], int(parts[2])
        key = (case_id, step)
        if case_id in ended or not 0 <= step < len(cases[case_id]['inputs']):
            raise ValueError('event after case end or outside input sequence')
        if name == 'SAMPLE' and len(parts) == 4:
            if key in samples or (step and (case_id, step - 1) not in samples):
                raise ValueError('sample duplicated or out of order')
            observed = {}
            for cell in parts[3].split():
                pair = cell.split('=')
                if len(pair) != 2 or pair[0] in observed or pair[0] not in ports or not re.fullmatch('[0-9a-fA-FxXzZ]+', pair[1]):
                    raise ValueError('invalid or duplicate sampled signal')
                observed[pair[0]] = pair[1]
            if set(observed) != set(ports):
                raise ValueError('sample omits a signal')
            for input_name, number in cases[case_id]['inputs'][step].items():
                actual = observed[input_name]
                if re.search('[xzXZ]', actual) or int(actual, 16) != number:
                    raise ValueError('sampled input differs from the frozen stimulus')
            samples[key] = parts[3]
        elif name == 'ASSUME' and len(parts) == 4 and parts[3] in ('0', '1', 'x', 'z'):
            if key not in samples or key in assumptions or step < suite['warmup']:
                raise ValueError('invalid assumption event position')
            assumptions[key] = parts[3]
        elif name == 'CHECK' and len(parts) == 5 and parts[3] in properties and parts[4] in (
                'PASS', 'FAIL', 'UNKNOWN', 'INACTIVE', 'SKIP'):
            check_key = (*key, parts[3])
            if key not in assumptions or check_key in checks:
                raise ValueError('check duplicated or missing sample/assumption')
            if (assumptions[key] == '1') == (parts[4] == 'SKIP'):
                raise ValueError('check is inconsistent with input assumptions')
            checks[check_key] = parts[4]
        else:
            raise ValueError('unknown property event')
    expected_samples = {(c['id'], i) for c in suite['cases'] for i in range(len(c['inputs']))}
    expected_assumptions = {k for k in expected_samples if k[1] >= suite['warmup']}
    expected_checks = {(*k, p) for k in expected_assumptions for p in properties}
    if set(samples) != expected_samples or set(assumptions) != expected_assumptions or set(checks) != expected_checks or ended != set(cases):
        raise ValueError('property samples, checks or case ends are incomplete')
    records = {}
    for identifier, prop in properties.items():
        values = [(k, v) for k, v in checks.items() if k[2] == identifier]
        failures = [k for k, v in values if v == 'FAIL']
        unknown = [k for k, v in values if v == 'UNKNOWN']
        passed = [k for k, v in values if v == 'PASS']
        classification = ('observed_counterexample' if failures else 'unknown' if unknown else
                          'simulation_checked' if passed else 'not_triggered_in_stimuli')
        record = {'quote': prop['quote'], 'classification': classification,
                  'trigger_hits': len(passed) + len(failures), 'passed_samples': len(passed),
                  'failed_samples': len(failures), 'unknown_samples': len(unknown), 'replayed': False}
        if failures:
            case_id, step, _identifier = failures[0]
            frames = cases[case_id]['inputs']
            record.update(first_failure_case=case_id, first_failure_step=step,
                actual_sample=samples[(case_id, step)],
                input_window=[{'step': i, 'values': frames[i]} for i in
                              range(max(0, step - 2), min(len(frames), step + 2))])
        records[identifier] = record
    return {'properties': records, 'valid_samples': sum(x == '1' for x in assumptions.values()),
            'blocked_samples': sum(x == '0' for x in assumptions.values()),
            'unknown_assumption_samples': sum(x not in ('0', '1') for x in assumptions.values()),
            'sample_count': len(samples)}


class PropertySimulationService:
    def __init__(self, *, xvlog_bin=None, xelab_bin=None, xsim_bin=None):
        self.configured = {'xvlog': xvlog_bin, 'xelab': xelab_bin, 'xsim': xsim_bin}

    def run(self, ctx, input):
        import os
        started = time.monotonic()
        commands, logs = [], []
        details = {'checker': VERSION, 'suite_hash': suite_hash(input.suite),
                   'scope': 'finite_stimuli_only', 'failure_kind': 'unknown',
                   'simulation_engine': 'Vivado xsim', 'properties': {}}
        work = None

        def result(status, summary, **extra):
            return CheckOutcome(status, summary, blocking=False,
                elapsed_s=time.monotonic() - started, command=tuple(commands),
                details={**details, **extra}, log_paths=tuple(logs),
                work_dir=None)

        try:
            suite = validate_suite(input.suite, ctx.task)
        except (ValueError, TypeError, KeyError) as exc:
            return result('error', '性质或激励格式不适用：' + str(exc), classification='invalid_suite')
        chain = ctx.toolchain() if callable(getattr(ctx, 'toolchain', None)) else None
        search = getattr(getattr(chain, 'config', None), 'bin_dir', None)
        if search is None:
            search = os.environ.get('VIVADO_BIN') or os.environ.get('PATH', '')
        paths = {n: (shutil.which(self.configured[n]) if self.configured[n] else
                 getattr(chain, n, None) or shutil.which(n, path=search)) for n in self.configured}
        details['tool_paths'] = paths
        details['tool_identity'] = {}
        for name, path in paths.items():
            try:
                details['tool_identity'][name] = hashlib.sha256(Path(path).read_bytes()).hexdigest() if path else None
            except OSError:
                details['tool_identity'][name] = None
        if any(not p for p in paths.values()):
            return result('unavailable', 'Vivado xvlog/xelab/xsim 不完整', failure_kind='environment')
        selected_source = selected_module_text(input.candidate.code, ctx.task.top)
        interface = parse_module_interface(selected_source)
        got = {p.name: (p.direction, p.width) for p in interface.ports}
        wanted = {p['name']: (p['direction'], p['width']) for p in suite['ports']}
        if not interface.parsed or interface.module_name != ctx.task.top or got != wanted:
            return result('error', '性质接口与 RTL 接口不一致', classification='interface_mismatch')
        scanned = mask_comments(input.candidate.code)
        if re.search(r'\bsigned\b|\$signed\b', mask_comments(selected_source)):
            return result('error', '首版性质检查只支持无符号 RTL', classification='unsupported_signed_rtl')
        if (re.search(r'`\s*(include|define|ifdef|ifndef)', scanned) or
                re.search(r'\b(force|release|bind|config|library)\b', scanned) or
                any(n not in ('clog2', 'signed', 'unsigned') for n in
                    re.findall(r'\$([A-Za-z_][A-Za-z0-9_]*)', scanned))):
            return result('error', '不支持外部文件、宏或系统任务', classification='unsupported_rtl')
        stem = 'property/' + input.candidate.id + '/' + details['suite_hash'][:16]
        stored = ctx.artifacts.write_text(stem + '/candidate.sv', input.candidate.code)
        details.update(artifact_directory=str(stored.parent), working_directory_retained=False)
        scratch = getattr(getattr(chain, 'config', None), 'temp_dir', None)
        try:
            temporary = tempfile.TemporaryDirectory(prefix='property_', dir=scratch)
        except OSError as exc:
            return result('unavailable', '无法准备本地临时目录：' + type(exc).__name__, failure_kind='environment')
        work = Path(temporary.name)
        try:
            Path(work, 'candidate.sv').write_text(input.candidate.code, encoding='utf-8')
            ctx.artifacts.write_json(stem + '/suite.json', suite)
            deadline = started + (ctx.timeout_s or 600.0)

            def execute(command, name):
                commands.append(tuple(command))
                answer = ctx.processes.run(ProcessRequest(tuple(command), str(work),
                    max(0.0, deadline - time.monotonic())))
                saved = ctx.artifacts.write_text(stem + '/' + name + '.log', answer.output)
                logs.append(str(saved))
                return answer

            def simulate(current, label):
                marker = 'm' + hashlib.sha256((input.candidate.code_hash +
                    suite_hash(current) + label).encode()).hexdigest()[:20]
                driver = build_testbench(current, ctx.task.top, marker)
                ctx.artifacts.write_text(stem + '/' + label + '.sv', driver)
                Path(work, label + '.sv').write_text(driver, encoding='utf-8')
                snapshot = 'rtla_property_' + label
                stages = [(paths['xvlog'], '--sv', 'candidate.sv', label + '.sv'),
                          (paths['xelab'], 'rtla_property_driver', '-s', snapshot),
                          (paths['xsim'], snapshot, '-runall')]
                for index, command in enumerate(stages):
                    answer = execute(command, label + '_' + str(index))
                    if answer.rc != 0 or answer.status != 'ok':
                        return None, answer.status
                try:
                    return parse_events(answer.output, current, marker), None
                except ValueError as exc:
                    return None, str(exc)

            measured, error = simulate(suite, 'search')
            if measured is None:
                status = 'timeout' if error == 'timeout' else 'unavailable' if error == 'unavailable' else 'error'
                return result(status, 'Vivado 性质仿真未得到完整事件：' + str(error), classification='simulation_incomplete')
            details.update(measured, version=suite['version'], assumptions=suite['assumptions'],
                           startup=suite['startup'], stimulus_cases=len(suite['cases']))
            # Repeat the failing case with the same reset and the shortest observed
            # prefix. An incomplete run can never authorize repair.
            for identifier, record in measured['properties'].items():
                if record['classification'] != 'observed_counterexample':
                    continue
                case = next(c for c in suite['cases'] if c['id'] == record['first_failure_case'])
                replay_suite = {**suite, 'cases': [{**case,
                    'inputs': case['inputs'][:record['first_failure_step'] + 1]}]}
                replayed, replay_error = simulate(replay_suite, 'replay_' + identifier)
                if (replayed is not None and replayed['properties'][identifier]['classification'] == 'observed_counterexample' and
                        replayed['properties'][identifier]['first_failure_step'] == record['first_failure_step'] and
                        replayed['properties'][identifier]['actual_sample'] == record['actual_sample']):
                    record.update(classification='replayed_counterexample', replayed=True,
                                  replay_simulator='Vivado xsim')
                else:
                    record.update(classification='counterexample_unreplayed', replay_reason=replay_error or 'trace changed')
            passed = [p for p, r in measured['properties'].items() if r['classification'] == 'simulation_checked']
            failed = [p for p, r in measured['properties'].items() if r['classification'] == 'replayed_counterexample']
            details.update(passed_property_ids=passed, failed_property_ids=failed)
            ctx.artifacts.write_json(stem + '/result.json', details)
            if failed:
                return result('failed', 'Vivado 已复现性质反例：' + ', '.join(failed), classification='replayed_counterexample')
            if len(passed) == len(suite['properties']) and measured['unknown_assumption_samples'] == 0:
                return result('passed', '已有有限激励中的性质检查通过；不代表完整正确', classification='simulation_checked')
            return result('skipped', '部分性质未触发、输出未知或反例未复现', classification='insufficient_simulation_evidence')


        finally:
            temporary.cleanup()
