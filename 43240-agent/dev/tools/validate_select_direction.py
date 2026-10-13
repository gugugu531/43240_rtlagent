#!/usr/bin/env python3
"""Validate a primary part-select diagnostic with independent non-contest examples."""
from pathlib import Path
import argparse
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from agent.services.vivado import RtlToolchain
from agent.recording.artifacts import atomic_write_json, atomic_write_text


def validate(out):
    out.mkdir(parents=True, exist_ok=False)
    tools = RtlToolchain()
    identity = tools.identify(timeout_s=10)
    rows = []
    for name, select, ok in (('broken', '0:3', False), ('fixed', '3:0', True), ('control', '7:4', True)):
        source = f'module sample(input [7:0] a, output [3:0] y); assign y=a[{select}]; endmodule\n'
        atomic_write_text(out / (name + '.sv'), source)
        result = tools.lint(source, 'sample', timeout_s=30)
        row = dict(name=name, expected_pass=ok, status=result.status, summary=result.summary,
                   failure_kind=result.failure_kind, commands=result.command)
        row['valid'] = (result.status == 'ok' if ok else result.status == 'failed' and
                        'VRFC 10-1219' in result.summary and result.failure_kind == 'code')
        rows.append(row)
    atomic_write_json(out / 'validation.json', dict(identity=identity, rows=rows))
    if not all(row['valid'] for row in rows):
        raise ValueError('independent select validation differs; retain all evidence')
    return rows


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('out', type=Path)
    print(validate(parser.parse_args().out))
