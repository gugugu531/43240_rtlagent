"""Directory-based entry point; select a registered Python workflow."""
from __future__ import annotations
import argparse
import os
import time
from pathlib import Path
from .core.task import TaskSpec
from .recording.recorder import RecordingConfig
from .runner import RunOptions
from .supervision import Supervisor, RunSpec


def main(argv: list[str] | None = None) -> int:
    started_at = time.monotonic()
    parser = argparse.ArgumentParser(description='registered RTL workflows')
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--top', default=os.environ.get('RTL_TOP', ''))
    parser.add_argument('--workflow', default=os.environ.get('AGENT_WORKFLOW', 'single_generate'))
    parser.add_argument('--import-module', action='append', default=[],
                        help='explicit extension module; repeat for multiple modules')
    parser.add_argument('--deadline-s', type=float, default=os.environ.get('AGENT_DEADLINE_S', '360'))
    parser.add_argument('--reserve-s', type=float, default=os.environ.get('AGENT_RESERVE_S', '20'))
    parser.add_argument('--record-root', type=Path, default=os.environ.get('AGENT_RECORD_ROOT'))
    parser.add_argument('--record-level', choices=('basic', 'full'),
                        default=os.environ.get('AGENT_RECORD_LEVEL', 'full'))
    parser.add_argument('--save-candidates', action='store_true',
                        default=os.environ.get('AGENT_SAVE_CANDIDATES') == '1')
    args = parser.parse_args(argv)
    task = TaskSpec.from_directory(args.input, task_id=os.environ.get('AGENT_TASK_ID'), top=args.top)

    Supervisor().run(RunSpec(task, args.workflow, RunOptions(
        output_dir=args.output, deadline_s=args.deadline_s, reserve_s=args.reserve_s,
        recording=RecordingConfig(args.record_level, args.record_root.resolve() if args.record_root else None),
        save_candidates=args.save_candidates), import_modules=tuple(args.import_module), started_at=started_at))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
