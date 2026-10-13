#!/usr/bin/env python3
"""Continue cancelled diagnostic samples through the unchanged unified runner."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from dataclasses import replace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from agent.core.configuration import load_config, resolve_config
from agent.recording.artifacts import atomic_write_json
from dev.tools.combine_runs import combine
from dev.tools.experiment import (ExperimentRunner, ResolvedExperiment, build_sample_plan,
                                  parse_experiment, select_tasks)
from dev.tools.generation_diagnostic import digest
from dev.tools.generation_sweep import (REMOTE, audits_for_run, preflight, runner_environment,
                                       session_settings, write_report)
from dev.tools.remote.model_gateway import PROFILES

PROFILE = 'think-on-sampled'


def pending_keys(prior):
    """Retry cancellations only, never low grades or infrastructure/model errors."""
    rows = json.loads((prior/'metrics.json').read_text())
    settings = json.loads((prior/'experiment.json').read_text())
    if settings['status'] != 'cancelled':
        raise ValueError('requires a cancelled run')
    tasks = json.loads((prior/'tasks.json').read_text())['tasks']
    expected = {(t['task_id'], m, i) for t in tasks
                for m in settings['experiment']['modes']
                for i in range(settings['experiment']['samples'])}
    found = set(); pending = set()
    for row in rows:
        key = (row['task_id'], row['mode'], row['index'])
        if key in found or key not in expected:
            raise ValueError('duplicate or unexpected sample')
        found.add(key)
        metrics = {m['name']: m for m in row['metrics']}
        if row['solve']['status'] == 'cancelled':
            if any(m['status'] != 'skipped' for m in metrics.values()):
                raise ValueError('cancelled sample with partial metrics requires manual review')
            pending.add(key)
        else:
            model = metrics.get('model', {})
            judge = metrics.get('judge', {})
            verdict = judge.get('values', {}).get('verdict', {})
            if (row['solve']['status'] != 'ok' or model.get('status') != 'ok'
                    or model['values'].get('failed', 0) or model['values'].get('unfinished', 0)
                    or judge.get('status') != 'ok' or verdict.get('level') not in (0, 1, 2, 3)
                    or verdict.get('tool_error')):
                raise ValueError('non-cancellation failure requires manual review, not resampling')
    if found != expected or not pending:
        raise ValueError('incomplete manifest or nothing to continue')
    return pending


def origin_hashes(previous_session, prior):
    paths = [previous_session/'state.json', previous_session/'think-on-sampled/profile.json',
             previous_session/'think-on-sampled/runner.log']
    paths += [prior/name for name in ('experiment.json', 'metrics.json', 'tasks.json',
                                      'resolved.yaml', 'source/manifest.json')]
    paths += sorted((previous_session/'think-on-sampled/gateway').glob('*.json'))
    paths += sorted(prior.glob('samples/*/*/s0/solution.v'))
    paths += sorted(prior.glob('samples/*/*/s0/records/*/calls/*/*.json'))
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def verify(state):
    config, profiles = session_settings(state)
    if state['status'] != 'prepared' or digest(preflight(config, profiles)) != digest(state['preflight']):
        raise ValueError('prepared preflight differs')
    previous = Path(state['previous_session']); prior = Path(state['prior_run'])
    if origin_hashes(previous, prior) != state['origin_hashes']:
        raise ValueError('original evidence changed')
    if pending_keys(prior) != {tuple(k) for k in state['pending']}:
        raise ValueError('pending sample set changed')


def prepare(previous, session):
    old = json.loads((previous/'state.json').read_text())
    if (old['status'] != 'incomplete' or len(old['arms']) != 1
            or old['arms'][0]['profile'] != 'think-on-greedy'
            or old['current_profile'] != PROFILE):
        raise ValueError('requires interrupted second arm, with completed greedy arm')
    config, profiles = session_settings(old)
    if profiles != ('think-on-greedy', PROFILE) or digest(preflight(config, profiles)) != digest(old['preflight']):
        raise ValueError('original frozen preflight differs')
    prior = Path((previous/PROFILE/'runner.log').read_text().splitlines()[-2])
    if json.loads((previous/PROFILE/'profile.json').read_text()) != PROFILES[PROFILE]:
        raise ValueError('original profile differs')
    pending = pending_keys(prior)
    session.mkdir(parents=True, exist_ok=False)
    state = dict(status='prepared', created_at=time.time(), config_path=str(config),
                 profile_order=list(profiles), preflight=old['preflight'], arms=old['arms'],
                 current_profile=PROFILE, previous_session=str(previous), prior_run=str(prior),
                 pending=sorted(pending), origin_hashes=origin_hashes(previous, prior),
                 whole_session_limit_s=0)
    atomic_write_json(session/'state.json', state)
    write_report(session, state)
    print(json.dumps({'pending': sorted(pending), 'session': str(session)}, ensure_ascii=False))


def run(session):
    state = json.loads((session/'state.json').read_text()); verify(state)
    previous = Path(state['previous_session']); prior = Path(state['prior_run'])
    pending = {tuple(k) for k in state['pending']}
    arm = session/PROFILE; arm.mkdir()
    atomic_write_json(arm/'profile.json', PROFILES[PROFILE])
    env = runner_environment(PROFILE, arm/'gateway')
    os.environ.clear(); os.environ.update(env)
    try:
        subprocess.run(['bash', str(REMOTE/'tunnel.sh'), 'down'], cwd=ROOT, check=True)
        subprocess.run(['bash', str(REMOTE/'tunnel.sh'), 'up'], cwd=ROOT, check=True)
        subprocess.run(['bash', str(REMOTE/'remote_vllm.sh'), 'wait'], cwd=ROOT, check=True)
        config = resolve_config(load_config(Path(state['config_path'])), env={})
        experiment = replace(parse_experiment(config), tag='gen11-think-on-sampled-resume')
        manifest = select_tasks(experiment.selection)
        plan = tuple(s for s in build_sample_plan(manifest, experiment)
                     if (s.task['task_id'], s.mode, s.index) in pending)
        if len(plan) != len(pending):
            raise ValueError('continuation plan differs')
        state.update(status='running', started_at=time.time())
        atomic_write_json(session/'state.json', state); write_report(session, state)
        result = ExperimentRunner().run(plan, ResolvedExperiment(config, experiment, manifest))
        state['continuation_run'] = str(result.output_dir)
        if result.status != 'completed':
            raise ValueError('continuation cancelled; original samples retained')
        summary, samples, provenance = combine(prior, result.output_dir)
        kept = {(s.task_id, s.mode, s.index) for s in samples} - pending
        discarded = []
        audit = audits_for_run(previous/PROFILE, prior, sample_keys=kept, discarded_requests=discarded)
        # Only an unfinished baseline request belonging to a cancelled sample may be discarded.
        from baseline import SYS
        allowed = set()
        for s in plan:
            if s.mode == 'baseline':
                directory = Path(s.task['directory'])
                prompt = (directory/'prompt.txt').read_text()
                if (directory/'interface.txt').exists():
                    prompt += '\n\nInterface:\n' + (directory/'interface.txt').read_text()
                allowed.add(digest([{'role': 'system', 'content': SYS['rtl']}, {'role': 'user', 'content': prompt}]))
        for row in discarded:
            if row['response'] is not None or digest(row['request']['original']['messages']) not in allowed:
                raise ValueError('unexpected discarded request; manual evidence review required')
            if any(row['request']['effective'].get(k) != v for k, v in PROFILES[PROFILE].items()):
                raise ValueError('discarded request profile differs')
        audit += audits_for_run(arm, result.output_dir, sample_keys=pending)
        for row in audit:
            if any(row['effective'].get(k) != v for k, v in PROFILES[PROFILE].items()):
                raise ValueError('effective profile differs')
        first = {f"{r['mode']}/{r['task_id']}": r['messages_sha256'] for r in audit if r['call_index'] == 0}
        greedy_audit = json.loads(Path(state['arms'][0]['audit_summary']).read_text())
        reference = {f"{r['mode']}/{r['task_id']}": r['messages_sha256'] for r in greedy_audit if r['call_index'] == 0}
        if len(first) != 22 or first != reference:
            raise ValueError('first messages differ across arms')
        destination = session/'combined-sampled'; destination.mkdir()
        atomic_write_json(destination/'summary.json', summary)
        atomic_write_json(destination/'metrics.json', [s.public_dict() for s in samples])
        atomic_write_json(destination/'provenance.json', provenance)
        atomic_write_json(arm/'audit-summary.json', audit)
        atomic_write_json(arm/'discarded-requests.json', discarded)
        atomic_write_json(destination/'generation-profile.json', {
            'kind': 'development_gateway_override_not_official_sampling', 'profile': PROFILE,
            'settings': PROFILES[PROFILE], 'all_calls_audited': True,
            'first_messages_sha256': first, 'session': str(session),
            'source_gateway_dirs': [str(previous/PROFILE/'gateway'), str(arm/'gateway')],
            'discarded_unfinished_requests': len(discarded)})
        state['arms'].append(dict(profile=PROFILE, run=str(destination), summary=summary,
                                  audit_summary=str(arm/'audit-summary.json')))
        state.update(status='completed', finished_at=time.time(), first_messages_verified=True)
        print(str(result.output_dir), 'completed', sep='\n', flush=True)
    except BaseException as exc:
        state.update(status='incomplete', error_type=type(exc).__name__, error=str(exc), finished_at=time.time())
        raise
    finally:
        atomic_write_json(session/'state.json', state); write_report(session, state)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'verify', 'run'])
    parser.add_argument('session', type=Path)
    parser.add_argument('--previous', type=Path)
    args = parser.parse_args(); session = args.session.resolve()
    if args.command == 'prepare':
        if args.previous is None:
            parser.error('prepare requires --previous')
        prepare(args.previous.resolve(), session)
    elif args.command == 'verify':
        verify(json.loads((session/'state.json').read_text()))
        print('frozen source, original evidence and cancelled-only plan verified', flush=True)
    else:
        run(session)


if __name__ == '__main__':
    main()
