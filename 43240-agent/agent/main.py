"""Competition directory entry point using the shared configuration contract."""
from __future__ import annotations
import argparse
import os
import time
from pathlib import Path
from agent.core.task import TaskSpec
from agent.core.configuration import load_config, resolve_config, build_run_spec, RunOverrides, ConfigError
from agent.core.supervision import Supervisor


def main(argv: list[str] | None = None) -> int:
    started_at = time.monotonic()
    parser = argparse.ArgumentParser(description='registered RTL workflows')
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--config', type=Path, default=os.environ.get('AGENT_CONFIG'))
    parser.add_argument('--config-parent', type=Path, help='parent experiment configuration evidence')
    parser.add_argument('--top', default=os.environ.get('RTL_TOP', ''))
    parser.add_argument('--workflow')
    parser.add_argument('--import-module', action='append', default=None)
    parser.add_argument('--deadline-s', type=float)
    parser.add_argument('--hard-deadline-s', type=float)
    parser.add_argument('--reserve-s', type=float)
    parser.add_argument('--record-root', type=Path)
    parser.add_argument('--record-level', choices=('basic', 'full'))
    args = parser.parse_args(argv)
    caller = Path(os.environ.get("AGENT_CALLER_CWD", os.getcwd()))
    for name in ("config", "record_root", "config_parent"):
        value = getattr(args, name)
        if value is not None and not value.is_absolute():
            setattr(args, name, (caller / value).resolve())
    fields = {'workflow': 'workflow.type', 'import_module': 'imports', 'deadline_s': 'runtime.deadline_s',
              'reserve_s': 'runtime.reserve_s', 'record_root': 'runtime.recording.root',
              'record_level': 'runtime.recording.level'}
    overrides = RunOverrides({target: getattr(args, name) for name, target in fields.items()
                              if getattr(args, name) is not None})
    try:
        config = resolve_config(load_config(args.config), env=os.environ, overrides=overrides)
        task = TaskSpec.from_directory(args.input, task_id=os.environ.get('AGENT_TASK_ID'), top=args.top)
        spec = build_run_spec(task, config, output_dir=args.output, started_at=started_at,
                              hard_deadline_s=args.hard_deadline_s)
        if args.config_parent:
            spec.configuration['parent_config'] = str(args.config_parent.resolve())
    except Exception as exc:
        # No user values or parser exception strings enter the mandatory failure trace.
        from agent.recording.artifacts import atomic_write_text, atomic_write_json
        from agent.recording.recorder import RunRecorder
        atomic_write_text(args.output / 'solution.v', '')
        atomic_write_json(args.output / 'selection.json', {'candidate_id': None})
        recorder = RunRecorder(args.output)
        try:
            recorder.write_event('agent', 'error', error_type=type(exc).__name__, reason='configuration_or_entry_error',
                                 excerpt=str(exc) if isinstance(exc, ConfigError) else 'entry preparation failed')
            recorder.write_event('agent', 'done', candidate_id=None, code_hash=None, bytes=0,
                                 status='error', stop_reason='configuration_or_entry_error')
        finally:
            recorder.close()
        return 0
    Supervisor().run(spec)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
