from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import stat
import shutil
import sys
from unittest.mock import patch
import subprocess
import tempfile
import time
import unittest


AGENT_ROOT = Path(__file__).resolve().parents[2]
RUN_SH = AGENT_ROOT / "run.sh"
sys.path.insert(0, str(AGENT_ROOT))


class RunContractTests(unittest.TestCase):
    def test_relative_paths_are_resolved_from_callers_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            cwd = Path(temp)
            task = cwd / "task"
            task.mkdir()
            (task / "prompt.txt").write_text(
                "I would like you to implement a module named TopModule with "
                "the following interface.\n - input a\n - output q\n",
                encoding="utf-8",
            )

            result = self._run(["task", "result"], cwd=cwd)

            self.assertEqual(result.returncode, 0, result.stderr)
            solution = cwd / "result" / "solution.v"
            trace = cwd / "result" / "trace.jsonl"
            self.assertTrue(solution.is_file())
            self.assertTrue(trace.is_file())
            self.assertIn("module TopModule", solution.read_text(encoding="utf-8"))
            self._assert_jsonl(trace)
            records = list((cwd / "result" / "records").iterdir())
            self.assertEqual(len(records), 1)
            self.assertTrue((records[0] / "calls/m001/response.txt").is_file())
            self.assertTrue((records[0] / "candidates/c001.v").is_file())
            self.assertFalse((AGENT_ROOT / "result").exists())

    def test_agent_process_failure_still_creates_contract_files(self):
        with tempfile.TemporaryDirectory() as temp:
            cwd = Path(temp)
            task = cwd / "task"
            task.mkdir()
            (task / "prompt.txt").write_text("unused", encoding="utf-8")

            fake_bin = cwd / "bin"
            fake_bin.mkdir()
            fake_python = fake_bin / "python3"
            fake_python.write_text("#!/bin/sh\nexit 7\n", encoding="utf-8")
            fake_python.chmod(
                fake_python.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP
            )
            env = dict(os.environ)
            env["PATH"] = str(fake_bin) + os.pathsep + env.get("PATH", "")

            result = self._run(["task", "result"], cwd=cwd, env=env)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((cwd / "result" / "solution.v").read_text(), "")
            self.assertEqual((cwd / "result" / "trace.jsonl").read_text(), "")
            self.assertIn("agent exited with 7", result.stderr)

    def isolated_path(self, cwd):
        bin_dir = cwd / "isolated_bin"
        bin_dir.mkdir(exist_ok=True)
        for command in ("bash", "dirname", "mkdir", "python3"):
            (bin_dir / command).symlink_to(shutil.which(command))
        return str(bin_dir)

    @unittest.skipUnless(importlib.util.find_spec("fastapi"), "fastapi is not installed")
    def test_http_preserves_records_outside_request_temporary_directory(self):
        from serve import serve_api
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            records = root / "records"
            env = dict(LLM_BACKEND="mock", AGENT_WORKFLOW="single_generate", AGENT_RECORD_ROOT=str(records),
                       AGENT_RECORD_LEVEL="full", PATH=self.isolated_path(root))
            request = serve_api.SolveRequest(task_id="single-test", prompt=
                "I would like you to implement a module named TopModule with "
                "the following interface.\n - input a\n - output q\n")
            with patch.dict(os.environ, env), patch.object(serve_api, "TOKEN", "test-token"), \
                    patch.object(serve_api, "SCRATCH", str(root)):
                solution, trace = serve_api._solve(request, time.monotonic())
            self.assertIn("module TopModule", solution)
            tasks = list(records.glob('*/task.json'))
            self.assertEqual(len(tasks), 1)
            self.assertEqual(json.loads(tasks[0].read_text())['task_id'], 'single-test')
            self.assertTrue((tasks[0].parent/'calls/m001/response.txt').is_file())
            self.assertEqual(set(root.iterdir()), {records, root / "isolated_bin"})
            events = [json.loads(line) for line in trace.splitlines()]
            done = next(e for e in events if e['tool'] == 'agent' and e['event'] == 'done')
            self.assertEqual(done['candidate_id'], 'c001')
            self.assertTrue(any(e.get('candidate_id') == 'c001' and e.get('source_call_id') == 'm001'
                                for e in events))

    def _run(self, args, *, cwd: Path, env=None):
        run_env = dict(os.environ) if env is None else env
        if env is None:
            run_env["PATH"] = self.isolated_path(cwd)
        run_env.pop("AGENT_RECORD_ROOT", None)
        run_env["AGENT_RECORD_LEVEL"] = "full"
        run_env["LLM_BACKEND"] = "mock"
        run_env["AGENT_WORKFLOW"] = "single_generate"
        return subprocess.run(
            [str(RUN_SH), *args],
            cwd=cwd,
            env=run_env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    def _assert_jsonl(self, path: Path) -> None:
        lines = path.read_text(encoding="utf-8").splitlines()
        self.assertTrue(lines)
        for line in lines:
            self.assertIsInstance(json.loads(line), dict)


if __name__ == "__main__":
    unittest.main()
