"""Official judge adapter; task/reference access stays in development code."""
from pathlib import Path
import json
import os
import sys
import shutil
from agent.recording.metrics import MetricResult
from agent.services.processes import ProcessExecutor, ProcessRequest
from agent.recording.artifacts import atomic_write_json, atomic_write_text

REPO = Path(__file__).resolve().parents[4]


class JudgeMetric:
    name, version = 'judge', 1

    def __init__(self, tasks, *, timeout_s=1800, tools=None):
        self.tasks, self.timeout_s, self.tools = tasks, timeout_s, tools

    def collect(self, sample):
        output = sample.output_dir / 'judge'
        output.mkdir(parents=True, exist_ok=True)
        path = output / 'result.json'
        env = dict(os.environ, SELFTEST_KEEP_WORK='1')
        if self.tools:
            env['EDA_TMP'] = self.tools.temp_dir
            if self.tools.bin_dir: env['PATH'] = self.tools.bin_dir + os.pathsep + env.get('PATH', '')
        executor = ProcessExecutor(log_dir=output / 'process_logs')
        request = ProcessRequest((sys.executable, str(REPO / 'selftest/judge.py'),
            '--task', str(self.tasks[sample.task_id]), '--solution', str(sample.output_dir / 'solution.v'),
            '--outdir', str(output), '--json', str(path), '--timeout', str(self.timeout_s)),
            str(REPO), self.timeout_s + 2, env)
        runner = getattr(self, "process_runner", None)
        result = runner(request, output) if runner else executor.run(request)
        if result is None:
            return MetricResult(self.name, self.version, "skipped", {"reason":"cancelled"}, ("judge/process_logs",))
        atomic_write_text(output / 'adapter.log', executor.redactor.copy(result.output))
        try:
            verdict = json.loads(path.read_text())
            if not isinstance(verdict, dict) or 'level' not in verdict: raise ValueError()
        except (OSError, ValueError):
            return MetricResult(self.name, self.version, 'error', {'process_status': result.status}, ('judge/adapter.log',))
        work = verdict.get('work_dir')
        work_root = Path(work).resolve() if work else None
        scratch = Path(self.tools.temp_dir if self.tools else os.environ.get('EDA_TMP','/tmp')).resolve()
        if (work_root and work_root.is_dir() and work_root.is_relative_to(scratch)
                and work_root != scratch and work_root.name.startswith('judge_')):
            for log in work_root.rglob('*'):
                if log.is_file() and (log.suffix == '.log' or log.name == 'verdict.json'):
                    target = output/'logs'/log.relative_to(work_root)
                    target.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copyfile(log,target)
            shutil.rmtree(work_root)
        # The exact official result is preserved. An environment failure is not zero score.
        if verdict.get('tool_error'):
            return MetricResult(self.name, self.version, 'unavailable', {'verdict': verdict}, ('judge/result.json',))
        return MetricResult(self.name, self.version, 'ok', {'verdict': verdict}, ('judge/result.json',))
