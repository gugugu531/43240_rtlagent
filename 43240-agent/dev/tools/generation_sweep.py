#!/usr/bin/env python3
"""Run frozen five/eleven-task generation settings through the unified runner."""
from pathlib import Path
import argparse
import json
import os
import subprocess
import sys
import time
import signal

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from agent.core.configuration import load_config, resolve_config, ENV_FIELDS
from agent.recording.artifacts import atomic_write_json, atomic_write_text
from dev.tools.experiment import parse_experiment, select_tasks, task_hashes
from dev.tools.generation_diagnostic import digest, classify_response
from dev.tools.remote.model_gateway import PROFILES

PRIOR = ROOT/'dev/runs/20261012-225403-autodl-qwen3-8b-a-fixed-quick34-460c1d2a'
CONFIG = ROOT/'dev/configs/generation-diagnostic-five.yaml'
CONFIG_ELEVEN = ROOT/'dev/configs/generation-diagnostic-eleven.yaml'
REMOTE = ROOT/'dev/tools/remote'


def session_settings(state):
    config_path = Path(state.get('config_path', str(CONFIG))).resolve()
    profiles = tuple(state.get('profile_order', list(PROFILES)))
    if not profiles or len(set(profiles)) != len(profiles) or any(p not in PROFILES for p in profiles):
        raise ValueError('require unique known profiles')
    return config_path, profiles


def runner_environment(profile, audit_dir):
    env = dict(os.environ)
    # YAML is frozen; do not let user-manager environment silently override it.
    for key in (*ENV_FIELDS, 'MODEL_NAME', 'AGENT_CONFIG', 'AGENT_TMP', 'EDA_TMP', 'TRACK_TMP'):
        env.pop(key, None)
    env.update(MODEL_GATEWAY_PROFILE=profile, MODEL_GATEWAY_AUDIT_DIR=str(audit_dir))
    return env


def preflight(config_path=CONFIG, profiles=None):
    import hashlib
    config_path = Path(config_path).resolve()
    profiles = tuple(PROFILES) if profiles is None else tuple(profiles)
    session_settings({'config_path': str(config_path), 'profile_order': profiles})
    approved = {CONFIG.resolve(): 5, CONFIG_ELEVEN.resolve(): 11}
    if config_path not in approved:
        raise ValueError('requires a predeclared five/eleven-task config')
    source = json.loads((PRIOR/'source/manifest.json').read_text())['files']
    verified = {}
    for item in source:
        name = item['path']
        if name.startswith(('agent/', 'config/', 'skill/')) or name in (
                'baseline.py', 'run_baseline.sh', 'run.sh', 'serve/vllm.sh', 'requirements.txt'):
            actual = hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
            if actual != item['sha256']:
                raise ValueError(f'frozen runtime source changed: {name}')
            verified[name] = actual
    config = resolve_config(load_config(config_path), env={})
    experiment = parse_experiment(config)
    tasks = select_tasks(experiment.selection)
    original = {t['task_id']: t['inputs'] for t in json.loads((PRIOR/'tasks.json').read_text())['tasks']}
    if (len(tasks.tasks) != approved[config_path] or tasks.excluded
            or experiment.samples != 1 or experiment.solve_jobs != 1 or experiment.metric_jobs != 1
            or tuple(experiment.modes) != ('agent', 'baseline')
            or set(experiment.metrics) != {'runtime', 'model', 'judge'}
            or config.agent.workflow.type != 'evidence_repair'
            or config.agent.runtime.deadline_s != 360 or config.agent.runtime.reserve_s != 20
            or config.agent.services.model.timeout_s != 300
            or config.agent.services.model.backend != 'openai'
            or config.agent.services.model.model != 'Qwen3-8B'
            or config.agent.services.model.base_url != 'http://127.0.0.1:18000/v1'):
        raise ValueError('diagnostic selection or budgets changed')
    for task in tasks.tasks:
        if task_hashes(Path(task['directory'])) != original[task['task_id']]:
            raise ValueError('task input changed')
    return {'runtime_hashes': verified, 'tasks': tasks.public_dict(),
            'profiles': {p: PROFILES[p] for p in profiles},
            'config_sha256': hashlib.sha256(config_path.read_bytes()).hexdigest()}


def audits_for_run(arm, run, *, sample_keys=None, discarded_requests=None):
    """Associate wire evidence to tasks by exact first message / response ID."""
    tasks = json.loads((run/'tasks.json').read_text())['tasks']
    raw = []
    for reqpath in sorted((arm/'gateway').glob('*.request.json')):
        request = json.loads(reqpath.read_text())
        response_path = reqpath.with_name(reqpath.name.replace('.request.', '.response.'))
        response = json.loads(response_path.read_text()) if response_path.exists() else None
        body = json.loads(response['raw_text']) if response is not None else None
        if request['original']['messages'] != request['effective']['messages']:
            raise ValueError('gateway changed messages')
        raw.append((request, response, body))
    expected = []
    from baseline import SYS
    for task in tasks:
        task_dir = Path(task['directory'])
        prompt = (task_dir/'prompt.txt').read_text()
        interface = (task_dir/'interface.txt').read_text() if (task_dir/'interface.txt').exists() else ''
        if interface:
            prompt += '\n\nInterface:\n' + interface
        if sample_keys is None or (task['task_id'], 'baseline', 0) in sample_keys:
            expected.append((task['task_id'], 'baseline', 0,
                             [{'role': 'system', 'content': SYS['rtl']}, {'role': 'user', 'content': prompt}], None))
        if sample_keys is not None and (task['task_id'], 'agent', 0) not in sample_keys:
            continue
        sample = run/'samples/agent'/task['task_id']/'s0'
        for path in sorted(sample.glob('records/*/calls/*/request.json')):
            response = json.loads((path.parent/'response.json').read_text())
            request = json.loads(path.read_text())
            expected.append((task['task_id'], 'agent', int(path.parent.name[1:]) - 1,
                             request['messages'], response['id']))
    result = []
    used = set()
    for task, mode, index, messages, response_id in expected:
        matches = [(i, req, res, body) for i, (req, res, body) in enumerate(raw)
                   if digest(req['original']['messages']) == digest(messages)
                   and (response_id is None or (body is not None and body.get('id') == response_id))]
        if len(matches) != 1 or matches[0][0] in used:
            raise ValueError('gateway evidence cannot be uniquely assigned')
        i, req, res, body = matches[0]
        if res is None or res['status'] != 200 or body is None or 'choices' not in body:
            raise ValueError('gateway upstream failure; do not silently resample')
        used.add(i)
        detail = classify_response(body)
        detail.update(task_id=task, mode=mode, call_index=index,
                      messages_sha256=digest(messages), effective={k: v for k, v in req['effective'].items() if k != 'messages'},
                      gateway_attempts=res['attempts'], elapsed_s=res['elapsed_s'], response_id=body['id'])
        result.append(detail)
    if len(used) != len(raw) and discarded_requests is None:
        raise ValueError('unexpected gateway requests')
    if discarded_requests is not None:
        for i, (req, res, body) in enumerate(raw):
            if i not in used:
                discarded_requests.append({'request': req, 'response': res})
    return result


def run_session(session):
    state = json.loads((session/'state.json').read_text())
    config_path, profiles = session_settings(state)
    task_count = len(state['preflight']['tasks']['tasks'])
    first_messages = None
    try:
        for profile in profiles:
            # Recheck frozen source before each arm, not just at session start.
            current = preflight(config_path, profiles)
            if digest(current) != digest(state['preflight']):
                raise ValueError('experiment preflight changed during session')
            arm = session/profile
            arm.mkdir()
            state.update(current_profile=profile, status='running')
            atomic_write_json(session/'state.json', state)
            write_report(session, state)
            atomic_write_json(arm/'profile.json', PROFILES[profile])
            env = runner_environment(profile, arm/'gateway')
            subprocess.run(['bash', str(REMOTE/'tunnel.sh'), 'down'], cwd=ROOT, check=True)
            subprocess.run(['bash', str(REMOTE/'tunnel.sh'), 'up'], cwd=ROOT, env=env, check=True)
            subprocess.run(['bash', str(REMOTE/'remote_vllm.sh'), 'wait'], cwd=ROOT, check=True)
            print(f'arm started: {profile}', flush=True)
            with (arm/'runner.log').open('w') as log:
                process = subprocess.run([sys.executable, str(ROOT/'dev/tools/run.py'),
                    '--config', str(config_path), '--tag', f'gen{task_count}-{profile}'], cwd=ROOT,
                    env=env, stdout=log, stderr=subprocess.STDOUT)
            output = (arm/'runner.log').read_text().splitlines()
            if process.returncode != 0 or len(output) < 2 or output[-1] != 'completed':
                raise ValueError('arm cancelled or runner failed; see runner.log')
            run = Path(output[-2])
            summary = json.loads((run/'summary.json').read_text())
            if not summary['comparison']['full_comparison_valid']:
                raise ValueError('invalid paired arm; original failures retained')
            audit = audits_for_run(arm, run)
            first = {f"{r['mode']}/{r['task_id']}": r['messages_sha256'] for r in audit if r['call_index'] == 0}
            if len(first) != task_count * 2 or (first_messages is not None and first != first_messages):
                raise ValueError('first-generation messages differ across arms')
            first_messages = first
            for row in audit:
                if any(row['effective'].get(k) != v for k, v in PROFILES[profile].items()):
                    raise ValueError('effective profile differs')
            atomic_write_json(arm/'audit-summary.json', audit)
            atomic_write_json(run/'generation-profile.json', {
                'kind': 'development_gateway_override_not_official_sampling',
                'profile': profile, 'settings': PROFILES[profile],
                'audit_dir': str(arm/'gateway'), 'session': str(session),
                'first_messages_sha256': first, 'all_calls_audited': True})
            state['arms'].append({'profile': profile, 'run': str(run), 'summary': summary,
                                  'audit_summary': str(arm/'audit-summary.json')})
            atomic_write_json(session/'state.json', state)
            write_report(session, state)
            print(f'arm completed: {profile}: {run}', flush=True)
        state.update(status='completed', finished_at=time.time(), first_messages_verified=True)
    except BaseException as exc:
        state.update(status='incomplete', error_type=type(exc).__name__, error=str(exc), finished_at=time.time())
        raise
    finally:
        atomic_write_json(session/'state.json', state)
        write_report(session, state)


def write_report(session, state):
    task_count = len(state['preflight']['tasks']['tasks'])
    _, profiles = session_settings(state)
    planned = task_count * 2 * len(profiles)
    completed = task_count * 2 * len(state['arms'])
    generator = 'generation_resume.py' if state.get('previous_session') else 'generation_sweep.py'
    lines = [f'# {task_count} 题 thinking / 采样诊断结果', '',
             f'由 `dev/tools/{generator} run <会话目录>` 生成，不要手改。',
             f"状态：{state['status']}。原始会话：`{session}`。", '',
             f"已完整汇总 {completed}/{planned} 次求解；当前设置：{state.get('current_profile', '尚未开始')}。在途组的部分成绩尚未计入本表。",
             f'每组 {task_count} 题、双方各 1 样本；固定各自提示、单次 8192 输出 tokens、300 秒单次上限、360 秒单题预算。',
             '采样组覆盖了官方 baseline 的参数，属于开发对照，不是官方固定采样成绩。', '',
             '| 设置 | 模式 | L0/L1/L2/L3 | 系数均值 | 截断/调用 | 输出 tokens | 求解秒 |',
             '| --- | --- | --- | ---: | ---: | ---: | ---: |']
    grades = {}
    for arm in state['arms']:
        run = Path(arm['run'])
        rows = json.loads((run/'metrics.json').read_text())
        grades[arm['profile']] = {}
        for mode in ('agent', 'baseline'):
            selected = [r for r in rows if r['mode'] == mode]
            levels = [0]*4
            truncated = calls = tokens = 0
            wall = 0
            for r in selected:
                metrics = {m['name']: m['values'] for m in r['metrics']}
                level = metrics['judge']['verdict']['level']
                levels[level] += 1
                grades[arm['profile']][f"{mode}/{r['task_id']}"] = level
                truncated += metrics['model']['truncated']
                calls += metrics['model']['attempts']
                tokens += metrics['model']['completion_tokens']['known_total']
                wall += r['solve']['wall_s']
            score = sum(n*c for n,c in zip(levels, (0,.2,.7,1))) / len(selected)
            lines.append(f"| {arm['profile']} | {mode} | {'/'.join(map(str,levels))} | {score:.4f} | {truncated}/{calls} | {tokens} | {wall:.2f} |")
    if grades:
        lines.extend(['', '| 模式/题目 | ' + ' | '.join(grades) + ' |',
                      '| --- | ' + ' | '.join('---' for _ in grades) + ' |'])
        for key in sorted(next(iter(grades.values()))):
            lines.append('| ' + key + ' | ' + ' | '.join(f'L{g[key]}' for g in grades.values()) + ' |')
    lines.extend(['', '生成设置的实际值与逐调用完整 RTL/思考截断分类见各组 audit-summary.json。',
                  '开/关 thinking 应比较同一采样下的 on/off 组；采样配方比较 think-on-greedy 与 think-on-sampled，不是 temperature 单因素实验。',
                  '选题基于先前失败，且每组仅 1 个样本，不支持整体提升或稳定性结论；不替换旧 quick-34 结果。', ''])
    if state.get('previous_session'):
        lines.extend(['## 中断恢复与来源', '',
                      f"旧会话：`{state['previous_session']}`；旧会话状态和原始成绩未改写。",
                      f"本会话仅补 {len(state['pending'])} 个取消样本，保留旧有效结果；整轮无固定时长截止。",
                      '推荐采样组的合并摘要不是一次连续执行；逐样本来源见 combined-sampled/provenance.json。',
                      '旧中断请求不计作完成，单独保存在 think-on-sampled/discarded-requests.json。', ''])
    atomic_write_text(session/'README.md', '\n'.join(lines))
    atomic_write_text(ROOT/'dev/docs/experiments'/f'{session.name}.md', '\n'.join(lines))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'run', 'environment', 'verify'])
    parser.add_argument('session', type=Path)
    parser.add_argument('--config', type=Path, default=CONFIG)
    parser.add_argument('--profiles', nargs='+', choices=tuple(PROFILES))
    args = parser.parse_args()
    if args.command == 'verify':
        state = json.loads((args.session/'state.json').read_text())
        config_path, profiles = session_settings(state)
        if state['status'] != 'prepared' or digest(preflight(config_path, profiles)) != digest(state['preflight']):
            raise ValueError('prepared experiment preflight differs')
        print('frozen runtime, selection and profiles verified', flush=True)
    elif args.command == 'environment':
        value = json.load(sys.stdin)
        atomic_write_json(args.session/'remote-environment.json', value)
        if value['vllm'] != '0.11.0' or value['torch'] != '2.8.0+cu128':
            raise ValueError('remote package versions changed')
        reference = json.loads((ROOT/'dev/runs/20261013-generation-diagnostic-five-retry1/remote-environment.json').read_text())
        if value['hashes'] != reference['hashes'] or value['model_path'] != reference['model_path']:
            raise ValueError('remote model weights/tokenizer changed')
    elif args.command == 'prepare':
        config_path = args.config.resolve()
        profiles = args.profiles or (['think-on-greedy', 'think-on-sampled']
                                    if config_path == CONFIG_ELEVEN.resolve() else list(PROFILES))
        checked = preflight(config_path, profiles)
        args.session.mkdir(parents=True, exist_ok=False)
        state = {'status': 'prepared', 'created_at': time.time(), 'config_path': str(config_path),
                 'profile_order': profiles, 'preflight': checked, 'arms': []}
        atomic_write_json(args.session/'state.json', state)
        write_report(args.session, state)
    else:
        def stop_requested(signum, frame):
            raise KeyboardInterrupt('session stop requested')
        signal.signal(signal.SIGTERM, stop_requested)
        run_session(args.session)


if __name__ == '__main__':
    main()
