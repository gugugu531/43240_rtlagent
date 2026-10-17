"""Narrow public-specification literals, not model-computed expectations.

Fail closed outside a complete binary combinational truth table. This is not a
natural-language theorem prover and never reads task IDs, solutions or a TB.
"""
from dataclasses import dataclass
import hashlib
import json
import re

from agent.services.timing import parse_timing
from agent.services.spec_ports import supported_ports


@dataclass(frozen=True)
class LiteralTruthTable:
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    rows: tuple[tuple[tuple[int, ...], tuple[int, ...]], ...]
    basis: str

    def public_dict(self):
        return dict(source='public_literal_truth_table', inputs=list(self.inputs),
                    outputs=list(self.outputs), rows=[[list(i), list(o)] for i, o in self.rows],
                    basis=self.basis)

    @property
    def fingerprint(self):
        return hashlib.sha256(json.dumps(self.public_dict(), sort_keys=True).encode()).hexdigest()

    def expected(self, driven):
        key = tuple(driven[n] for n in self.inputs)
        return dict(zip(self.outputs, dict(self.rows)[key]))


def plan_kind(task):
    """Routing hint only; the existing timing validator is still authoritative."""
    ports = task.expected_interface.ports
    inputs = {p.name: p.width for p in ports if p.direction == 'input'}
    outputs = {p.name: p.width for p in ports if p.direction == 'output'}
    if not task.expected_interface.parsed:
        return 'uncertain'
    try:
        parse_timing(dict(kind='combinational'), task, inputs, outputs)
        return 'combinational'
    except ValueError:
        return ('sequential' if any(re.search(r'clk|clock', n, re.I) for n in inputs)
                or re.search(r'\b(posedge|negedge|flip.flop|sequential|registered|rising|falling)\b|'
                             r'\b(?:positive|negative)\s+edge\b', task.prompt, re.I)
                else 'uncertain')


def parse_literal_truth_table(task):
    """Accept a unique complete 0/1 table with exactly the declared 1-bit ports.

    Scope is deliberately small: an affirmative combinational truth-table
    declaration, at most five inputs (32 rows), no caveats or competing tables.
    Refusing this shortcut does not reject the task or relax normal validation.
    """
    try:
        supported_ports(task)
    except ValueError:
        return None
    if plan_kind(task) != 'combinational':
        return None
    spec = task.expected_interface
    ports = {p.name: p.direction for p in spec.ports}
    inputs = tuple(p.name for p in spec.ports if p.direction == 'input')
    outputs = tuple(p.name for p in spec.ports if p.direction == 'output')
    if (not 1 <= len(inputs) <= 5 or not 1 <= len(outputs) <= 16 or len(ports) != len(spec.ports)
            or len(task.prompt) > 65536 or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',task.top)
            or any(p.width != 1 or p.direction not in ('input', 'output')
                   or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',p.name) for p in spec.ports)):
        return None
    declaration = re.search(
        r'(?:should|must)\s+implement\s+a\s+combinational\s+circuit\s+for\s+the\s+following\s+truth\s+table\s*:',
        task.prompt, re.I)
    if not declaration:
        return None
    # The stock interface's "unless otherwise specified" is not a table caveat.
    without_interface_caveat = re.sub(r'unless\s+otherwise\s+specified', '', task.prompt, flags=re.I)
    if re.search(r"\b(not|unless|except|example|illustrative|invert(?:ed)?|override|negated)\b|don't\s+care",
                 without_interface_caveat, re.I):
        return None
    lines = task.prompt[declaration.end():].splitlines()
    def cells(line):
        return tuple(c.strip().strip('`') for c in line.strip().strip('|').split('|'))
    headers = [(i, cells(line)) for i, line in enumerate(lines)
               if '|' in line and len(cells(line)) == len(ports) and set(cells(line)) == set(ports)]
    if len(headers) != 1:
        return None
    index, header = headers[0]
    # No prose between the affirmative declaration and the one table header.
    if any(line.strip() for line in lines[:index]):
        return None
    rows = {}
    for line in lines[index + 1:]:
        if not line.strip():
            continue
        values = cells(line)
        if all(re.fullmatch(r':?-+:?', value) for value in values) and not rows:
            continue  # Markdown separator, not an input/output row.
        if len(values) != len(header) or any(value not in ('0', '1') for value in values):
            return None  # Includes ellipses, trailing caveats and extra tables.
        named = dict(zip(header, map(int, values)))
        key = tuple(named[n] for n in inputs)
        if key in rows:
            return None  # Reject identical duplicates as well as contradictions.
        rows[key] = tuple(named[n] for n in outputs)
    if len(rows) != 2 ** len(inputs):
        return None
    basis = task.prompt[declaration.start():]
    return LiteralTruthTable(inputs, outputs, tuple(sorted(rows.items())), basis)
