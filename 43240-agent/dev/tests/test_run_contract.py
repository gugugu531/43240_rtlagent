from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest


AGENT_ROOT = Path(__file__).resolve().parents[2]
RUN_SH = AGENT_ROOT / "run.sh"


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

    def _run(self, args, *, cwd: Path, env=None):
        run_env = dict(os.environ) if env is None else env
        run_env["LLM_BACKEND"] = "mock"
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
