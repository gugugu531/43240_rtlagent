#!/usr/bin/env python3
"""Stage an explicit runtime file set and verify it without development files."""
from __future__ import annotations
import argparse
import ast
from dataclasses import dataclass, asdict
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import shlex
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from agent.recording.artifacts import atomic_write_json
from agent.services.processes import ProcessExecutor, ProcessRequest

FILES = ('run.sh', 'run_baseline.sh', 'baseline.py', 'requirements.txt',
         'manifest.json', 'REPORT.md', 'README.md', 'Dockerfile', '.dockerignore')
DIRECTORIES = ('agent', 'config', 'skill', 'serve', 'model')
REQUIRED = (*FILES, 'config/example.yaml', 'agent/main.py', 'serve/serve_api.py',
            'serve/vllm.sh', 'serve/start.sh', 'model/MODEL.md')
FIXED_NAMES = {'README.md', 'REPORT.md', 'MODEL.md', 'SKILL.md', 'Dockerfile', '.dockerignore'}


@dataclass(frozen=True)
class CheckReport:
    errors: tuple[str, ...]
    files: tuple[str, ...]

    @property
    def ok(self): return not self.errors


@dataclass(frozen=True)
class SubmissionManifest:
    root: str
    files: tuple[dict, ...]


@dataclass(frozen=True)
class SmokeResult:
    ok: bool
    process_status: str
    rc: int | None
    solution_bytes: int
    stop_reason: str | None


def _files(root):
    found = []
    for name in FILES:
        p = root / name
        if p.exists() or p.is_symlink(): found.append(p)
    for name in DIRECTORIES:
        directory = root / name
        if directory.is_symlink(): found.append(directory); continue
        if directory.is_dir():
            found.extend(p for p in directory.rglob('*') if
                         '__pycache__' not in p.parts and p.suffix not in ('.pyc', '.pyo') and
                         (p.is_file() or p.is_symlink()))
    return tuple(sorted(found))


def check_submission_layout(root: Path) -> CheckReport:
    root = Path(root).resolve(); errors = []
    for name in REQUIRED:
        if not (root / name).is_file(): errors.append(f'missing required file: {name}')
    files = _files(root)
    for path in files:
        relative = path.relative_to(root).as_posix()
        if path.is_symlink() or any(p.is_symlink() for p in path.parents if p != root and p.is_relative_to(root)):
            errors.append(f'symlink is not a submission file: {relative}'); continue
        for part in Path(relative).parts:
            if part not in FIXED_NAMES and not re.fullmatch(r'[a-z0-9_-]+(?:\.[a-z0-9_-]+)*', part):
                errors.append(f'invalid submission name: {relative}'); break
        if path.name in ('remote.env', 'env.sh', '.env', 'cloud.state', 'cloud_known_hosts') or path.suffix in ('.log', '.jou'):
            errors.append(f'local configuration or log in submission: {relative}')
        if path.suffix == '.py':
            try: tree = ast.parse(path.read_text())
            except (SyntaxError, UnicodeError):
                errors.append(f'invalid Python source: {relative}'); continue
            for node in ast.walk(tree):
                names = [a.name for a in node.names] if isinstance(node, ast.Import) else ([node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
                if any(n.split('.')[0] in ('dev', 'selftest') for n in names):
                    errors.append(f'development import in submission: {relative}'); break
    # Validate the current simple COPY declarations, including destination paths.
    docker = root / 'Dockerfile'
    copied = set()
    if docker.is_file():
        for line in docker.read_text().splitlines():
            if not line.strip().startswith('COPY '): continue
            try: parts = shlex.split(line.strip())[1:]
            except ValueError:
                errors.append('invalid Docker COPY declaration'); continue
            if len(parts) < 2: continue
            sources, destination = parts[:-1], Path(parts[-1])
            for source in sources:
                if source.startswith('--'): continue
                source_path = Path(source)
                for name in (p.relative_to(root).as_posix() for p in files):
                    candidate = Path(name)
                    if candidate == source_path:
                        target = destination / source_path.name
                    elif (root/source_path).is_dir() and candidate.is_relative_to(source_path):
                        target = destination / candidate.relative_to(source_path)
                    else: continue
                    if target == candidate: copied.add(name)
        expected = set(p.relative_to(root).as_posix() for p in files) - {'Dockerfile', '.dockerignore', 'README.md'}
        for name in sorted(expected - copied):
            errors.append(f'file absent from Docker COPY destinations: {name}')
    example = root.parent / 'example'
    for name in ('baseline.py', 'run_baseline.sh'):
        if (example/name).is_file() and (root/name).is_file() and (example/name).read_bytes() != (root/name).read_bytes():
            errors.append(f'official baseline changed: {name}')
    return CheckReport(tuple(errors), tuple(p.relative_to(root).as_posix() for p in files))


def stage_submission(root: Path, destination: Path) -> SubmissionManifest:
    root = Path(root).resolve(); destination = Path(destination).resolve()
    if destination == root or destination.is_relative_to(root) or root.is_relative_to(destination):
        raise ValueError('staging directory must be outside the source tree')
    if destination.exists(): raise FileExistsError('staging directory must not exist')
    report = check_submission_layout(root)
    if not report.ok: raise ValueError('submission layout has errors: ' + '; '.join(report.errors))
    destination.mkdir(parents=True)
    entries = []
    for name in report.files:
        source = root / name; target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        entries.append({'path':name, 'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
                        'bytes':target.stat().st_size})
    manifest = SubmissionManifest(str(destination), tuple(entries))
    atomic_write_json(destination.parent / (destination.name + '-manifest.json'), asdict(manifest))
    return manifest


def smoke_submission(staged_root: Path, task_dir: Path, output_dir: Path) -> SmokeResult:
    staged_root = Path(staged_root).resolve(); task_dir = Path(task_dir).resolve(); output_dir = Path(output_dir).resolve()
    if output_dir == staged_root or output_dir.is_relative_to(staged_root):
        raise ValueError('smoke output must be outside the staged submission')
    from agent.core.configuration import ENV_FIELDS
    env = {k:v for k,v in os.environ.items() if k not in (*ENV_FIELDS, 'AGENT_CONFIG', 'AGENT_CALLER_CWD',
           'AGENT_TMP', 'EDA_TMP', 'TRACK_TMP', 'RTL_TOP', 'AGENT_TASK_ID', 'PYTHONPATH')}
    env.update(LLM_BACKEND='mock', AGENT_WORKFLOW='single_generate')
    process = ProcessExecutor(log_dir=output_dir/'process_logs').run(ProcessRequest(
        (str(staged_root/'run.sh'), str(task_dir), str(output_dir)), str(staged_root), 30, env))
    events = []
    try:
        events = [json.loads(line) for line in (output_dir/'trace.jsonl').read_text().splitlines() if line.strip()]
    except (OSError, ValueError): pass
    supervisor = next((e for e in reversed(events) if e.get('tool') == 'supervisor'), {})
    solution = output_dir/'solution.v'; size = solution.stat().st_size if solution.exists() else 0
    ok = process.status == 'ok' and process.rc == 0 and size > 0 and supervisor.get('status') == 'completed' and not supervisor.get('unreaped_pids')
    result = SmokeResult(ok, process.status, process.rc, size, supervisor.get('stop_reason'))
    atomic_write_json(output_dir/'smoke.json', asdict(result))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description='检查并暂存不含 dev 的方案文件；不发布或构建镜像')
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--stage', type=Path)
    parser.add_argument('--task', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    report = check_submission_layout(args.root)
    print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
    if not report.ok: return 2
    if args.task and (not args.stage or not args.output): parser.error('--task requires --stage and --output')
    if args.stage:
        stage_submission(args.root, args.stage)
        if args.task:
            result = smoke_submission(args.stage, args.task, args.output)
            print(json.dumps(asdict(result), ensure_ascii=False)); return 0 if result.ok else 2
    return 0


if __name__ == '__main__': raise SystemExit(main())
