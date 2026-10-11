"""Frozen task selection, isolated solve processes and optional metrics."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
import hashlib
import importlib.util
import json
import os
import re
import signal
import threading
import time
import uuid
import sys
from agent.recording.artifacts import atomic_write_json, atomic_write_text
from agent.core.configuration import ConfigError, ResolvedConfig, positive, string_list
from agent.recording.metrics import CompletedSample, ModelMetric, RuntimeMetric, collect_metrics
from agent.recording.redaction import Redactor
from agent.services.processes import ProcessExecutor, ProcessRequest
from .metrics.judge import JudgeMetric

ROOT = Path(__file__).resolve().parents[2]
REPO = ROOT.parent


@dataclass(frozen=True)
class TaskSelection:
    root: Path
    ids: tuple[str, ...] | None = None
    list_path: Path | None = None
    exclude_path: Path | None = None


@dataclass(frozen=True)
class TaskManifest:
    tasks: tuple[dict, ...]
    excluded: tuple[dict, ...]
    root: Path
    digest: str

    def public_dict(self):
        return {'root': str(self.root), 'tasks': self.tasks, 'excluded': self.excluded, 'digest': self.digest}


@dataclass(frozen=True)
class ExperimentConfig:
    selection: TaskSelection
    modes: tuple[str, ...] = ('agent',)
    samples: int = 1
    solve_jobs: int = 1
    metric_jobs: int = 1
    metrics: tuple[str, ...] = ('runtime', 'model')
    output_root: Path = ROOT / 'dev/runs'
    tag: str = 'experiment'
    judge_timeout_s: float = 1800


@dataclass(frozen=True)
class ResolvedExperiment:
    runtime: ResolvedConfig
    experiment: ExperimentConfig
    manifest: TaskManifest


@dataclass(frozen=True)
class SampleSpec:
    task: dict
    mode: str
    index: int


@dataclass(frozen=True)
class SampleResult:
    task_id: str
    mode: str
    index: int
    output_dir: Path
    solve: dict
    metrics: tuple = ()

    def public_dict(self):
        return {'task_id': self.task_id, 'mode': self.mode, 'index': self.index,
                'output_dir': str(self.output_dir), 'solve': self.solve,
                'metrics': [m.public_dict() for m in self.metrics]}


@dataclass(frozen=True)
class ExperimentResult:
    output_dir: Path
    status: str
    samples: tuple[SampleResult, ...]


def _names(path):
    try:
        return tuple(line.split('#', 1)[0].strip() for line in path.read_text().splitlines()
                     if line.split('#', 1)[0].strip())
    except (OSError, UnicodeError): raise ConfigError('cannot read task list') from None


def task_hashes(directory):
    return {name: hashlib.sha256((directory/name).read_bytes() if (directory/name).is_file() else b'').hexdigest()
            for name in ('prompt.txt', 'interface.txt')}


def select_tasks(selection: TaskSelection) -> TaskManifest:
    root = selection.root.resolve()
    if not root.is_dir(): raise ConfigError('tasks.root must be an existing directory')
    if selection.ids is not None and selection.list_path is not None:
        raise ConfigError('tasks.ids and tasks.list are mutually exclusive')
    if selection.ids is not None: names = selection.ids
    elif selection.list_path is not None: names = _names(selection.list_path)
    else: names = tuple(sorted(p.name for p in root.iterdir() if p.is_dir() and (p/'prompt.txt').is_file()))
    if not names or len(set(names)) != len(names): raise ConfigError('task selection must be nonempty and unique')
    excluded_names = set(_names(selection.exclude_path)) if selection.exclude_path else set()
    selected, excluded = [], []
    for name in names:
        if not re.fullmatch(r'[A-Za-z0-9_-]+', name): raise ConfigError('task ids must be directory names')
        directory = (root/name).resolve()
        if not directory.is_relative_to(root) or not (directory/'prompt.txt').is_file():
            raise ConfigError('selected task does not exist or escapes tasks.root')
        if name in excluded_names:
            excluded.append({'task_id': name, 'reason': 'exclude_list', 'source': str(selection.exclude_path)})
        else: selected.append({'task_id': name, 'directory': str(directory), 'inputs': task_hashes(directory)})
    if not selected: raise ConfigError('all selected tasks were excluded')
    digest = hashlib.sha256(json.dumps(selected, sort_keys=True).encode()).hexdigest()
    return TaskManifest(tuple(selected), tuple(excluded), root, digest)


def parse_experiment(config, overrides=None):
    from dataclasses import replace
    raw = config.values.get('experiment', {})
    tasks = raw.get('tasks', {})
    root = tasks.get('root')
    if not isinstance(root, str) or not root: raise ConfigError('experiment.tasks.root is required')
    ids = string_list(tasks['ids'], 'tasks.ids') if 'ids' in tasks else None
    defaults = ROOT / 'dev/configs/exclude.txt'
    selection = TaskSelection(Path(root), ids, Path(tasks['list']) if tasks.get('list') else None,
                              Path(tasks['exclude']) if tasks.get('exclude') else defaults if defaults.is_file() else None)
    values = dict(modes=string_list(raw.get('modes', ['agent']), 'experiment.modes'),
                  metrics=string_list(raw.get('metrics', ['runtime', 'model']), 'experiment.metrics'),
                  output_root=Path(raw.get('output_root', ROOT/'dev/runs')),
                  tag=raw.get('tag', 'experiment'), judge_timeout_s=positive(raw.get('judge_timeout_s', 1800), 'judge_timeout_s'))
    for key in ('samples', 'solve_jobs', 'metric_jobs'):
        val = raw.get(key, 1)
        if type(val) is not int or val < 1: raise ConfigError(f'experiment.{key} must be a positive integer')
        values[key] = val
    result = ExperimentConfig(selection, **values)
    if overrides:
        task = overrides.pop('task', None)
        if task is not None: result = replace(result, selection=replace(result.selection, ids=(task,), list_path=None))
        result = replace(result, **overrides)
    for key in ('samples','solve_jobs','metric_jobs'):
        if type(getattr(result,key)) is not int or getattr(result,key) < 1: raise ConfigError(f'{key} must be a positive integer')
    if not isinstance(result.tag,str) or not re.fullmatch(r'[a-z][a-z0-9_-]*', result.tag): raise ConfigError('experiment.tag must be a lowercase identifier')
    if not result.modes or any(m not in ('agent', 'baseline') for m in result.modes): raise ConfigError('modes must select agent or baseline')
    if len(set(result.modes)) != len(result.modes): raise ConfigError('modes must be unique')
    if len(set(result.metrics)) != len(result.metrics): raise ConfigError('metrics must be unique')
    if any(m not in ('runtime', 'model', 'judge') for m in result.metrics): raise ConfigError('unknown metric')
    if 'baseline' in result.modes and config.agent.services.model.backend == 'mock':
        raise ConfigError('baseline requires a real HTTP model service; mock applies only to agent')
    return result


def build_sample_plan(manifest, config):
    return tuple(SampleSpec(task, mode, index) for task in manifest.tasks
                 for index in range(config.samples) for mode in config.modes)


def snapshot_sources(destination, config):
    """Explicit code/config allowlist; no environment, answers, weights or logs."""
    files = set()
    for base in (ROOT/'agent', ROOT/'serve', ROOT/'skill', ROOT/'dev/tools'):
        files.update(p for p in base.rglob('*') if p.is_file() and p.suffix in ('.py', '.md', '.txt')
                     and '__pycache__' not in p.parts)
    files.update(ROOT/name for name in ('run.sh','baseline.py','run_baseline.sh','requirements.txt'))
    files.update((ROOT/'config').glob('*.yaml'))
    incomplete = []
    for module in config.agent.workflow.imports:
        # Do not import user components in the scheduler. Only inspect known local paths.
        path = ROOT.joinpath(*module.split('.')).with_suffix('.py')
        if path.is_file(): files.add(path)
        else: incomplete.append(module)
    redactor = Redactor([config.agent.services.model.api_key])
    entries = []
    for path in sorted(files):
        if not path.is_file(): continue
        text = path.read_text(encoding='utf-8')
        # Source text is not a log: regex-based prose redaction would corrupt Python.
        # Mask known secrets and literal secret assignments, and flag altered snapshots.
        sanitized = text
        for secret in sorted(redactor.secrets,key=len,reverse=True):
            sanitized = sanitized.replace(secret,'[redacted]')
        sanitized = re.sub(r'(?im)^(\s*(?:api_key|token|password|secret|cookie|RC_COOKIE|RC_API_KEY|LLM_API_KEY)\s*=\s*)([\'"])([^\n]*?)\2',
                           r'\1\2[redacted]\2',sanitized)
        relative = path.relative_to(ROOT)
        target = destination / relative
        atomic_write_text(target, sanitized)
        entries.append({'path':str(relative), 'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                        'snapshot_sha256':hashlib.sha256(sanitized.encode()).hexdigest(), 'redacted':sanitized!=text})
    info = {'files':entries, 'unresolved_extensions':incomplete, 'complete':not incomplete and not any(e['redacted'] for e in entries)}
    atomic_write_json(destination/'manifest.json', info)
    return info


def summarize_experiment(samples, *, planned=0, status='completed'):
    result = {'status':status, 'planned_samples':planned, 'completed_samples':len(samples), 'modes':{}, 'cancelled_samples':sum(s.solve.get('status')=='cancelled' for s in samples)}
    spec = importlib.util.spec_from_file_location('official_score', REPO/'selftest/score.py')
    official = importlib.util.module_from_spec(spec); spec.loader.exec_module(official)
    for mode in sorted({s.mode for s in samples}):
        rows = [s for s in samples if s.mode == mode]
        metrics = {}
        for row in rows:
            for metric in row.metrics:
                metrics.setdefault(metric.name, []).append(metric)
        entry = {'samples':len(rows), 'solve_wall_s_sum':sum(r.solve.get('wall_s', 0) for r in rows),
                 'metric_statuses':{name:{state:sum(m.status==state for m in values) for state in sorted({m.status for m in values})}
                                    for name,values in metrics.items()}}
        judge_rows = {}
        for row in rows:
            metric = next((m for m in row.metrics if m.name=='judge'), None)
            if metric is None: continue
            verdict = metric.values.get('verdict')
            if verdict is None:
                verdict = {'tool_error':f'metric_{metric.status}', 'elapsed_s':0}
            judge_rows.setdefault(row.task_id, []).append(verdict)
        if judge_rows: entry['judge'] = official.summarize(judge_rows)
        result['modes'][mode] = entry
    a = result['modes'].get('agent', {}).get('judge'); b = result['modes'].get('baseline', {}).get('judge')
    if a and b:
        # Avoid misleading gains when interruptions/environment exclusions change paired coverage.
        valid = lambda mode: {(s.task_id,s.index) for s in samples if s.mode==mode and
                              any(m.name=='judge' and m.status=='ok' for m in s.metrics)}
        comparable = valid('agent') == valid('baseline') and bool(valid('agent'))
        result['comparison'] = {'paired_coverage':comparable,
             'gain':a['set_score']/b['set_score'] if comparable and b['set_score'] else None,
             'baseline_timeout_s':300, 'note':'single_generate 对齐 baseline RTL 请求与提取；预算与实际条件见逐样本记录'}
    return result


class ExperimentRunner:
    def __init__(self, *, write_notes=True):
        self.write_notes = write_notes
        self._secrets = []
        self.cancelled = threading.Event()
        self._active = {}
        self._lock = threading.Lock()

    def cancel(self, reason='cancelled'):
        self.cancelled.set()

    def _process(self, request, output):
        executor = ProcessExecutor(log_dir=output/'process_logs')
        executor.redactor.add_secrets(self._secrets)
        with self._lock: self._active[id(executor)] = executor
        try:
            if self.cancelled.is_set(): return None
            identity = executor.start(request)
            while True:
                if self.cancelled.is_set():
                    executor.cancel_all(time.monotonic()+0.5)
                    return None
                result = executor.poll(identity)
                if result is not None: return result
                time.sleep(.01)
        finally:
            executor.cancel_all(time.monotonic()+0.5)
            with self._lock: self._active.pop(id(executor), None)

    def _solve(self, sample, config, run_dir):
        name = sample.task['task_id']; output = run_dir/'samples'/sample.mode/name/f's{sample.index}'
        output.mkdir(parents=True, exist_ok=True)
        started = time.monotonic(); agent = config.agent
        env = dict(os.environ)
        # Effective config is frozen; ambient supported overrides cannot reapply in children.
        from agent.core.configuration import ENV_FIELDS
        for key in (*ENV_FIELDS, 'MODEL_NAME', 'AGENT_CONFIG','AGENT_TMP','EDA_TMP','TRACK_TMP'): env.pop(key, None)
        env['AGENT_TASK_ID'] = name
        # Freeze the experiment's model for both modes; baseline ignores LLM_MODEL.
        env['MODEL_NAME'] = agent.services.model.model
        if task_hashes(Path(sample.task['directory'])) != sample.task['inputs']:
            raise ConfigError('task inputs changed after selection')
        command = (str(ROOT/'run.sh'), sample.task['directory'], str(output), '--config', str(run_dir/'resolved.yaml'), '--config-parent', str(run_dir/'config.json'))
        if sample.mode == 'baseline':
            model = agent.services.model
            env.update(LLM_BASE_URL=model.base_url)
            command = (str(ROOT/'run_baseline.sh'), sample.task['directory'], str(output))
        process = self._process(ProcessRequest(command, str(ROOT), agent.runtime.deadline_s, env,
                                                terminate_grace_s=min(.5, agent.runtime.deadline_s*.1)), output)
        solve = {'wall_s':time.monotonic()-started, 'status':'cancelled' if process is None else process.status,
                 'rc':None if process is None else process.rc, 'mode':sample.mode,
                 'service_timeout_s':300 if sample.mode=='baseline' else agent.services.model.timeout_s}
        for name in ('solution.v','trace.jsonl'):
            if not (output/name).exists(): atomic_write_text(output/name,'')
        from agent.recording.metrics import read_events
        events, _ = read_events(output/'trace.jsonl')
        supervision = next((e for e in reversed(events) if e.get('tool')=='supervisor'), {})
        solve['stop_reason'] = supervision.get('stop_reason')
        solve['workflow_status'] = supervision.get('status')
        atomic_write_json(output/'solve.json', solve)
        if process is not None: atomic_write_text(output/'run.log', Redactor([agent.services.model.api_key]).copy(process.output))
        if sample.mode=='baseline': atomic_write_json(output/'config.json', {'mode':'baseline','service':agent.services.model.public_dict(), 'request_timeout_s':300})
        return CompletedSample(sample.task['task_id'], sample.mode, sample.index, output, solve)

    def run(self, plan, config: ResolvedExperiment):
        config, experiment, manifest = config.runtime, config.experiment, config.manifest
        self._secrets = [config.agent.services.model.api_key]
        import yaml
        from agent.core.metadata import git_metadata
        run_dir = experiment.output_root / f'{time.strftime("%Y%m%d-%H%M%S")}-{experiment.tag}-{uuid.uuid4().hex[:8]}'
        run_dir.mkdir(parents=True, exist_ok=False)
        public = config.public_dict()
        atomic_write_json(run_dir/'config.json', public)
        atomic_write_json(run_dir/'tasks.json', manifest.public_dict())
        effective = dict(config.values)
        effective.pop('experiment', None)
        # YAML is an internal runtime transport, contains only the validated effective config.
        atomic_write_text(run_dir/'resolved.yaml', yaml.safe_dump(effective, sort_keys=False))
        source = snapshot_sources(run_dir/'source', config)
        atomic_write_json(run_dir/'experiment.json', {'status':'running', 'planned_samples':len(plan),
                          'git':git_metadata(str(ROOT)), 'source_complete':source['complete'],
                          'experiment':{'modes':experiment.modes,'samples':experiment.samples,
                           'solve_jobs':experiment.solve_jobs,'metric_jobs':experiment.metric_jobs,
                           'metrics':experiment.metrics,'judge_timeout_s':experiment.judge_timeout_s}})
        tasks = {t['task_id']:Path(t['directory']) for t in manifest.tasks}
        collectors = {'runtime':RuntimeMetric(), 'model':ModelMetric(),
                      'judge':JudgeMetric(tasks, timeout_s=experiment.judge_timeout_s, tools=config.agent.services.tools)}
        results = []; previous = {}
        if threading.current_thread() is threading.main_thread():
            for sig in (signal.SIGTERM,signal.SIGINT):
                previous[sig] = signal.signal(sig, lambda signum, frame:self.cancel())
        def evaluate(sample):
            selected = [] if self.cancelled.is_set() else [collectors[n] for n in experiment.metrics]
            # Cancellation also owns the judge process (the adapter accepts the same executor callback).
            collectors['judge'].process_runner = self._process
            metrics = collect_metrics(sample, selected)
            if self.cancelled.is_set():
                from agent.recording.metrics import MetricResult
                present = {m.name for m in metrics}
                metrics += tuple(MetricResult(n,1,'skipped',{'reason':'cancelled'}) for n in experiment.metrics if n not in present)
            atomic_write_json(sample.output_dir/'metrics.json', [m.public_dict() for m in metrics])
            return SampleResult(sample.task_id,sample.mode,sample.index,sample.output_dir,sample.solve,metrics)
        try:
            with ThreadPoolExecutor(max_workers=experiment.solve_jobs) as solves, ThreadPoolExecutor(max_workers=experiment.metric_jobs) as metrics:
                pending = {solves.submit(self._solve,s,config,run_dir):s for s in plan}
                evaluated = []
                for future in as_completed(pending):
                    spec = pending[future]
                    try: sample = future.result()
                    except Exception as exc:
                        output = run_dir/'samples'/spec.mode/spec.task['task_id']/f's{spec.index}'
                        output.mkdir(parents=True,exist_ok=True)
                        solve = {'status':'error','error_type':type(exc).__name__,'wall_s':0}
                        atomic_write_json(output/'solve.json',solve)
                        atomic_write_text(output/'solution.v',''); atomic_write_text(output/'trace.jsonl','')
                        sample = CompletedSample(spec.task['task_id'],spec.mode,spec.index,output,solve)
                    evaluated.append(metrics.submit(evaluate,sample))
                for future in as_completed(evaluated):
                    result = future.result(); results.append(result)
                    atomic_write_json(run_dir/'metrics.json', [s.public_dict() for s in results])
        finally:
            for sig,handler in previous.items(): signal.signal(sig,handler)
        status = 'cancelled' if self.cancelled.is_set() else 'completed'
        summary = summarize_experiment(results,planned=len(plan),status=status)
        atomic_write_json(run_dir/'summary.json',summary)
        lines = ['# 实验结果','',f'状态：{status}。完成 {len(results)}/{len(plan)} 个样本。','',
                 '本文件由 dev/tools/run.py 生成，不要手改。逐样本证据见 samples/。','',
                 '| 模式 | 样本 | 官方等级分布 |','| --- | ---: | --- |']
        for mode,entry in summary['modes'].items(): lines.append(f"| {mode} | {entry['samples']} | {entry.get('judge',{}).get('level_counts','未启用')} |")
        atomic_write_text(run_dir/'summary.md','\n'.join(lines)+'\n')
        metadata = json.loads((run_dir/'experiment.json').read_text())
        metadata.update(status=status, completed_samples=len(results), summary='summary.json')
        atomic_write_json(run_dir/'experiment.json', metadata)
        if self.write_notes:
            notes = ROOT/'dev/docs/experiments'; notes.mkdir(parents=True,exist_ok=True)
            note = notes/(run_dir.name+'.md')
            atomic_write_text(note, f'# {run_dir.name}\n\n原始记录：`{run_dir}`。\n\n'
                              '<!-- BEGIN:results -->\n'+ '\n'.join(lines[2:])+'\n<!-- END:results -->\n\n'
                              '## 改动与假设\n\n待填写。\n\n## 结论\n\n待填写。\n')
        return ExperimentResult(run_dir,status,tuple(results))
