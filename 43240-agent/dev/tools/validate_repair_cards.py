#!/usr/bin/env python3
"""Independent non-contest HDL examples for the small E1 repair-card subset."""
from pathlib import Path
import argparse
import json
import sys
import hashlib
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from agent.services.vivado import RtlToolchain
from agent.core.config import ToolConfig
from agent.recording.artifacts import atomic_write_json

CASES = (
    ('procedural-variable', 'VRFC 10-1280',
     'module TopModule(input a, output q); always @* q = a; endmodule\n',
     'module TopModule(input a, output reg q); always @* q = a; endmodule\n',
     'module TopModule(input a, output q); assign q = a; endmodule\n'),
    ('syntax-local-context', 'VRFC 10-4982',
     'module TopModule(input a, output q) assign q = a; endmodule\n',
     'module TopModule(input a, output q); assign q = a; endmodule\n',
     'module TopModule(input a, output q); assign q = ~a; endmodule\n'),
    ('module-port-contract', 'VRFC 10-3180',
     'module child(input a, output q); assign q=a; endmodule\nmodule TopModule(input a, output q); child dut(.wrong(a), .q(q)); endmodule\n',
     'module child(input a, output q); assign q=a; endmodule\nmodule TopModule(input a, output q); child dut(.a(a), .q(q)); endmodule\n',
     'module child(input a, output q); assign q=a; endmodule\nmodule TopModule(input a, output q); child dut(.a(a), .q(q)); endmodule\n'),
    ('ansi-port-declaration', 'VRFC 10-9336',
     'module TopModule(input a, output q); reg q; always @* q=a; endmodule\n',
     'module TopModule(input a, output reg q); always @* q=a; endmodule\n',
     'module TopModule(a,q); input a; output q; reg q; always @* q=a; endmodule\n'),
    ('mixed-drivers-declaration', 'VRFC 10-1280',
     'module TopModule(input a, input clk, output w, output q); assign w=a; always @(posedge clk) q<=a; endmodule\n',
     'module TopModule(input a, input clk, output w, output reg q); assign w=a; always @(posedge clk) q<=a; endmodule\n',
     'module TopModule(input a, input clk, output w, output logic q); assign w=a; always @(posedge clk) q<=a; endmodule\n'),
    ('part-select-descending', 'VRFC 10-1219',
     'module TopModule(input [7:0] a, output [3:0] q); assign q=a[0:3]; endmodule\n',
     'module TopModule(input [7:0] a, output [3:0] q); assign q=a[3:0]; endmodule\n',
     'module TopModule(input [7:0] a, output [3:0] q); assign q=a[4 +: 4]; endmodule\n'),
    ('part-select-ascending', 'VRFC 10-1219',
     'module TopModule(input [0:7] a, output [3:0] q); assign q=a[7:4]; endmodule\n',
     'module TopModule(input [0:7] a, output [3:0] q); assign q=a[4:7]; endmodule\n',
     'module TopModule(input [0:7] a, output [3:0] q); assign q=a[0 +: 4]; endmodule\n'),
)


def validate(destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    tool = RtlToolchain(config=ToolConfig(), log_dir=destination / 'logs')
    identity = tool.identify()
    rows = []
    for card_id, code, broken, fixed, control in CASES:
        row = dict(card_id=card_id, expected_code=code)
        for name, source in (('broken', broken), ('fixed', fixed), ('control', control)):
            (destination / f'{card_id}-{name}.sv').write_text(source)
            result = tool.lint(source, 'TopModule', timeout_s=30)
            row[name] = dict(status=result.status, summary=result.summary, failure_kind=result.failure_kind,
                command=result.command, source_sha256=hashlib.sha256(source.encode()).hexdigest(),
                log_paths=result.log_paths, diagnostic_tool=result.diagnostic_tool)
        row['valid'] = (row['broken']['status'] == 'failed' and code in row['broken']['summary']
                        and row['fixed']['status'] == 'ok' and row['control']['status'] == 'ok')
        rows.append(row)
    report = dict(kind='independent_non_contest_examples', created_at=time.time(),
                  tool_identity=identity, cases=rows, all_valid=all(r['valid'] for r in rows),
                  tool_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    atomic_write_json(destination / 'report.json', report)
    print(json.dumps({'out': str(destination), 'all_valid': report['all_valid'],
                      'cases': [{k: r[k] for k in ('card_id', 'valid')} for r in rows]}))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(0 if validate(args.out)['all_valid'] else 1)
