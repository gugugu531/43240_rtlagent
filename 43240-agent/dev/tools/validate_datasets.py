#!/usr/bin/env python3
"""调用未修改的官方链路验参考答案，再检查输出恒零和未知值的候选。"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from datasets import ROOT, REPO, TASKS, code_only, check_task, write_json, parse_module_interface


def fingerprint(path):
    h = hashlib.sha256()
    for f in sorted(path.rglob('*')):
        if f.is_file():
            h.update(str(f.relative_to(path)).encode())
            h.update(f.read_bytes())
    return h.hexdigest()


def mutant(source, value):
    masked = code_only(source)
    m = re.search(r'\bmodule\s+TopModule\b', masked)
    end = masked.index(';', m.end()) + 1
    header = source[m.start():end]
    body_end = masked.index('endmodule', end)
    body = source[end:body_end]
    # 只保留接口和参数，不保留任何参考行为。
    declarations = re.findall(r'\b(?:parameter|localparam)\b[^;]*;', code_only(body))
    if not re.search(r'\b(?:input|output|inout)\b', code_only(header)):
        declarations += re.findall(r'\b(?:input|output|inout)\b[^;]*;', code_only(body))
    spec = parse_module_interface(source[m.start():body_end] + 'endmodule')
    if spec.module_name != 'TopModule' or not spec.ports:
        raise ValueError('无法解析参考接口以构造负例')
    outputs = [p.name for p in spec.ports if p.direction == 'output']
    if not outputs:
        raise ValueError('无输出端口')
    # 宏定义可能用于公开接口宽度。
    macros = '\n'.join(re.findall(r'(?m)^\s*`define[^\n]+', source))
    return macros + '\n' + header + '\n' + '\n'.join(declarations) + '\n' + '\n'.join(
        f"assign {name} = '{value};" for name in outputs) + '\nendmodule\n'


def run_one(path, out, rerun):
    tid = path.name
    dst = out / tid
    dst.mkdir(parents=True, exist_ok=True)
    cached = dst/'validation.json'
    digest = fingerprint(path)
    if cached.exists() and not rerun:
        old = json.loads(cached.read_text())
        if old.get('fingerprint') == digest and old.get('complete'):
            return old
    result = dict(task_id=tid, fingerprint=digest, format_errors=check_task(path),
                  reference={}, mutants={}, complete=False)
    if result['format_errors']:
        result['complete'] = True
        write_json(cached, result)
        return result
    # 每次只向官方自测入口提供一道题，避免多题运行相互污染工作目录。
    with tempfile.TemporaryDirectory(prefix='dataset-reference-') as work:
        taskroot = Path(work)/'tasks'
        taskroot.mkdir()
        shutil.copytree(path, taskroot/tid)
        command = [str(REPO/'selftest/run_selftest.sh'), '--reference', '--tasks', str(taskroot),
                   '--out', str(dst/'reference'), '--timeout', '180']
        with (dst/'reference-run.log').open('w') as log:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=False,
                           env={**os.environ, 'SELFTEST_TMP': str(dst), 'SELFTEST_KEEP_WORK': '1'})
    js = dst/'reference/results'/f'reference.{tid}.s0.json'
    if js.exists():
        result['reference'] = json.loads(js.read_text())
        work_dir = result['reference'].get('work_dir')
        if work_dir:
            for rel, name in [('w/judge.log', 'reference-judge.log'),
                              ('w/synth/synth.log', 'reference-synth.log')]:
                if (Path(work_dir)/rel).exists():
                    shutil.copyfile(Path(work_dir)/rel, dst/name)
    else:
        result['reference'] = dict(tool_error='官方自测未产出结果，见 reference-run.log')
    if result['reference'].get('stages', {}).get('simulate'):
        source = (path/'reference/solution.sv').read_text()
        for label, value in [('zero', '0'), ('unknown', 'x')]:
            md = dst/label
            md.mkdir(exist_ok=True)
            try:
                (md/'solution.sv').write_text(mutant(source, value))
            except ValueError as exc:
                result['mutants'][label] = dict(error=str(exc))
                continue
            command = ['python3', str(REPO/'selftest/judge/veval-judge'),
                       '--dut', str(md/'solution.sv'), '--ref', str(path/'ref.sv'),
                       '--test', str(path/'tb.sv'), '--workdir', str(md/'work'),
                       '--json', str(md/'verdict.json'), '--level', '2', '--clean',
                       '--timeout-compile', '30', '--timeout-elab', '45', '--timeout-sim', '30', '--quiet']
            with (md/'run.log').open('w') as log:
                subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=False)
            result['mutants'][label] = json.loads((md/'verdict.json').read_text())
    result['complete'] = True
    write_json(cached, result)
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--tasks', type=Path, default=TASKS)
    ap.add_argument('--list', type=Path, help='按TXT清单选题')
    ap.add_argument('--out', type=Path, default=ROOT/'dev/runs/dataset-validation/full')
    ap.add_argument('--prefix', default='')
    ap.add_argument('--jobs', type=int, default=4)
    ap.add_argument('--rerun', action='store_true')
    args = ap.parse_args()
    from dev.tools.experiment import TaskSelection, select_tasks
    manifest = select_tasks(TaskSelection(args.tasks, list_path=args.list))
    paths = [Path(row['directory']) for row in manifest.tasks if Path(row['directory']).name.startswith(args.prefix)]
    if not paths:
        ap.error('没有匹配的题目')
    if args.jobs < 1:
        ap.error('--jobs 必须大于0')
    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=True)
    results = []
    with ThreadPoolExecutor(max_workers=args.jobs) as executor:
        pending = {executor.submit(run_one, p, args.out, args.rerun): p for p in paths}
        for f in as_completed(pending):
            result = f.result()
            results.append(result)
            print(f"{len(results)}/{len(paths)} {result['task_id']} reference={result['reference'].get('level')} "
                  f"tool_error={result['reference'].get('tool_error')} "
                  f"mutants={[(k,v.get('verdict',v.get('error'))) for k,v in result['mutants'].items()]}", flush=True)
    write_json(args.out/'summary.json', dict(generated=True, tasks=sorted(results, key=lambda r:r['task_id'])))


if __name__ == '__main__':
    main()
