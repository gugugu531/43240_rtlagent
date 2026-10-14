"""Specification-only evidence references and deterministic cycle expansion."""
import re


def evidence_catalog(prompt):
    """Stable, exact source paragraphs; never inspect implementations or test data."""
    paragraphs = re.split(r'\n\s*\n', prompt)
    spans = []
    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if len(paragraph) <= 2000:
            spans.append(paragraph)
        else:
            # Do not truncate a quotation or split in the middle of a literal.
            spans.extend(line.strip() for line in paragraph.splitlines()
                         if line.strip() and len(line.strip()) <= 2000)
    return tuple(spans)


def resolve_basis(value, prompt):
    """References resolve to original spans; legacy exact quotations still work."""
    catalog = evidence_catalog(prompt)
    if type(value) is int:
        value = [value]
    if isinstance(value, list) and value and all(type(i) is int for i in value):
        if len(value) > 16 or len(value) != len(set(value)) or any(not 0 <= i < len(catalog) for i in value):
            raise ValueError('invalid specification evidence IDs')
        return [catalog[i] for i in value]
    if isinstance(value, str):
        return value
    if isinstance(value, list) and value and all(isinstance(s, str) for s in value):
        # Internally composed evidence and legacy fragment quotations are still
        # checked against the original prompt by specification_quote.
        return value
    raise ValueError('basis must be a nonempty list of evidence IDs or an exact quotation')


def cycle_steps(cycles, timing, inputs, *, max_steps, reset_basis):
    """The scheduler owns clock/reset. Model cycles contain data and post-edge checks."""
    if timing.kind != 'sequential':
        raise ValueError('cycles require an explicit sequential timing contract')
    if not isinstance(cycles, list) or not 1 <= len(cycles) <= min(14, (max_steps - 4) // 2):
        raise ValueError('invalid cycle count')
    data_ports = set(inputs) - {timing.clock, timing.reset}
    for index, row in enumerate(cycles):
        if not isinstance(row, dict) or set(row) != {'inputs', 'expected', 'basis'}:
            raise ValueError('invalid cycle fields')
        if not isinstance(row['inputs'], dict) or not set(row['inputs']) <= data_ports:
            raise ValueError('cycles may drive declared data inputs only; scheduler owns clock/reset')
        if index == 0 and set(row['inputs']) != data_ports:
            raise ValueError('first cycle must initialize all data inputs')
    inactive = 0 if timing.edge == 'posedge' else 1
    active = 1 - inactive
    def step(driven, expected, basis):
        return dict(inputs=driven, expected=expected, basis=basis, wait_ns=1)
    # No assertion before a synchronous reset has had an effective edge.
    initial = dict(cycles[0]['inputs'])
    initial.update({timing.clock: inactive, timing.reset: timing.reset_active})
    # Keep original fragments for both checks: the contract's joined display
    # text need not occur contiguously in the specification.
    rows = [step(initial, {}, ''),
            step({timing.clock: active}, dict(timing.reset_values), reset_basis)]
    for row in cycles:
        prepared = dict(row['inputs'])
        prepared.update({timing.clock: inactive, timing.reset: 1 - timing.reset_active})
        rows.append(step(prepared, {}, ''))
        rows.append(step({timing.clock: active}, row['expected'], row['basis']))
    # Always probe reset, even when the model predicts the reset value. A sync
    # hold is compared with the OBSERVED previous sample by analyze_trace, not
    # with a model-predicted last state. Equal-to-reset states are explicitly
    # recorded as non-discriminating for reset-kind coverage.
    rows.append(step({timing.clock: inactive, timing.reset: timing.reset_active}, {}, ''))
    rows.append(step({timing.clock: active}, dict(timing.reset_values), reset_basis))
    return rows
