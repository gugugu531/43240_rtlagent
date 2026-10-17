"""Attributed own-tool diagnostics; uncertain source positions stay explicit."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import re

CODE = re.compile(r'\b(ERROR|WARNING|CRITICAL WARNING):\s*\[([A-Za-z][\w-]*\s+\d+-\d+)\]', re.I)
POSITION = re.compile(r'\[([^\[\]]+?):(\d+)(?::(\d+))?\]\s*$')


@dataclass(frozen=True)
class Diagnostic:
    source_id: str
    candidate_id: str
    stage: str
    status: str
    classification: str
    tool: str | None
    version: str | None
    code: str | None
    severity: str
    message: str
    path: str | None = None
    reported_line: int | None = None
    reported_column: int | None = None
    candidate_line: int | None = None
    confidence: str = 'excerpt_only'
    log_paths: tuple[str, ...] = ()

    def public_dict(self):
        return asdict(self)


def diagnostics_from_check(check, *, candidate_code='', tool_identity=None):
    identity = tool_identity or check.details
    results, seen = [], set()
    for line in check.summary.splitlines():
        match = CODE.search(line)
        if match is None:
            continue
        severity, code = match.group(1).upper(), ' '.join(match.group(2).upper().split())
        position = POSITION.search(line)
        path = position.group(1) if position else None
        reported = int(position.group(2)) if position else None
        column = int(position.group(3)) if position and position.group(3) else None
        verified = (path is not None and Path(path).name in ('solution.sv', 'solution.v')
                    and reported is not None and 1 <= reported <= len(candidate_code.splitlines()))
        key = code, line.strip()
        if key in seen:
            continue
        seen.add(key)
        results.append(Diagnostic(check.id, check.candidate_id, check.kind, check.status,
            check.classify(), identity.get('diagnostic_tool'), identity.get('tool_version'), code,
            severity, line.strip(), path, reported, column, reported if verified else None,
            'candidate_line_verified' if verified else 'excerpt_only', check.log_paths))
    if not results and check.status != 'passed':
        results.append(Diagnostic(check.id, check.candidate_id, check.kind, check.status,
            check.classify(), identity.get('diagnostic_tool'), identity.get('tool_version'), None,
            'UNKNOWN', check.summary, log_paths=check.log_paths))
    return tuple(results)
