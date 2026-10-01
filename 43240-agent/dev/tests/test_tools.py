from __future__ import annotations

import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import patch


AGENT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(AGENT_ROOT))

from agent.tools import RtlToolchain, run_command  # noqa: E402


class CommandRunnerTests(unittest.TestCase):
    def test_success_failure_and_launch_error_have_distinct_statuses(self):
        with tempfile.TemporaryDirectory() as temp:
            success = run_command(
                "test", [sys.executable, "-c", "print('ok')"], temp, 2
            )
            failure = run_command(
                "test", [sys.executable, "-c", "raise SystemExit(7)"], temp, 2
            )
            unavailable = run_command(
                "test", [str(Path(temp, "missing-command"))], temp, 2
            )

        self.assertEqual((success.status, success.rc), ("ok", 0))
        self.assertEqual((failure.status, failure.rc), ("failed", 7))
        self.assertEqual((unavailable.status, unavailable.rc), ("unavailable", -1))

    def test_timeout_terminates_parent_and_child_processes(self):
        with tempfile.TemporaryDirectory() as temp:
            child_pid_path = Path(temp, "child.pid")
            code = (
                "import pathlib, signal, subprocess, sys, time\n"
                "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                "child = subprocess.Popen([sys.executable, '-c', "
                "'import signal, time; "
                "signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)'])\n"
                f"pathlib.Path({str(child_pid_path)!r}).write_text(str(child.pid))\n"
                "time.sleep(30)\n"
            )
            result = run_command(
                "test", [sys.executable, "-c", code], temp, 0.2,
                terminate_grace_s=0.05,
            )
            child_pid = int(child_pid_path.read_text())

            deadline = time.monotonic() + 1.0
            while _pid_is_running(child_pid) and time.monotonic() < deadline:
                time.sleep(0.02)

        self.assertEqual(result.status, "timeout")
        self.assertEqual(result.rc, 124)
        self.assertFalse(_pid_is_running(child_pid))

    def test_summary_is_separate_from_optional_full_log(self):
        with tempfile.TemporaryDirectory() as temp:
            full_log = str(Path(temp, "full.log"))
            code = "\n".join([
                "for i in range(80):",
                "    print(f'ordinary line {i}: ' + 'x' * 80)",
            ])
            result = run_command(
                "test", [sys.executable, "-c", code], temp, 2,
                full_log_path=full_log,
            )

            saved = Path(full_log).read_text()

        self.assertEqual(result.status, "ok")
        self.assertLessEqual(len(result.summary), 2100)
        self.assertIn("ordinary line 0", saved)
        self.assertIn("ordinary line 79", saved)
        self.assertNotIn("ordinary line 0", result.summary)


class RtlToolchainTests(unittest.TestCase):
    def test_lint_timeout_covers_both_commands(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bin_dir = root / "bin"
            scratch = root / "scratch"
            bin_dir.mkdir()
            scratch.mkdir()
            _write_executable(bin_dir / "xvlog", "#!/bin/sh\nsleep 0.15\n")
            _write_executable(bin_dir / "xelab", "#!/bin/sh\nsleep 30\n")
            _write_executable(bin_dir / "vivado", "#!/bin/sh\nexit 0\n")
            env = {
                "PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", ""),
                "AGENT_TMP": str(scratch),
            }
            started = time.monotonic()
            with patch.dict(os.environ, env, clear=False):
                result = RtlToolchain().lint(
                    "module TopModule; endmodule", "TopModule", 0.3
                )
            elapsed = time.monotonic() - started

        self.assertEqual(result.status, "timeout")
        self.assertEqual(len(result.command), 2)
        # One extra second is the deliberate SIGTERM grace period.
        self.assertLess(elapsed, 1.7)

    def test_repeated_runs_clean_independent_work_directories(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bin_dir = root / "bin"
            scratch = root / "scratch"
            bin_dir.mkdir()
            scratch.mkdir()
            _write_executable(bin_dir / "xvlog", "#!/bin/sh\necho xvlog-ok\n")
            _write_executable(bin_dir / "xelab", "#!/bin/sh\necho xelab-ok\n")
            _write_executable(
                bin_dir / "vivado", "#!/bin/sh\necho 'Synthesis finished'\n"
            )
            env = {
                "PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", ""),
                "AGENT_TMP": str(scratch),
            }
            with patch.dict(os.environ, env, clear=False):
                os.environ.pop("AGENT_KEEP_WORK", None)
                tools = RtlToolchain()
                for _ in range(4):
                    lint = tools.lint("module TopModule; endmodule", "TopModule", 2)
                    synth = tools.synth("module TopModule; endmodule", "TopModule", 2)
                    self.assertEqual(lint.status, "ok")
                    self.assertEqual(synth.status, "ok")
                    self.assertIsNone(lint.work_dir)
                    self.assertIsNone(synth.work_dir)

            self.assertEqual(list(scratch.iterdir()), [])

    def test_debug_mode_retains_work_directory_and_full_log(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bin_dir = root / "bin"
            scratch = root / "scratch"
            bin_dir.mkdir()
            scratch.mkdir()
            _write_executable(bin_dir / "xvlog", "#!/bin/sh\necho xvlog-full\n")
            _write_executable(bin_dir / "xelab", "#!/bin/sh\necho xelab-full\n")
            _write_executable(
                bin_dir / "vivado", "#!/bin/sh\necho 'Synthesis finished'\n"
            )
            env = {
                "PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", ""),
                "AGENT_TMP": str(scratch),
                "AGENT_KEEP_WORK": "1",
            }
            with patch.dict(os.environ, env, clear=False):
                result = RtlToolchain().lint(
                    "module TopModule; endmodule", "TopModule", 2
                )

            self.assertEqual(result.status, "ok")
            self.assertIsNotNone(result.work_dir)
            self.assertIsNotNone(result.full_log_path)
            self.assertTrue(Path(result.full_log_path or "").is_file())
            self.assertIn("xvlog-full", Path(result.full_log_path or "").read_text())

    def test_invalid_top_is_rejected_before_creating_work_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bin_dir = root / "bin"
            scratch = root / "scratch"
            bin_dir.mkdir()
            scratch.mkdir()
            for name in ("xvlog", "xelab", "vivado"):
                _write_executable(bin_dir / name, "#!/bin/sh\nexit 0\n")
            env = {
                "PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", ""),
                "AGENT_TMP": str(scratch),
            }
            with patch.dict(os.environ, env, clear=False):
                result = RtlToolchain().synth(
                    "module TopModule; endmodule", "TopModule; exec bad", 2
                )

            self.assertEqual(result.status, "failed")
            self.assertEqual(result.rc, 2)
            self.assertEqual(result.command, ())
            self.assertEqual(list(scratch.iterdir()), [])


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(0o755)


def _pid_is_running(pid: int) -> bool:
    stat = Path(f"/proc/{pid}/stat")
    try:
        state = stat.read_text().split()[2]
    except (FileNotFoundError, IndexError, OSError):
        return False
    return state != "Z"


if __name__ == "__main__":
    unittest.main()
