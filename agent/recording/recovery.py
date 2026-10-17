"""Recover committed selection and close trace evidence after the worker stops."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import time
from agent.core.candidate import Candidate
from agent.recording.artifacts import atomic_write_text


def recover_selection(out: str | Path) -> tuple[Candidate | None, str]:
    out = Path(out)
    try:
        saved = json.loads((out / 'selection.json').read_text())
        if saved.get('candidate_id') is None:
            atomic_write_text(out / 'solution.v', '')
            return None, 'empty'
        code, metadata = saved['code'], saved['candidate']
        digest = hashlib.sha256(code.encode()).hexdigest()
        if digest != saved['code_hash'] or digest != metadata['code_hash'] or metadata['id'] != saved['candidate_id']:
            raise ValueError('checkpoint hash/identity mismatch')
        candidate = Candidate(code=code, **{k: v for k, v in metadata.items() if k != 'code_bytes'})
        previous = (out / 'solution.v').read_text()
        if previous != code:
            atomic_write_text(out / 'solution.v', code)
        return candidate, 'verified' if previous == code else 'restored'
    except (OSError, ValueError, KeyError, TypeError):
        # A file without verified provenance cannot be described as selected.
        atomic_write_text(out / 'solution.v', '')
        return None, 'invalid_checkpoint'


def record_supervision(out: str | Path, fields: dict, run_id: str) -> None:
    """Append after worker exit; leave unfinished call/node evidence untouched."""
    out = Path(out)
    trace = out / 'trace.jsonl'
    events = []
    raw = trace.read_bytes() if trace.exists() else b''
    valid = bytearray()
    for line in raw.splitlines(keepends=True):
        try:
            events.append(json.loads(line))
            valid.extend(line if line.endswith(b'\n') else line + b'\n')
        except (ValueError, UnicodeDecodeError):
            # Retain interrupted bytes separately; return parseable JSONL.
            atomic_write_text(out / 'trace_partial.txt', line.decode(errors='replace'))
    event = dict(fields, tool='supervisor', event='result', run_id=run_id,
                 seq=max((e.get('seq', 0) for e in events), default=0) + 1, ts=round(time.time(), 3))
    atomic_write_text(trace, valid.decode() + json.dumps(event, ensure_ascii=False) + '\n')
