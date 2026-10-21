"""Restricted behavior expressions and a fixed, managed xsim driver.

Generated data never becomes Python or arbitrary testbench source. Expressions
carry explicit widths; sequential updates read one old-state snapshot. Unknown
values remain unknown until an explicit transition makes them known.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile
import time

from agent.core.model import _thaw
from agent.core.process import ProcessRequest
from agent.core.tool import CheckOutcome


class SuiteError(ValueError):
    pass


_NAME = re.compile(r'^[A-Za-z_][A-Za-z0-9_$]*$')
_OPS = {'add': 2, 'sub': 2, 'mul': 2, 'and': 2, 'or': 2, 'xor': 2,
        'shl': 2, 'shr': 2, 'asr': 2, 'eq': 2, 'ne': 2, 'lt': 2,
        'le': 2, 'gt': 2, 'ge': 2, 'land': 2, 'lor': 2, 'not': 1,
        'bitnot': 1, 'neg': 1, 'ite': 3, 'slice': 1, 'concat': None,
        'reduce_and': 1, 'reduce_or': 1, 'reduce_xor': 1}


def _integer(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        raise SuiteError(f'{label} must be an integer in {low}..{high}')
    return value


def _name(value):
    if not isinstance(value, str) or not _NAME.fullmatch(value) or value.startswith('rtla_'):
        raise SuiteError('invalid or reserved signal name')
    return value


def suite_hash(suite):
    body = json.dumps(_thaw(suite), sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(body.encode()).hexdigest()


def validate_revision(previous, revised, revision):
    """Retain every old stimulus and permit only named behavior-expression edits."""
    old, new = validate_suite(previous), validate_suite(revised)
    if (revision.get('kind') != 'specification_revision' or
            revision.get('origin') != 'code_aware_diagnosis' or
            set(revision) != {'kind', 'origin', 'quote', 'target', 'names'}):
        raise SuiteError('checker revision must use the fixed specification-only request')
    target, names = revision.get('target'), revision.get('names')
    if target not in ('outputs', 'state_next', 'async_reset_values') or not isinstance(names, list) or not names:
        raise SuiteError('checker revision target or names are invalid')
    if any(not isinstance(name, str) for name in names) or len(set(names)) != len(names):
        raise SuiteError('checker revision names must be unique strings')
    allowed = old['outputs'] if target == 'outputs' else old['state']
    if not set(names).issubset(allowed):
        raise SuiteError('checker revision must name existing model signals')
    ports = lambda suite: {n: (p['direction'], p['width'], p.get('signed', False))
                           for n, p in suite['ports'].items()}
    if (ports(old) != ports(new) or old.get('clock') != new.get('clock') or
            old.get('clocks') != new.get('clocks') or old['mode'] != new['mode']):
        raise SuiteError('checker revision cannot change ports, clock or mode')
    steps = lambda case: [{'inputs': s['inputs'], 'edge': s.get('edge', True),
                          'sample': s.get('sample', True), 'edges': s.get('edges')} for s in case['steps']]
    new_cases = {case['id']: case for case in new['cases']}
    for case in old['cases']:
        if case['id'] not in new_cases or steps(case) != steps(new_cases[case['id']]):
            raise SuiteError('checker revision must preserve every old case, input, edge and sample')
    old_requirements = {r['id']: r['quote'] for r in old['requirements']}
    new_requirements = {r['id']: r['quote'] for r in new['requirements']}
    if any(new_requirements.get(name) != quote for name, quote in old_requirements.items()):
        raise SuiteError('checker revision cannot remove or alter existing requirement quotations')
    if set(old['state']) != set(new['state']):
        raise SuiteError('checker revision cannot add or remove model state')
    if any(old.get(key, {}) != new.get(key, {}) for key in ('output_valid', 'output_masks')):
        raise SuiteError('checker revision cannot change output validity or masks')
    if set(old['outputs']) != set(new['outputs']):
        raise SuiteError('checker revision cannot change the checked output set')
    changes = []
    for name in old['outputs']:
        if old['outputs'][name] != new['outputs'][name]:
            if target != 'outputs' or name not in names:
                raise SuiteError('checker revision changed an unapproved output expression')
            changes.append({'path': f'outputs.{name}', 'old': old['outputs'][name], 'new': new['outputs'][name]})
    for name, register in old['state'].items():
        replacement = new['state'][name]
        if {k: v for k, v in register.items() if k != 'next'} != {k: v for k, v in replacement.items() if k != 'next'}:
            raise SuiteError('checker revision cannot change state metadata or clock binding')
        if (register['width'], register.get('signed', False)) != (replacement['width'], replacement.get('signed', False)):
            raise SuiteError('checker revision cannot change state widths or signedness')
        if register['next'] != replacement['next']:
            if target != 'state_next' or name not in names:
                raise SuiteError('checker revision changed an unapproved state transition')
            changes.append({'path': f'state.{name}.next', 'old': register['next'], 'new': replacement['next']})
    old_reset, new_reset = old.get('async_reset'), new.get('async_reset')
    if bool(old_reset) != bool(new_reset):
        raise SuiteError('checker revision cannot change the reset sampling contract')
    if old_reset:
        if (old_reset['port'], old_reset['active']) != (new_reset['port'], new_reset['active']):
            raise SuiteError('checker revision cannot change reset binding or polarity')
        for name in old_reset['values']:
            if old_reset['values'][name] != new_reset['values'][name]:
                if target != 'async_reset_values' or name not in names:
                    raise SuiteError('checker revision changed an unapproved reset value')
                changes.append({'path': f'async_reset.values.{name}', 'old': old_reset['values'][name],
                                'new': new_reset['values'][name]})
    old_resets, new_resets = old.get('async_resets', []), new.get('async_resets', [])
    if len(old_resets) != len(new_resets):
        raise SuiteError('checker revision cannot change explicit reset contracts')
    for index, (before, after) in enumerate(zip(old_resets, new_resets)):
        if (before['port'], before['active'], set(before['values'])) != (after['port'], after['active'], set(after['values'])):
            raise SuiteError('checker revision cannot change reset binding, polarity or state subset')
        for name in before['values']:
            if before['values'][name] != after['values'][name]:
                if target != 'async_reset_values' or name not in names:
                    raise SuiteError('checker revision changed an unapproved reset value')
                changes.append({'path': f'async_resets.{index}.values.{name}',
                                'old': before['values'][name], 'new': after['values'][name]})
    if not changes:
        raise SuiteError('checker revision made no approved behavior change')
    # A permitted state expression must not indirectly disable a previously
    # required comparison through an unchanged guard or mask expression.
    new_rows = {(row['case_id'], row['step']): row for row in expected_traces(new)}
    for before in expected_traces(old):
        if not before['sample']:
            continue
        after = new_rows[before['case_id'], before['step']]
        for name in before['expected']:
            full = (1 << old['ports'][name]['width']) - 1
            if (before['valid'][name] is True and before['mask_known'][name] == full and before['masks'][name] and
                    (after['valid'][name] is not True or after['mask_known'][name] != full or
                     before['masks'][name] & ~after['masks'][name])):
                raise SuiteError('checker revision cannot weaken prior effective output validity or masks')
    for change in changes:
        change['old_suite_hash'] = suite_hash(old)
        change['new_suite_hash'] = suite_hash(new)
    return changes


def validate_suite(suite, *, task_text=None):
    """Return plain validated data. No model score is treated as validation."""
    value = _thaw(suite)
    if not isinstance(value, dict) or value.get('schema_version') != 1:
        raise SuiteError('schema_version must be 1')
    if value.get('mode') not in ('behavior', 'stimulus'):
        raise SuiteError('mode must be behavior or stimulus')
    ports = value.get('ports')
    if not isinstance(ports, dict) or not 1 <= len(ports) <= 64:
        raise SuiteError('ports must contain 1..64 entries')
    for name, port in ports.items():
        _name(name)
        if not isinstance(port, dict) or port.get('direction') not in ('input', 'output'):
            raise SuiteError('each port needs an input/output direction')
        _integer(port.get('width'), 1, 256, 'port width')
        if type(port.get('signed', False)) is not bool:
            raise SuiteError('signed must be boolean')
    inputs = {n for n, p in ports.items() if p['direction'] == 'input'}
    outputs = {n for n, p in ports.items() if p['direction'] == 'output'}
    if not outputs:
        raise SuiteError('at least one output is required')
    clock = value.get('clock')
    if clock is not None:
        if not isinstance(clock, dict):
            raise SuiteError('clock: legacy single-clock format requires an object with port and edge')
        if not isinstance(clock.get('port'), str) or clock['port'] not in inputs or ports[clock['port']]['width'] != 1:
            raise SuiteError('clock.port: must name a one-bit input')
        if clock.get('edge') not in ('posedge', 'negedge'):
            raise SuiteError('clock.edge: must be posedge or negedge')
    clocks = value.get('clocks')
    if clocks is not None:
        if clock is not None:
            raise SuiteError('clocks: cannot coexist with legacy clock; select one clock format')
        if not isinstance(clocks, dict) or not 1 <= len(clocks) <= 8:
            raise SuiteError('clocks: explicit format requires a map of 1..8 input names to {edge: posedge|negedge}, not a list')
        for name, definition in clocks.items():
            if name not in inputs or ports[name]['width'] != 1:
                raise SuiteError(f'clocks.{name}: key must name a one-bit input')
            if not isinstance(definition, dict) or set(definition) != {'edge'}:
                raise SuiteError(f'clocks.{name}: requires exactly the edge field; the input name is the map key')
            if definition['edge'] not in ('posedge', 'negedge'):
                raise SuiteError(f'clocks.{name}.edge: must be posedge or negedge')
    state = value.setdefault('state', {})
    if not isinstance(state, dict) or len(state) > 64 or (state and clock is None and clocks is None):
        raise SuiteError('state requires clocks and at most 64 registers')
    for name, register in state.items():
        _name(name)
        if name in ports or not isinstance(register, dict):
            raise SuiteError('state names must be separate from ports')
        if clocks is not None and (not isinstance(register.get('clock'), str) or register['clock'] not in clocks):
            raise SuiteError(f'state.{name}.clock: explicit clocks requires a key from clocks')
        if clocks is None and 'clock' in register:
            raise SuiteError(f'state.{name}.clock: register binding requires explicit clocks, not legacy clock')
        _integer(register.get('width'), 1, 256, 'state width')
        if 'initial' in register:
            raise SuiteError('state initialization is unsupported; drive an explicit reset')
        if type(register.get('signed', False)) is not bool:
            raise SuiteError('state signed must be boolean')
    symbols = {n: p['width'] for n, p in ports.items() if n in inputs}
    symbols.update({n: p['width'] for n, p in state.items()})
    diagnostics = _ExpressionDiagnostics()
    for name, register in state.items():
        _validate_expr(register.get('next'), symbols, path=f'state.{name}.next', _diagnostics=diagnostics)
    asynchronous = value.get('async_reset')
    if asynchronous is not None:
        if not clock:
            raise SuiteError('async_reset: requires legacy clock; explicit clocks uses async_resets, a list of reset objects')
        if not isinstance(asynchronous, dict):
            raise SuiteError('async_reset: requires an object with port, active, and values')
        if (not isinstance(asynchronous.get('port'), str) or asynchronous['port'] not in inputs or
                ports[asynchronous['port']]['width'] != 1):
            raise SuiteError('async_reset.port: must name a one-bit input')
        if type(asynchronous.get('active')) is not int or asynchronous['active'] not in (0, 1):
            raise SuiteError('async_reset.active: must be integer 0 or 1')
        if (not isinstance(asynchronous.get('values'), dict) or set(asynchronous['values']) != set(state) or
                (not state and value['mode'] != 'stimulus')):
            raise SuiteError('async_reset.values: must map every state register to its reset expression; empty is only allowed in stimulus mode')
        for name, expression in asynchronous['values'].items():
            _validate_expr(expression, symbols, path=f'async_reset.values.{name}', _diagnostics=diagnostics)
    resets = value.get('async_resets')
    if resets is not None:
        if asynchronous is not None:
            raise SuiteError('async_resets: cannot coexist with legacy async_reset')
        if not clocks:
            raise SuiteError('async_resets: requires explicit clocks; legacy clock uses a single async_reset object')
        if not isinstance(resets, list) or not 1 <= len(resets) <= 8:
            raise SuiteError('async_resets: requires a list of 1..8 objects with port, active, and values')
        reset_states = set()
        for index, reset in enumerate(resets):
            path = f'async_resets[{index}]'
            if not isinstance(reset, dict) or set(reset) != {'port', 'active', 'values'}:
                raise SuiteError(path + ': requires exactly port, active, and values fields')
            if (not isinstance(reset['port'], str) or reset['port'] not in inputs or
                    reset['port'] in clocks or ports[reset['port']]['width'] != 1):
                raise SuiteError(path + '.port: must name a one-bit non-clock input')
            if type(reset['active']) is not int or reset['active'] not in (0, 1):
                raise SuiteError(path + '.active: must be integer 0 or 1')
            if (not isinstance(reset['values'], dict) or not reset['values'] or
                    not set(reset['values']).issubset(state) or reset_states.intersection(reset['values'])):
                raise SuiteError(path + '.values: must map a nonempty state subset, disjoint from earlier resets')
            reset_states.update(reset['values'])
            for name, expression in reset['values'].items():
                _validate_expr(expression, symbols, path=f'{path}.values.{name}', _diagnostics=diagnostics)
    expressions = value.setdefault('outputs', {})
    if not isinstance(expressions, dict) or not set(expressions).issubset(outputs):
        raise SuiteError('outputs: must map declared output names to expressions')
    if value['mode'] == 'behavior' and set(expressions) != outputs:
        raise SuiteError('outputs: behavior mode must define every output exactly once')
    for name, expression in expressions.items():
        _validate_expr(expression, symbols, path=f'outputs.{name}', _diagnostics=diagnostics)
    for key in ('output_valid', 'output_masks'):
        mapping = value.get(key, {})
        if not isinstance(mapping, dict) or not set(mapping).issubset(outputs):
            raise SuiteError(key + ' must map output names to expressions')
        for name, expression in mapping.items():
            width = _validate_expr(expression, symbols, path=f'{key}.{name}', _diagnostics=diagnostics)
            expected_width = 1 if key == 'output_valid' else ports[name]['width']
            if width is not None and width != expected_width:
                diagnostics.add(f'{key}.{name}.width', f'expression width must be {expected_width} for this output contract')
    diagnostics.raise_if_any()
    if task_text is not None:
        from agent.core.specification import normalize_requirements
        try:
            value['requirements'] = normalize_requirements(value.get('requirements'), task_text)
        except ValueError as error:
            raise SuiteError(str(error)) from error
    requirements = value.get('requirements')
    if not isinstance(requirements, list) or not 1 <= len(requirements) <= 64:
        raise SuiteError('requirements must contain 1..64 source quotations')
    ids = set()
    for requirement in requirements:
        if (not isinstance(requirement, dict) or not isinstance(requirement.get('id'), str) or
                not requirement['id'] or requirement['id'] in ids or
                not isinstance(requirement.get('quote'), str) or not requirement['quote'].strip()):
            raise SuiteError('requirements need unique ids and nonempty quotations')
        ids.add(requirement['id'])
    cases = value.get('cases')
    if not isinstance(cases, list) or not 1 <= len(cases) <= 32:
        raise SuiteError('cases must contain 1..32 entries')
    case_ids, events, samples = set(), 0, 0
    driven = inputs - set(clocks or {}) - ({clock['port']} if clock else set())
    for case_index, case in enumerate(cases):
        if (not isinstance(case, dict) or not isinstance(case.get('id'), str) or
                not case['id'] or len(case['id']) > 80 or case['id'] in case_ids):
            raise SuiteError('case ids must be unique nonempty strings')
        case_ids.add(case['id'])
        steps = case.get('steps')
        if not isinstance(steps, list) or not 1 <= len(steps) <= 512:
            raise SuiteError('case needs 1..512 steps')
        for step_index, step in enumerate(steps):
            path = f'cases[{case_index}].steps[{step_index}]'
            if not isinstance(step, dict) or not isinstance(step.get('inputs'), dict) or set(step['inputs']) != driven:
                raise SuiteError('each step must drive every non-clock input exactly once')
            if type(step.get('sample', True)) is not bool:
                raise SuiteError('sample must be boolean')
            if clocks is not None:
                edges = step.get('edges')
                if ('edge' in step or not isinstance(edges, list) or
                        any(not isinstance(n, str) or n not in clocks for n in edges) or len(set(edges)) != len(edges)):
                    raise SuiteError(path + '.edges: explicit clocks requires a list of unique clock names (empty for no edges), and no legacy edge field')
            elif 'edges' in step:
                raise SuiteError(path + '.edges: requires explicit clocks; legacy clock uses boolean edge')
            if type(step.get('edge', True)) is not bool:
                raise SuiteError(path + '.edge: legacy clock edge must be boolean')
            for name, number in step['inputs'].items():
                width = ports[name]['width']
                _integer(number, -(1 << (width - 1)), (1 << width) - 1, 'input value')
            events += 1
            samples += step.get('sample', True)
    if events > 4096 or not samples:
        raise SuiteError('suite needs sampled events and at most 4096 total events')
    return value


class _ExpressionDiagnostics:
    """Collect independent expression errors once, with bounded feedback size."""
    limit = 8

    def __init__(self):
        self.errors = []

    @property
    def full(self):
        return len(self.errors) >= self.limit

    def add(self, path, message):
        if not self.full:
            self.errors.append(f'{path}: {message}')

    def raise_if_any(self):
        if self.errors:
            suffix = f'\ndiagnostic limit {self.limit} reached; further errors may exist' if self.full else ''
            raise SuiteError('\n'.join(self.errors) + suffix)


def _validate_expr(expr, symbols, depth=0, *, path='expression', _diagnostics=None):
    """Validate each node once; no width is inferred for an invalid expression."""
    diagnostics = _diagnostics if _diagnostics is not None else _ExpressionDiagnostics()
    width = _check_expr(expr, symbols, depth, path, diagnostics)
    if _diagnostics is None:
        diagnostics.raise_if_any()
    return width


def _check_expr(expr, symbols, depth, path, diagnostics):
    if diagnostics.full:
        return None
    before = len(diagnostics.errors)
    if depth > 32 or not isinstance(expr, dict):
        diagnostics.add(path, 'expression must be an object with depth at most 32')
        return None
    if 'ref' in expr:
        if set(expr) != {'ref'}:
            diagnostics.add(path, 'reference only accepts ref')
        if not isinstance(expr['ref'], str) or expr['ref'] not in symbols:
            diagnostics.add(path + '.ref', 'unknown expression reference; must name an input or state register')
        return symbols[expr['ref']] if len(diagnostics.errors) == before else None
    width = expr.get('width')
    if type(width) is not int or not 1 <= width <= 256:
        diagnostics.add(path + '.width', 'expression width must be an integer in 1..256')
        width = None
    if 'const' in expr:
        if set(expr) - {'const', 'width'}:
            diagnostics.add(path, 'constant only accepts const and width')
        if type(expr['const']) is not int:
            diagnostics.add(path + '.const', 'constant must be an integer')
        elif width is not None and not -(1 << (width - 1)) <= expr['const'] <= (1 << width) - 1:
            diagnostics.add(path + '.const', f'constant must be an integer in {-(1 << (width - 1))}..{(1 << width) - 1}')
        return width if len(diagnostics.errors) == before else None
    op, args = expr.get('op'), expr.get('args')
    if not isinstance(op, str) or op not in _OPS:
        diagnostics.add(path + '.op', 'unsupported expression operator')
        return None
    if not isinstance(args, list):
        diagnostics.add(path + '.args', 'expression arguments must be a list')
        return None
    arity = _OPS[op]
    if (len(args) != arity if arity is not None else not 1 <= len(args) <= 32):
        expected = str(arity) if arity is not None else '1..32'
        diagnostics.add(path + '.args', f'incorrect expression argument count; {op} requires {expected}')
        return None
    if set(expr) - {'op', 'args', 'width', 'signed', 'lsb'}:
        diagnostics.add(path, 'unknown expression key')
    if type(expr.get('signed', False)) is not bool:
        diagnostics.add(path + '.signed', 'expression signed must be boolean')
    elif expr.get('signed', False) and op not in ('add', 'sub', 'mul', 'and', 'or', 'xor',
                                                'eq', 'ne', 'lt', 'le', 'gt', 'ge', 'shl', 'asr', 'bitnot', 'neg'):
        diagnostics.add(path + '.signed', 'signed is unsupported for this operator')
    widths = []
    for index, arg in enumerate(args):
        if diagnostics.full:
            return None
        widths.append(_check_expr(arg, symbols, depth + 1, f'{path}.args[{index}]', diagnostics))
    if op == 'slice':
        lsb = expr.get('lsb')
        if type(lsb) is not int or not 0 <= lsb <= 255:
            diagnostics.add(path + '.lsb', 'slice lsb must be an integer in 0..255')
        elif width is not None and widths[0] is not None and lsb + width > widths[0]:
            diagnostics.add(path + '.lsb', 'slice exceeds input width')
    elif 'lsb' in expr:
        diagnostics.add(path + '.lsb', 'lsb only belongs to slice')
    if op == 'concat' and width is not None and all(w is not None for w in widths) and sum(widths) != width:
        diagnostics.add(path + '.width', 'concat width differs from argument widths')
    if op in ('eq', 'ne', 'lt', 'le', 'gt', 'ge', 'land', 'lor', 'not', 'reduce_and', 'reduce_or', 'reduce_xor') and width is not None and width != 1:
        diagnostics.add(path + '.width', 'boolean expression width must be one')
    return width if len(diagnostics.errors) == before else None


def evaluate(expr, values, widths):
    """Return (unsigned bits or None, width), without evaluating source code."""
    if 'ref' in expr:
        return values[expr['ref']], widths[expr['ref']]
    width = expr['width']
    mask = (1 << width) - 1
    if 'const' in expr:
        return expr['const'] & mask, width
    op = expr['op']
    args = [evaluate(arg, values, widths) for arg in expr['args']]
    numbers = [v for v, _ in args]
    if op == 'ite':
        if numbers[0] is None:
            result = numbers[1] if numbers[1] == numbers[2] else None
        else:
            result = numbers[1] if numbers[0] else numbers[2]
        return (result & mask if result is not None else None), width
    if any(number is None for number in numbers):
        return None, width
    if expr.get('signed', False):
        numbers = [v - (1 << w) if v & (1 << (w - 1)) and (op not in ('shl', 'asr') or i == 0) else v
                   for i, (v, w) in enumerate(args)]
    a = numbers[0]
    b = numbers[1] if len(numbers) > 1 else 0
    if op == 'add': result = a + b
    elif op == 'sub': result = a - b
    elif op == 'mul': result = a * b
    elif op == 'and': result = a & b
    elif op == 'or': result = a | b
    elif op == 'xor': result = a ^ b
    elif op == 'shl': result = a << min(b, 512)
    elif op in ('shr', 'asr'): result = a >> min(max(b, 0), 512)
    elif op == 'eq': result = a == b
    elif op == 'ne': result = a != b
    elif op == 'lt': result = a < b
    elif op == 'le': result = a <= b
    elif op == 'gt': result = a > b
    elif op == 'ge': result = a >= b
    elif op == 'land': result = bool(a) and bool(b)
    elif op == 'lor': result = bool(a) or bool(b)
    elif op == 'not': result = not a
    elif op == 'bitnot': result = ~a
    elif op == 'neg': result = -a
    elif op == 'slice': result = a >> expr['lsb']
    elif op == 'reduce_and': result = a == (1 << args[0][1]) - 1
    elif op == 'reduce_or': result = bool(a)
    elif op == 'reduce_xor': result = a.bit_count() % 2
    elif op == 'concat':
        result = 0
        for number, bits in args:
            result = (result << bits) | number
    else: raise SuiteError('unsupported expression operator')
    return int(result) & mask, width


def _resize(bits, width, signed=False):
    value, known, old_width = bits
    mask = (1 << width) - 1
    if width > old_width:
        extra = mask ^ ((1 << old_width) - 1)
        if not signed:
            known |= extra
        elif known & (1 << (old_width - 1)):
            known |= extra
            if value & (1 << (old_width - 1)):
                value |= extra
    return value & mask, known & mask, width


def _evaluate_bits(expr, values, widths):
    """Conservative bit knowledge; never invent an initial or arithmetic bit."""
    if 'ref' in expr:
        return values[expr['ref']]
    width = expr['width']
    full = (1 << width) - 1
    if 'const' in expr:
        return expr['const'] & full, full, width
    args = [_evaluate_bits(arg, values, widths) for arg in expr['args']]
    op = expr['op']
    if op == 'slice':
        a, known, _ = args[0]
        return (a >> expr['lsb']) & full, (known >> expr['lsb']) & full, width
    if op == 'concat':
        value = known = 0
        for a, k, w in args:
            value, known = (value << w) | a, (known << w) | k
        return value & full, known & full, width
    if op == 'ite':
        c, ck, cw = args[0]
        a = _resize(args[1], width)
        b = _resize(args[2], width)
        if c & ck:
            return a
        if ck == (1 << cw) - 1:
            return b
        known = a[1] & b[1] & ~(a[0] ^ b[0]) & full
        return a[0] & known, known, width
    if op in ('and', 'or', 'xor', 'bitnot'):
        expanded = [_resize(a, width, expr.get('signed', False)) for a in args]
        a, ak, _ = expanded[0]
        if op == 'bitnot':
            return (~a) & ak & full, ak, width
        b, bk, _ = expanded[1]
        if op == 'and':
            known = (ak & bk) | (ak & ~a) | (bk & ~b)
            value = a & b
        elif op == 'or':
            known = (ak & bk) | (ak & a) | (bk & b)
            value = a | b
        else:
            known, value = ak & bk, a ^ b
        return value & known & full, known & full, width
    if all(k == (1 << w) - 1 for _, k, w in args):
        concrete = {**expr, 'args': [{'const': a, 'width': w} for a, _, w in args]}
        result, _ = evaluate(concrete, {}, {})
        return result, full, width
    return 0, 0, width


def _clocks(suite):
    if suite.get('clock'):
        return {suite['clock']['port']: {'edge': suite['clock']['edge']}}
    return suite.get('clocks', {})


def _edges(suite, step):
    if suite.get('clocks'):
        return step['edges']
    return list(_clocks(suite)) if step.get('edge', True) else []


def expected_traces(suite):
    suite = validate_suite(suite)
    ports, registers = suite['ports'], suite['state']
    widths = {n: p['width'] for n, p in ports.items()}
    widths.update({n: p['width'] for n, p in registers.items()})
    clocks = _clocks(suite)
    resets = suite.get('async_resets', [suite['async_reset']] if suite.get('async_reset') else [])
    result = []
    for case in suite['cases']:
        state = {n: (0, 0, r['width']) for n, r in registers.items()}
        previous_inputs = {}
        for index, step in enumerate(case['steps']):
            values = {n: (v & ((1 << widths[n]) - 1), (1 << widths[n]) - 1, widths[n])
                      for n, v in step['inputs'].items()}
            edges = _edges(suite, step)
            for name, clock in clocks.items():
                values[name] = (int(clock['edge'] != 'posedge'), 1, 1)
            values.update(state)
            reset_values, asserted_values = {}, {}
            for reset in resets:
                if values[reset['port']][0] == reset['active']:
                    reset_values.update(reset['values'])
                    if previous_inputs.get(reset['port']) != reset['active']:
                        asserted_values.update(reset['values'])
            # Reset is driven before edges and settles before other domains sample it.
            state.update({n: _resize(_evaluate_bits(e, values, widths), widths[n])
                          for n, e in asserted_values.items()})
            values.update(state)
            for name in edges:
                values[name] = (int(clocks[name]['edge'] == 'posedge'), 1, 1)
            # Every triggered domain reads this one snapshot, including cross-domain reads.
            updates = {n: _resize(_evaluate_bits(reset_values.get(n, r['next']), values, widths), r['width'])
                       for n, r in registers.items()
                       if r.get('clock', next(iter(clocks), None)) in edges}
            state.update(updates)
            previous_inputs = dict(step['inputs'])
            values.update(state)
            expected, expected_known, valid, masks, mask_known, partial = {}, {}, {}, {}, {}, {}
            for n, e in suite['outputs'].items():
                full = (1 << ports[n]['width']) - 1
                v, known, _ = _resize(_evaluate_bits(e, values, widths), ports[n]['width'])
                expected[n], expected_known[n], partial[n] = v if known == full else None, known, v
                # Partial values remain available separately; None retains the old public convention.
                guard = suite.get('output_valid', {}).get(n, {'const': 1, 'width': 1})
                g, gk, _ = _evaluate_bits(guard, values, widths)
                valid[n] = bool(g) if gk else None
                mask_expr = suite.get('output_masks', {}).get(n, {'const': full, 'width': ports[n]['width']})
                masks[n], mask_known[n], _ = _evaluate_bits(mask_expr, values, widths)
            result.append({'case_id': case['id'], 'step': index, 'inputs': dict(step['inputs']),
                           'sample': step.get('sample', True), 'edge': step.get('edge', True),
                           'edges': edges, 'expected': expected, 'expected_bits': partial,
                           'expected_known': expected_known, 'valid': valid,
                           'masks': masks, 'mask_known': mask_known})
    return result


_COUNT_KEYS = ('sampled_events', 'comparable_samples', 'comparable_values', 'comparable_bits',
               'unknown_expected', 'guard_unknown', 'mask_unknown', 'excluded_values', 'excluded_bits')


def _expectation_counts(row, suite):
    counts = dict.fromkeys(_COUNT_KEYS, 0)
    if not row['sample']:
        return counts
    counts['sampled_events'] = 1
    for name in row['expected']:
        full = (1 << suite['ports'][name]['width']) - 1
        if row['valid'][name] is False:
            counts['excluded_values'] += 1
            counts['excluded_bits'] += full.bit_count()
            continue
        if row['valid'][name] is None:
            counts['guard_unknown'] += 1
            continue
        if row['mask_known'][name] != full:
            counts['mask_unknown'] += 1
            continue
        mask = row['masks'][name]
        counts['excluded_bits'] += (full ^ mask).bit_count()
        if not mask:
            counts['excluded_values'] += 1
            continue
        known = row['expected_known'][name] & mask
        counts['comparable_bits'] += known.bit_count()
        counts['comparable_values'] += bool(known)
        counts['unknown_expected'] += known != mask
    counts['comparable_samples'] = int(bool(counts['comparable_bits']))
    return counts


def analyze_expectations(suite):
    """Preflight only: counts model knowledge, without RTL or simulator outputs."""
    suite = validate_suite(suite)
    total = dict.fromkeys(_COUNT_KEYS, 0)
    cases = {c['id']: dict(case_id=c['id'], **dict.fromkeys(_COUNT_KEYS, 0)) for c in suite['cases']}
    for row in expected_traces(suite):
        counts = _expectation_counts(row, suite)
        for key, count in counts.items():
            total[key] += count
            cases[row['case_id']][key] += count
    return {**total, 'per_case': list(cases.values()), 'suite_hash': suite_hash(suite)}


def coverage_summary(suites):
    """Report stimulus diversity; exhaustiveness applies only to small combinational domains."""
    suites = [validate_suite(s) for s in suites]
    stimuli, inputs, complete_inputs = set(), set(), set()
    input_bits = None
    compatible = bool(suites)
    signature = None
    for suite in suites:
        ports = suite['ports']
        sig = {n: (p['direction'], p['width'], p.get('signed', False)) for n, p in ports.items()}
        compatible &= signature is None or signature == sig
        signature = sig
        bits = sum(p['width'] for p in ports.values() if p['direction'] == 'input')
        input_bits = bits if input_bits is None else input_bits
        compatible &= (not suite['state'] and not _clocks(suite) and suite['mode'] == 'behavior' and bits <= 12)
        for case in suite['cases']:
            steps = [{'inputs': {n: v & ((1 << ports[n]['width']) - 1) for n, v in step['inputs'].items()},
                      'edges': _edges(suite, step), 'sample': step.get('sample', True)} for step in case['steps']]
            stimuli.add(json.dumps({'clocks': _clocks(suite), 'steps': steps}, sort_keys=True))
        for row in expected_traces(suite):
            key = json.dumps({n: v & ((1 << ports[n]['width']) - 1) for n, v in row['inputs'].items()}, sort_keys=True)
            inputs.add(key)
            full = all(row['valid'][n] is True and row['masks'][n] == (1 << ports[n]['width']) - 1 and
                       row['mask_known'][n] == (1 << ports[n]['width']) - 1 and
                       row['expected_known'][n] == (1 << ports[n]['width']) - 1
                       for n, p in ports.items() if p['direction'] == 'output' and n in row['expected'])
            if row['sample'] and full and suite['mode'] == 'behavior':
                complete_inputs.add(key)
    domain = (1 << input_bits) if compatible else None
    return {'unique_stimuli': len(stimuli), 'unique_inputs': len(inputs),
            'fully_comparable_inputs': len(complete_inputs), 'input_domain_size': domain,
            'stateless_exhaustive': bool(compatible and len(complete_inputs) == domain)}


def build_testbench(suite, top, marker):
    if not _NAME.fullmatch(top) or not re.fullmatch(r'[a-f0-9]{16}', marker):
        raise SuiteError('invalid top or trace marker')
    suite = validate_suite(suite)
    ports, clocks = dict(sorted(suite['ports'].items())), dict(sorted(_clocks(suite).items()))
    outputs = sorted(n for n, p in ports.items() if p['direction'] == 'output')
    lines = ['`timescale 1ns/1ps', 'module rtla_tb;']
    for ci, case in enumerate(suite['cases']):
        for name, port in ports.items():
            kind = 'reg' if port['direction'] == 'input' else 'wire'
            lines.append(f'{kind} [{port["width"] - 1}:0] rtla_c{ci}_{name};')
        lines.append(f'{top} rtla_dut{ci} (' + ', '.join(f'.{n}(rtla_c{ci}_{n})' for n in ports) + ');')
        lines.append('initial begin')
        for name, clock in clocks.items():
            lines.append(f'rtla_c{ci}_{name} = 1\'b{int(clock["edge"] != "posedge")};')
        for si, step in enumerate(case['steps']):
            lines.append('#5;')
            for name, number in sorted(step['inputs'].items()):
                bits = ports[name]['width']
                lines.append(f'rtla_c{ci}_{name} = {bits}\'h{number & ((1 << bits) - 1):x};')
            if clocks:
                lines.append('#5;')
                for name in sorted(_edges(suite, step)):
                    # Nonblocking assignments put simultaneous clocks in one NBA update.
                    lines.append(f'rtla_c{ci}_{name} <= 1\'b{int(clocks[name]["edge"] == "posedge")};')
            lines.append('#1;')
            fmt = f'RTLA_{marker}|{ci}|{si}|' + '|'.join('b:%b' for _ in outputs)
            lines.append(f'$display("{fmt}", ' + ', '.join(f'rtla_c{ci}_{n}' for n in outputs) + ');')
            lines.append('#4;')
            for name, clock in clocks.items():
                lines.append(f'rtla_c{ci}_{name} <= 1\'b{int(clock["edge"] != "posedge")};')
        lines.append('end')
    duration = max(len(c['steps']) for c in suite['cases']) * 15 + 10
    lines += [f'initial begin #{duration}; $finish; end', 'endmodule']
    return '\n'.join(lines) + '\n'


def _parse_value(token, width):
    binary = token.startswith('b:')
    digits = token[2:] if binary else token
    if not re.fullmatch(r'[01xXzZ]+' if binary else r'[0-9a-fA-FxXzZ]+', digits):
        raise SuiteError('invalid simulation value')
    value = known = 0
    stride = 1 if binary else 4
    for digit in digits:
        value <<= stride
        known <<= stride
        if digit not in 'xXzZ':
            value |= int(digit, 2 if binary else 16)
            known |= (1 << stride) - 1
    full = (1 << width) - 1
    if value > full:
        raise SuiteError('simulation value exceeds declared width')
    if len(digits) * stride < width:
        # Legacy hexadecimal traces omit leading zeroes; those bits are known zero.
        known |= full ^ ((1 << (len(digits) * stride)) - 1)
    return value & full, known & full


def parse_traces(output, suite, marker, *, compare_expected=True):
    suite = validate_suite(suite)
    outputs = sorted(n for n, p in suite['ports'].items() if p['direction'] == 'output')
    rows = {}
    prefix = f'RTLA_{marker}|'
    for line in output.splitlines():
        if not line.startswith(prefix):
            continue
        parts = line[len(prefix):].strip().split('|')
        if len(parts) != len(outputs) + 2 or not all(re.fullmatch(r'\d+', p) for p in parts[:2]):
            raise SuiteError('malformed simulation trace')
        ci, si = map(int, parts[:2])
        if ci >= len(suite['cases']) or si >= len(suite['cases'][ci]['steps']) or (ci, si) in rows:
            raise SuiteError('duplicate or unexpected simulation event')
        rows[ci, si] = {name: _parse_value(token, suite['ports'][name]['width'])
                        for name, token in zip(outputs, parts[2:])}
    traces, passed, failed, first = [], [], [], None
    unknown_cases, untested_cases = [], []
    compared_samples = compared_values = compared_bits = 0
    unknown_expected = unknown_actual = guard_unknown = mask_unknown = 0
    expectations = iter(expected_traces(suite))
    for ci, case in enumerate(suite['cases']):
        mismatched, uncertain, comparisons = False, False, 0
        for si, step in enumerate(case['steps']):
            expected = next(expectations)
            if (ci, si) not in rows:
                raise SuiteError('simulation event count is incomplete')
            raw = rows[ci, si]
            actual = {n: v if k == (1 << suite['ports'][n]['width']) - 1 else None for n, (v, k) in raw.items()}
            trace = {**expected, 'outputs': actual, 'expected': expected['expected'] if compare_expected else None,
                     'actual_bits': {n: v for n, (v, k) in raw.items()},
                     'actual_known': {n: k for n, (v, k) in raw.items()},
                     'unknown_outputs': [n for n, v in actual.items() if v is None],
                     'compared_bits': 0, 'compared_values': 0,
                     'unknown_expected': [], 'unknown_actual': [], 'guard_unknown': [], 'mask_unknown': []}
            traces.append(trace)
            if not step.get('sample', True):
                continue
            if not compare_expected:
                uncertain |= any(v is None for v in actual.values())
                continue
            for name in expected['expected']:
                full = (1 << suite['ports'][name]['width']) - 1
                if expected['valid'][name] is False:
                    continue
                if expected['valid'][name] is None:
                    uncertain = True
                    guard_unknown += 1
                    trace['guard_unknown'].append(name)
                    continue
                if expected['mask_known'][name] != full:
                    uncertain = True
                    mask_unknown += 1
                    trace['mask_unknown'].append(name)
                    continue
                mask = expected['masks'][name]
                if not mask:
                    continue
                exp_known = expected['expected_known'][name]
                act, act_known = raw[name]
                if mask & ~exp_known:
                    uncertain = True
                    unknown_expected += 1
                    trace['unknown_expected'].append(name)
                if mask & ~act_known:
                    uncertain = True
                    unknown_actual += 1
                    trace['unknown_actual'].append(name)
                comparable = mask & exp_known & act_known
                if not comparable:
                    continue
                comparisons += 1
                trace['compared_values'] += 1
                trace['compared_bits'] += comparable.bit_count()
                if (expected['expected_bits'][name] ^ act) & comparable:
                    mismatched = True
                    if first is None:
                        first = {**trace, 'signal': name, 'expected_value': expected['expected'][name],
                                 'actual_value': actual[name], 'comparison_mask': comparable,
                                 'expected_bits_value': expected['expected_bits'][name], 'actual_bits_value': act}
            compared_samples += bool(trace['compared_values'])
            compared_values += trace['compared_values']
            compared_bits += trace['compared_bits']
        if mismatched: failed.append(case['id'])
        elif uncertain: unknown_cases.append(case['id'])
        elif compare_expected and comparisons: passed.append(case['id'])
        else: untested_cases.append(case['id'])
    return dict(suite_hash=suite_hash(suite), traces=traces, passed_cases=passed,
                failed_cases=failed, unknown_cases=unknown_cases, untested_cases=untested_cases,
                compared_samples=compared_samples, compared_values=compared_values, compared_bits=compared_bits,
                unknown_expected=unknown_expected, unknown_actual=unknown_actual,
                guard_unknown=guard_unknown, mask_unknown=mask_unknown,
                expectation_analysis=analyze_expectations(suite),
                clock=suite.get('clock'), clocks=suite.get('clocks'), sampling='after_edge_or_settle',
                first_mismatch=first,
                attribution='unverified_mismatch' if failed else 'unknown_values' if unknown_cases else
                            'self_agreement' if compare_expected else 'observation_only')


def simulate(ctx, input, *, save_vcd=False):
    """One bounded check, all commands use the caller's managed process service."""
    started = time.monotonic()
    try:
        suite = validate_suite(input.suite, task_text=ctx.task.prompt + '\n' + ctx.task.interface)
        if input.compare_expected and suite['mode'] != 'behavior':
            raise SuiteError('expected comparison requires behavior mode')
    except (SuiteError, TypeError, KeyError) as error:
        return CheckOutcome('error', str(error), details={'attribution': 'checker_invalid',
            'failure_kind': 'unknown', 'suite_hash': suite_hash(input.suite), 'traces': [],
            'passed_cases': [], 'failed_cases': [], 'first_mismatch': None})
    identity = suite_hash(suite)
    marker = hashlib.sha256((input.candidate.code_hash + identity).encode()).hexdigest()[:16]
    stem = f'functional/{input.candidate.id}-{identity[:12]}'
    driver = build_testbench(suite, ctx.task.top, marker)
    analysis = analyze_expectations(suite)
    artifacts = {'driver': str(ctx.artifacts.write_text(stem + '/driver.sv', driver)),
                 'suite': str(ctx.artifacts.write_json(stem + '/suite.json', suite))}
    base = {'suite_hash': identity, 'candidate_hash': input.candidate.code_hash,
            'driver_hash': hashlib.sha256(driver.encode()).hexdigest(),
            'expectation_analysis': analysis, 'artifacts': artifacts,
            'traces': [], 'passed_cases': [], 'failed_cases': [], 'first_mismatch': None,
            'attribution': 'environment', 'failure_kind': 'environment', 'vcd_requested': save_vcd}

    def finish(status, summary, **kwargs):
        details = kwargs.pop('details', base)
        details['artifacts'] = {**artifacts, **details.get('artifacts', {})}
        ctx.artifacts.write_json(stem + '/result.json',
            {'status': status, 'summary': summary, 'details': details,
             'commands': kwargs.get('command', ()), 'elapsed_s': time.monotonic() - started})
        return CheckOutcome(status, summary, details=details, elapsed_s=time.monotonic() - started, **kwargs)

    if input.compare_expected and not analysis['comparable_values']:
        return finish('skipped', 'checker has no comparable expected values; specification-grounded correction required',
            details={**base, 'attribution': 'checker_uninformative', 'failure_kind': 'unknown',
                     'compared_samples': 0, 'compared_values': 0, 'compared_bits': 0})
    chain = ctx.toolchain()
    config = getattr(chain, 'config', None)
    search = getattr(config, 'bin_dir', None)
    tools = {n: getattr(chain, n, None) or shutil.which(n, path=search) for n in ('xvlog', 'xelab', 'xsim')}
    missing = [n for n, executable in tools.items() if not executable]
    if missing:
        return finish('unavailable', 'simulation tools unavailable: ' + ', '.join(missing))
    timeout = ctx.timeout_s if ctx.timeout_s is not None else 300.0
    deadline = started + timeout
    commands, logs = [], []
    scratch = getattr(config, 'temp_dir', None)
    with tempfile.TemporaryDirectory(prefix='rtla_functional_', dir=scratch) as work:
        Path(work, 'solution.sv').write_text(input.candidate.code, encoding='utf-8')
        Path(work, 'driver.sv').write_text(driver, encoding='utf-8')
        simulation = (tools['xsim'], 'rtla_sim', '-runall')
        if save_vcd:
            script = 'open_vcd waveform.vcd\nlog_vcd /rtla_tb/*\nrun all\nclose_vcd\nquit\n'
            Path(work, 'wave.tcl').write_text(script, encoding='utf-8')
            artifacts['wave_script'] = str(ctx.artifacts.write_text(stem + '/wave.tcl', script))
            simulation = (tools['xsim'], 'rtla_sim', '-tclbatch', 'wave.tcl')
        elaboration = (tools['xelab'], 'rtla_tb', '-s', 'rtla_sim')
        if save_vcd:
            elaboration += ('-debug', 'typical')
        for index, command in enumerate(((tools['xvlog'], '--sv', 'solution.sv', 'driver.sv'),
                elaboration, simulation)):
            commands.append(tuple(command))
            result = ctx.processes.run(ProcessRequest(tuple(command), work, max(0, deadline - time.monotonic())))
            log = ctx.artifacts.write_text(stem + f'/stage-{index}.log', result.output)
            logs.append(str(log))
            wave = Path(work, 'waveform.vcd')
            if save_vcd and wave.is_file():
                artifacts['vcd'] = str(ctx.artifacts.write_text(stem + '/waveform.vcd', wave.read_text()))
            if result.status != 'ok':
                status = 'timeout' if result.status == 'timeout' else 'unavailable' if result.status == 'unavailable' else 'error'
                return finish(status, f'functional simulation stage {index} did not complete: ' + result.output[-1500:],
                    rc=result.rc, command=tuple(commands),
                    details={**base, 'attribution': 'simulation_unresolved'}, log_paths=tuple(logs))
        try:
            details = parse_traces(result.output, suite, marker, compare_expected=input.compare_expected)
        except SuiteError as error:
            return finish('error', str(error), command=tuple(commands),
                details={**base, 'attribution': 'simulation_incomplete', 'failure_kind': 'unknown'}, log_paths=tuple(logs))
        details = {**base, **details, 'failure_kind': 'unknown'}
        artifacts['traces'] = str(ctx.artifacts.write_json(stem + '/traces.json', details))
        status = ('failed' if details['failed_cases'] else 'skipped' if details['unknown_cases'] else
                  'passed' if not input.compare_expected or details['passed_cases'] else 'skipped')
        summary = ('observations collected; no expected behavior checked' if not input.compare_expected else
                   f"self-check: {len(details['passed_cases'])} passed, {len(details['failed_cases'])} failed, "
                   f"{len(details['unknown_cases'])} unknown cases; {details['compared_bits']} compared bits")
        return finish(status, summary, command=tuple(commands), details=details, log_paths=tuple(logs))
