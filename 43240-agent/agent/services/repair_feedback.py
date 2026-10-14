"""Bounded evidence from the current DUT and its own tool observations only."""
from __future__ import annotations
import re


def extract_diagnostics(log: str, limit=32):
    """Collect roots before summary truncation; incomplete evidence stays explicit."""
    rows, seen, omitted, truncated = [], set(), 0, False
    for line in log.splitlines():
        match = re.search(r'(ERROR|WARNING):\s*\[([^\]]+)\]\s*(.*)', line, re.I)
        if not match:
            continue
        severity, code, message = match.groups()
        code = ' '.join(code.upper().split())
        if severity.upper() == 'WARNING' and code != 'SYNTH 8-3848':
            continue
        key = (code, message)
        if key in seen:
            continue
        seen.add(key)
        if len(rows) >= limit:
            omitted += 1
            continue
        truncated |= len(message) > 700
        symbols = re.findall(r"(?:variable|signal|net)\s+['\"]([A-Za-z_][A-Za-z0-9_$]*)['\"]", message, re.I)
        rows.append(dict(code=code, severity=severity.lower(), message=message[:700],
                         symbols=list(dict.fromkeys(symbols)), cascade=code == 'XSIM 43-3322'))
    return dict(items=rows, omitted=omitted, complete=not (omitted or truncated))


def _interface(code, top):
    from agent.core.interface import parse_module_interface
    interface = parse_module_interface(code)
    # A lexical parser is not an HDL elaborator. Ambiguous headers are unknown.
    if (not interface.parsed or interface.confidence != 'high' or interface.module_name != top
            or any(p.width is None for p in interface.ports)):
        return None
    return interface


def output_driver_warnings(code, top, checks):
    interface = _interface(code, top)
    if interface is None:
        return []
    outputs = {p.name for p in interface.ports if p.direction == 'output'}
    warnings = []
    for check in checks:
        if check.kind != 'synth' or check.status != 'passed':
            continue
        evidence = check.details.get('repair_diagnostics')
        if not evidence or not evidence.get('complete') or evidence.get('omitted'):
            continue
        for diagnostic in evidence['items']:
            if diagnostic['code'] != 'SYNTH 8-3848':
                continue
            match = re.fullmatch(r'Net ([A-Za-z_][A-Za-z0-9_$]*)(\[\d+\])? in module/entity '
                r'([A-Za-z_][A-Za-z0-9_$]*) does not have driver\.\s*(?:\[[^\n]+\])?', diagnostic['message'])
            if match and match[1] in outputs and match[3] == top:
                warnings.append(dict(signal=match[1] + (match[2] or ''), code=diagnostic['code'],
                                     message=diagnostic['message']))
    return warnings


def output_driver_evidence(code, top, checks):
    """Absence of a warning proves nothing when the observation is incomplete."""
    interface = _interface(code, top)
    latest = next((c for c in reversed(checks) if c.kind == 'synth'), None)
    if interface is None or latest is None or latest.status != 'passed':
        return None
    evidence = latest.details.get('repair_diagnostics')
    if not evidence or not evidence.get('complete') or evidence.get('omitted'):
        return None
    # An unfamiliar undriven-warning format cannot establish that all defects cleared.
    for diagnostic in evidence['items']:
        if diagnostic['code'] == 'SYNTH 8-3848' and not re.fullmatch(
                r'Net [A-Za-z_][A-Za-z0-9_$]*(?:\[\d+\])? in module/entity '
                r'[A-Za-z_][A-Za-z0-9_$]* does not have driver\.\s*(?:\[[^\n]+\])?', diagnostic['message']):
            return None
    ports = tuple((p.name, p.direction, p.width, p.range_text) for p in interface.ports)
    if not any(p.direction == 'output' for p in interface.ports):
        return None
    return dict(ports=ports, undriven=frozenset(w['signal'] for w in
                output_driver_warnings(code, top, [latest])), check_id=latest.id)


def driver_repair_improves(old_code, new_code, top, old_checks, new_checks):
    old = output_driver_evidence(old_code, top, old_checks)
    new = output_driver_evidence(new_code, top, new_checks)
    return bool(old and new and old['ports'] == new['ports'] and new['undriven'] < old['undriven'])


def output_driver_feedback(warnings):
    return ('\nConfirmed synthesis observation: these TOP-LEVEL OUTPUTS have no driver:\n' +
        '\n'.join(f"{w['signal']}: [{w['code']}] {w['message'][:300]}" for w in warnings) +
        '\nImplement missing outputs according to the public specification. Similar internal names '
        'alone do not establish correctness. Preserve the complete interface, existing valid logic, '
        'reset semantics and timing. Do not silence warnings with arbitrary constants. '
        'Synthesis success and fewer warnings do NOT prove functional correctness.')


def assignment_hints(code, symbol):
    """Lexical navigation only: not AST scope analysis or a proof of drivers."""
    masked = re.sub(r'//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"',
                    lambda m: re.sub(r'[^\n]', ' ', m[0]), code)
    ident = r'[A-Za-z_][A-Za-z0-9_$]*(?:\s*\[[^\]\n]+\])*'
    lhs = rf'(?:{ident}|\{{\s*{ident}(?:\s*,\s*{ident})*\s*\}})'
    pattern = rf'(?:^|[;:)\n]|\bbegin\b|\belse\b|\bassign\b)\s*({lhs})\s*(?:<=(?!=)|=(?!=))'
    lines, sites = code.splitlines(), []
    for match in re.finditer(pattern, masked):
        bases = re.sub(r'\[[^\]]*\]', '', match[1])
        if symbol not in re.findall(r'[A-Za-z_][A-Za-z0-9_$]*', bases):
            continue
        line = masked.count('\n', 0, match.start(1)) + 1
        headers = list(re.finditer(r'\b(?:always(?:_ff|_comb|_latch)?|initial|assign)\b', masked[:match.start(1)]))
        owner = masked.count('\n', 0, headers[-1].start()) + 1 if headers else line
        sites.append(dict(line=line, text=lines[line-1].strip()[:240],
                          header_line=owner, header=lines[owner-1].strip()[:160]))
    return sites


def tool_repair_feedback(code, checks):
    """Group bounded diagnostics without opening any path taken from a log."""
    sections = []
    for check in checks:
        if check.status == 'passed':
            continue
        sections.append(f'[{check.kind}] {check.summary[:2000]}')
        evidence = check.details.get('repair_diagnostics') or extract_diagnostics(check.summary)
        roots = [d for d in evidence['items'] if not d['cascade'] and d['severity'] == 'error']
        if roots:
            sections.append('Distinct root diagnostics (fix every reported source defect):\n' +
                '\n'.join(f"[{d['code']}] {d['message']}" for d in roots))
        if not evidence.get('complete') or evidence.get('omitted'):
            sections.append(f"Diagnostic evidence incomplete; omitted reports: {evidence.get('omitted', 0)}")
        symbols = dict.fromkeys(s for d in roots for s in d['symbols'])
        for symbol in symbols:
            sites = assignment_hints(code, symbol)
            sections.append(f'Write-site hints for {symbol} (lexical, verify in full source): '
                            f'{len(sites)} write sites. Reset-only writes COUNT as drivers.')
            sections.extend(f"  L{s['line']}: {s['text']} | nearest header L{s['header_line']}: {s['header']}"
                            for s in sites[:12])
            if len(sites) > 12:
                sections.append(f'  {len(sites)-12} more write sites; inspect full source.')
            elif not sites:
                sections.append('  Not located lexically; do not assume no driver.')
        if any(re.search(r'multiple.*drivers|multi-driven|combination of procedural drivers', d['message'], re.I)
               for d in roots):
            sections.append('Driver ownership repair: audit EVERY reported signal, including reset writes. '
                'Give each register one procedural owner. Stateful values may use a clocked current '
                'register and a separate combinational next value with defaults. Combinational values '
                'need a single owner. Preserve specified reset type/priority and cycle behavior; '
                'do not merely rename variables or delete reset/functional assignments.')
    text = '\n\n'.join(sections)
    return text if len(text) <= 16000 else text[:16000] + '\n[feedback truncated; inspect full previous source]'
