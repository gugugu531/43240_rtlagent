from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch


AGENT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(AGENT_ROOT))

from agent.services.processes import ProcessExecutor, ProcessRequest  # noqa: E402
from agent.services.vivado import RtlToolchain  # noqa: E402


class ProcessStatusTests(unittest.TestCase):
    def test_success_failure_and_launch_error_have_distinct_statuses(self):
        with tempfile.TemporaryDirectory() as temp:
            executor = ProcessExecutor()
            success = executor.run(ProcessRequest((sys.executable, "-c", "print('ok')"), temp, 2))
            failure = executor.run(ProcessRequest((sys.executable, "-c", "raise SystemExit(7)"), temp, 2))
            unavailable = executor.run(ProcessRequest((str(Path(temp, "missing-command")),), temp, 2))

        self.assertEqual((success.status, success.rc), ("ok", 0))
        self.assertEqual((failure.status, failure.rc), ("failed", 7))
        self.assertEqual((unavailable.status, unavailable.rc), ("unavailable", -1))


class RtlToolchainTests(unittest.TestCase):
    def test_version_probe_uses_and_cleans_independent_scratch_directory(self):
        from agent.core.config import ToolConfig
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); bin_dir = root / 'bin'; scratch = root / 'scratch'
            bin_dir.mkdir(); scratch.mkdir()
            for name in ('xvlog','xelab','vivado'):
                _write_executable(bin_dir/name, '#!/bin/sh\necho Vivado Simulator v2026.1\ntouch probe.pb\n')
            result = RtlToolchain(config=ToolConfig(bin_dir=str(bin_dir), temp_dir=str(scratch))).identify()
            self.assertTrue(all(t['version']=='2026.1' for t in result['tools'].values()))
            self.assertEqual(list(scratch.iterdir()), [])

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
            self.assertEqual(len(result.log_paths), 1)
            self.assertTrue(Path(result.log_paths[0]).is_file())
            self.assertIn("xvlog-full", Path(result.log_paths[0]).read_text())

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


if __name__ == "__main__":
    unittest.main()
