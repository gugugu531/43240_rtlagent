"""Fail-closed timing checks for a deliberately narrow self-test protocol.

These checks establish stimulus consistency, NOT the truth of a model oracle.
Only single-clock, resettable designs with one output register bank are
supported for now. Mixed/multiple outputs, unknown initialization and multiple clocks
must fall back rather than produce speculative code-repair evidence.
"""
from dataclasses import dataclass, asdict
import re


def specification_quote(basis, prompt):
    if isinstance(basis, list):
        if not basis or len(basis) > 16 or sum(len(s) if isinstance(s, str) else 10000 for s in basis) > 8000:
            raise ValueError('invalid specification basis fragments')
        if any(not isinstance(s, str) for s in basis):
            raise ValueError('invalid specification basis fragments')
        return '\n'.join(specification_quote(s, prompt) for s in basis)
    if not isinstance(basis, str) or len(basis) > 2000:
        raise ValueError('invalid specification basis')
    words = basis.split()
    match = re.search(r'\s+'.join(re.escape(w) for w in words), prompt) if words else None
    if match is None:
        raise ValueError('each expectation needs a verbatim specification quote (whitespace may differ)')
    return match.group(0)


def explicit_reset_values(text, name):
    """Read narrow positive literals, including width-checked Verilog hex/octal."""
    literal = r"(\d+'[bBoOdDhH][0-9a-fA-F_]+|\d+)(?![\w'])"
    pattern = (r'(?<!\w)' + re.escape(name) +
               r'\s*(?:=|is\s+(?:set\s+to|reset\s+to)|resets\s+to|becomes|is|to)\s*' + literal)
    values = []
    for match in re.finditer(pattern, text, re.I):
        token = match.group(1)
        if "'" not in token:
            values.append(int(token))
            continue
        width, digits = token.split("'", 1)
        base = {'b': 2, 'o': 8, 'd': 10, 'h': 16}[digits[0].lower()]
        try:
            number = int(digits[1:].replace('_', ''), base)
        except ValueError:
            continue
        # Refuse overflow/truncation rather than infer the author's intention.
        if 1 <= int(width) <= 4096 and number.bit_length() <= int(width):
            values.append(number)
    return values


def mentions(text, name):
    return re.search(r'(?<!\w)' + re.escape(name) + r'(?!\w)', text, re.I) is not None


def _affirmative(text):
    text = re.sub(r'unless\s+otherwise\s+specified', '', text, flags=re.I)
    return not re.search(r"\b(?:not|never|except|unless|unspecified|either)\b|don't|"
                         r"(?:to|=)\s*(?:\d+|zero|one)\s+(?:or|if|when)\b", text, re.I)


def _reset_control_supported(text, polarity, kind, reset):
    """Polarity must describe reset, not an unrelated active-high enable."""
    active = r'active[-\s]+' + polarity + r'\b'
    mode = r'\b' + kind + r'\b'
    return any(re.search(pattern, text, re.I) for pattern in (
        active + r'\s+' + mode + r'\s+reset\b',
        mode + r'\s*,?\s*' + active + r'\s+reset\b',
        r'\breset\s+' + re.escape(reset) + r'\s+is\s+' + active + r'\s*,?\s*' + mode,
        r'\breset(?:\s+input)?\s+(?:is\s+)?' + active + r'\s*,?\s*' + mode))


def _single_registered_family(text, outputs):
    """A narrow unique-output reference, not an inference about FSM outputs."""
    return (len(outputs) == 1 and _affirmative(text)
            and not re.search(r'\b(?:combinational|FSM|Moore|Mealy)\b|state\s+machine', text, re.I) and
            re.search(r'\b(?:registered\s+output|D\s+flip.flops?|DFFs?|counter|shift\s+register|LFSR)\b', text, re.I))


def _reset_output_literals(text, name, outputs, family_text):
    literals = explicit_reset_values(text, name)
    if not _single_registered_family(family_text, outputs) or not _affirmative(text):
        return literals
    # Bind only a single externally visible register bank. "zero"/"one" are
    # explicit values; "cleared", state labels and unspecified values are not.
    token = r"(\d+'[bBoOdDhH][0-9a-fA-F_]+|\d+|zero|one)(?![\w'])"
    subjects = r'(?:the\s+)?(?:LFSR\s+)?output'
    if re.search(r'\bcounter\b', family_text, re.I) and outputs[name] > 1:
        subjects += r'|(?:the\s+)?counter'
    if re.search(r'\bshift\s+register\b', family_text, re.I):
        subjects += r'|(?:the\s+)?shift\s+register'
    patterns = [rf'(?:{subjects})\s+(?:should\s+be\s+)?(?:reset|set)\s+to\s+{token}',
                rf'(?:reset(?:ting|s)?|set(?:ting|s)?)\s+(?:{subjects})\s+to\s+{token}']
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.I):
            value = {'zero': '0', 'one': '1'}.get(match[1].lower(), match[1])
            literals.extend(explicit_reset_values(name + ' is set to ' + value, name))
    return literals


@dataclass(frozen=True)
class TimingContract:
    kind: str = 'combinational'
    clock: str = ''
    edge: str = ''
    reset: str = ''
    reset_active: int = 0
    reset_kind: str = ''
    reset_values: tuple = ()
    basis: str = ''
    reset_basis: str = ''

    def public_dict(self):
        if self.kind == 'combinational':
            return dict(kind=self.kind)
        result = asdict(self)
        result['reset_values'] = dict(self.reset_values)
        return result


def parse_timing(raw, task, inputs, outputs):
    clock_ports = {n for n in inputs if re.search(r'clk|clock', n, re.I)}
    # Explicit absence is not evidence of a clock/reset. Mask only the narrow
    # negative phrases, leaving every other state/edge mention intact.
    temporal_text = re.sub(r'\bno\s+(?:clock|reset)(?:\s+and\s+no\s+(?:clock|reset))?\b',
                           '', task.prompt, flags=re.I)
    temporal = re.search(r'\b(posedge|negedge|rising|falling|clock|sequential|register(?:ed)?|flip.flop|latch|reset|cycle|previous|state)\b|'
                         r'\b(?:positive|negative)\s+edge\b',
                         temporal_text, re.I)
    if raw is None:
        raw = dict(kind='combinational')  # Legacy combinational plans only.
    if not isinstance(raw, dict):
        raise ValueError('invalid timing contract')
    if raw == dict(kind='combinational'):
        if clock_ports or temporal:
            raise ValueError('temporal or uncertain design requires an explicit sequential timing contract')
        return TimingContract()
    fields = {'kind', 'clock', 'edge', 'reset', 'reset_active', 'reset_kind',
              'reset_values', 'basis', 'reset_basis'}
    if set(raw) != fields or raw['kind'] != 'sequential':
        raise ValueError('unsupported timing contract; only combinational or single-clock resettable registered outputs')
    clock, reset, edge = raw['clock'], raw['reset'], raw['edge']
    if (not isinstance(clock, str) or not isinstance(reset, str)
            or inputs.get(clock) != 1 or inputs.get(reset) != 1 or clock == reset):
        raise ValueError('clock and reset must be distinct declared one-bit inputs')
    if clock_ports - {clock} or re.search(r'\b(multiple clocks|multi.clock|both edges|dual.edge|latch)\b', task.prompt, re.I):
        raise ValueError('multiple clocks, dual edges and latches are unsupported')
    if edge not in ('posedge', 'negedge') or raw['reset_kind'] not in ('synchronous', 'asynchronous'):
        raise ValueError('edge and reset kind must be explicit')
    active = raw['reset_active']
    if type(active) is not int or active not in (0, 1):
        raise ValueError('reset_active must be 0 or 1')
    basis = specification_quote(raw['basis'], task.prompt)
    reset_basis = specification_quote(raw['reset_basis'], task.prompt)
    if not _affirmative(basis) or not _affirmative(reset_basis):
        raise ValueError('negated or conditional timing evidence is unsupported')
    if (not _single_registered_family(basis, outputs)
            or re.search(r'\b(?:combinational|FSM|Moore|Mealy|latch)\b|state\s+machine', task.prompt, re.I)):
        raise ValueError('ALL registered outputs need a supported unique register-bank contract')
    edge_words = r'\b(posedge|rising|positive)\b' if edge == 'posedge' else r'\b(negedge|falling|negative)\b'
    opposite = r'\b(negedge|falling|negative)\b' if edge == 'posedge' else r'\b(posedge|rising|positive)\b'
    named_clock = mentions(basis, clock)
    unique_declared_clock = (clock_ports == {clock} and re.search(r'\bclock\b', basis, re.I))
    if (not (named_clock or unique_declared_clock) or not re.search(edge_words, basis, re.I)
            or re.search(opposite, basis, re.I)
            or (any(not mentions(basis, n) for n in outputs) and not _single_registered_family(basis, outputs))):
        raise ValueError('clock edge and ALL registered outputs need unambiguous quoted evidence')
    polarity = 'high' if active else 'low'
    other = 'low' if active else 'high'
    reset_ports = {n for n in inputs if re.search(r'reset|rst', n, re.I)}
    if any(inputs[n] == 1 for n in reset_ports - {reset}):
        raise ValueError('multiple reset inputs are unsupported')
    unique_reset = (reset_ports == {reset} and re.search(r'\breset\b', reset_basis, re.I)
                    and _single_registered_family(basis, outputs))
    if (not (mentions(reset_basis, reset) or unique_reset)
            or not re.search(r'active[-\s]+' + polarity + r'\b', reset_basis, re.I)
            or re.search(r'active[-\s]+' + other + r'\b', reset_basis, re.I)
            or not _reset_control_supported(reset_basis, polarity, raw['reset_kind'], reset)):
        raise ValueError('reset name, polarity and sync/async kind need explicit quoted evidence')
    reset_values = raw['reset_values']
    if not isinstance(reset_values, dict) or set(reset_values) != set(outputs):
        raise ValueError('every registered output needs a reset value; mixed outputs unsupported')
    for name, value in reset_values.items():
        if type(value) is not int or not 0 <= value < 2 ** outputs[name]:
            raise ValueError('invalid or ungrounded reset output')
        # Do not infer "cleared", signed values, concatenations or number words.
        literals = _reset_output_literals(reset_basis, name, outputs, basis)
        if not literals or set(literals) != {value}:
            raise ValueError('reset output value needs an explicit supported literal next to its name')
    return TimingContract('sequential', clock, edge, reset, active, raw['reset_kind'],
                          tuple(sorted(reset_values.items())), basis, reset_basis)


def timing_history(plan):
    """Record the full bounded input prefix, including edge/reset state at each sample."""
    driven, history, elapsed, edges = {}, [], 0, 0
    timing = plan.timing
    for index, step in enumerate(plan.steps):
        previous = dict(driven)
        driven.update(step.inputs)
        active_edge = (timing.kind == 'sequential' and index > 0
                       and previous[timing.clock] != driven[timing.clock]
                       and driven[timing.clock] == (1 if timing.edge == 'posedge' else 0))
        edges += int(active_edge)
        elapsed += step.wait_ns
        history.append(dict(step=index, time_ns=elapsed, inputs=dict(driven),
            active_edge=bool(active_edge), active_edge_count=edges,
            reset_active=(driven[timing.reset] == timing.reset_active) if timing.kind == 'sequential' else None,
            expected=dict(step.expected)))
    return history


def validate_timing(plan):
    timing = plan.timing
    if timing.kind != 'sequential':
        return
    history = timing_history(plan)
    inactive = 0 if timing.edge == 'posedge' else 1
    first = history[0]['inputs']
    if first[timing.clock] != inactive or first[timing.reset] != timing.reset_active:
        raise ValueError('initialize clock inactive and reset asserted')
    initialized, reset_edge, functional_assertions = False, False, 0
    held = {}
    reset_values = dict(timing.reset_values)
    for index, (step, row) in enumerate(zip(plan.steps, history)):
        state = row['inputs']
        previous = history[index - 1]['inputs'] if index else state
        changed = {n for n in state if previous[n] != state[n]}
        if row['active_edge'] and changed - {timing.clock}:
            raise ValueError('data/reset changes must precede, not coincide with, an active clock edge')
        if changed - {timing.clock} and state[timing.clock] != inactive:
            raise ValueError('prepare data/reset only while clock is inactive')
        if timing.reset in changed and not row['reset_active'] and not reset_edge:
            raise ValueError('hold initial reset through at least one active clock edge')
        reset_event = row['reset_active'] and (row['active_edge'] or timing.reset_kind == 'asynchronous')
        if row['active_edge']:
            held = {}
            if row['reset_active']:
                reset_edge = True
        if reset_event:
            initialized = True
            held = dict(reset_values)
        expected = dict(step.expected)
        if expected and not initialized:
            raise ValueError('cannot assert unknown state before effective reset')
        for name, value in expected.items():
            if name in held and held[name] != value:
                raise ValueError('registered output expectation changes without an effective edge/reset event')
        held.update(expected)
        if row['active_edge'] and not row['reset_active']:
            functional_assertions += len(expected)
    if not functional_assertions:
        raise ValueError('sequential plan must check a functional active edge after reset release')
