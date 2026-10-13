#!/usr/bin/env python3
"""Combine valid samples from a paused run and its continuation, without rerunning."""
from pathlib import Path
import argparse
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from agent.recording.artifacts import atomic_write_json
from agent.recording.metrics import MetricResult
from dev.tools.experiment import SampleResult, summarize_experiment


def combine(prior, continuation):
    old = json.loads((prior/'experiment.json').read_text())
    new = json.loads((continuation/'experiment.json').read_text())
    if old['status'] != 'cancelled' or new['status'] != 'completed':
        raise ValueError('requires a cancelled original and a completed continuation')
    if (prior/'resolved.yaml').read_bytes() != (continuation/'resolved.yaml').read_bytes():
        raise ValueError('effective agent configurations differ')
    def runtime_sources(run):
        entries = json.loads((run/'source/manifest.json').read_text())['files']
        return {e['path']: e['sha256'] for e in entries
                if e['path'].startswith(('agent/', 'config/', 'skill/'))
                or e['path'] in ('run.sh', 'baseline.py', 'run_baseline.sh',
                                 'requirements.txt', 'serve/vllm.sh')}
    if runtime_sources(prior) != runtime_sources(continuation):
        raise ValueError('runtime source hashes differ')
    tasks = {t['task_id']: t['inputs'] for t in json.loads((prior/'tasks.json').read_text())['tasks']}
    for t in json.loads((continuation/'tasks.json').read_text())['tasks']:
        if tasks.get(t['task_id']) != t['inputs']:
            raise ValueError('task input hashes differ')
    settings = old['experiment']
    expected = {(task, mode, index) for task in tasks for mode in settings['modes']
                for index in range(settings['samples'])}
    selected = {}; skipped = []; provenance = []
    for run in (prior, continuation):
        for row in json.loads((run/'metrics.json').read_text()):
            key = (row['task_id'], row['mode'], row['index'])
            metrics = {m['name']: m for m in row['metrics']}
            model = metrics.get('model', {})
            judge = metrics.get('judge', {})
            verdict = judge.get('values', {}).get('verdict', {})
            usable = (row['solve'].get('status') == 'ok'
                      and model.get('status') == 'ok'
                      and not model['values'].get('failed', 0)
                      and not model['values'].get('unfinished', 0)
                      and judge.get('status') == 'ok'
                      and verdict.get('level') in (0, 1, 2, 3)
                      and not verdict.get('tool_error'))
            if not usable:
                skipped.append({'run': run.name, 'sample': list(key)})
                continue
            if key not in expected or key in selected:
                raise ValueError('unexpected or duplicate valid sample')
            selected[key] = SampleResult(row['task_id'], row['mode'], row['index'],
                                        Path(row['output_dir']), row['solve'],
                                        tuple(MetricResult(**m) for m in row['metrics']))
            provenance.append({'run': run.name, 'sample': list(key),
                               'output_dir': row['output_dir']})
    if set(selected) != expected:
        raise ValueError('combined coverage is incomplete')
    samples = list(selected.values())
    summary = summarize_experiment(samples, planned=len(expected), status='completed')
    if not summary['comparison']['full_comparison_valid']:
        raise ValueError('comparison is not valid')
    summary['aggregation'] = {'kind': 'combined_summary_not_new_execution',
                              'runs': [prior.name, continuation.name],
                              'tool_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                              'runtime_source_hashes_verified': True,
                              'task_input_hashes_verified': True}
    return summary, samples, {'selected': provenance, 'skipped': skipped}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('prior', type=Path)
    parser.add_argument('continuation', type=Path)
    args = parser.parse_args()
    summary, samples, provenance = combine(args.prior, args.continuation)
    destination = args.continuation/'combined'
    destination.mkdir(exist_ok=False)
    atomic_write_json(destination/'summary.json', summary)
    atomic_write_json(destination/'metrics.json', [s.public_dict() for s in samples])
    atomic_write_json(destination/'provenance.json', provenance)
    print(destination)
    print(json.dumps(summary['comparison'], ensure_ascii=False))


if __name__ == '__main__':
    main()
