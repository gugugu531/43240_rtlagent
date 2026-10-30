"""Official task lifetime and local deployment contracts, using synthetic tools."""

import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from agent.domain.rtl.vivado import executable
from agent.observability.recorder import Recorder
from agent.runtime.budget import Budget
from agent.runtime.process import ProcessManager


ROOT = Path(__file__).resolve().parents[1]


class RuntimeContractTests(unittest.TestCase):
    def test_default_start_ignores_leftover_small_model_setting(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            serve, binaries = root / "serve", root / "bin"
            serve.mkdir()
            binaries.mkdir()
            shutil.copy2(ROOT / "serve/start.sh", serve / "start.sh")
            # Catch accidental small-model startup without loading any model.
            small = serve / "start_verireason.sh"
            small.write_text('#!/bin/bash\ntouch "$SMALL_STARTED"\nexit 9\n')
            small.chmod(0o755)
            for name in ("bash", "dirname", "mkdir", "touch"):
                (binaries / name).symlink_to(shutil.which(name))
            (binaries / "python3").symlink_to(sys.executable)
            for name, body in {
                "setsid": "exit 0",  # Do not start the cleanup daemon in a test.
                "curl": "echo '{\"data\":[{\"id\":\"qwen38-27b-q4-k-m\"}]}'",
            }.items():
                program = binaries / name
                program.write_text("#!/bin/bash\n" + body + "\n")
                program.chmod(0o755)
            marker = root / "small-started"
            result = subprocess.run(
                [str(serve / "start.sh")],
                env={"PATH": str(binaries), "AGENT_TMP": str(root),
                     "EDA_TMP": str(root / "eda"), "VERI_GGUF": "unused-small.gguf",
                     "SMALL_STARTED": str(marker)},
                capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(marker.exists())

    def test_tool_start_failure_and_signal_keep_original_return_codes(self):
        with tempfile.TemporaryDirectory() as directory:
            record = Recorder(directory, level="basic")
            manager = ProcessManager(Budget(10, 0), record)
            try:
                missing = manager.run(["/nonexistent/synthetic-tool"], timeout_s=2)
                self.assertEqual(missing.rc, -1)
                killed = manager.run([sys.executable, "-c", "import os,signal;os.kill(os.getpid(),signal.SIGTERM)"], timeout_s=2)
                self.assertEqual(killed.rc, -signal.SIGTERM)
                self.assertFalse(killed.timed_out)
            finally:
                manager.close()
                record.close()

    def test_bad_cli_does_not_return_previous_answer(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            source, output = work / "in", work / "out"
            source.mkdir()
            output.mkdir()
            (source / "prompt.txt").write_text("Public synthetic task")
            (output / "solution.v").write_text("OLD ANSWER")
            (output / "trace.jsonl").write_text("OLD TRACE")
            result = subprocess.run(
                [str(ROOT / "run.sh"), str(source), str(output), "--invalid-argument"],
                capture_output=True, timeout=10,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((output / "solution.v").read_text(), "")
            self.assertEqual((output / "trace.jsonl").read_text(), "")

    @unittest.skipUnless(sys.platform == "linux", "official Linux task lifecycle")
    def test_tool_timeout_and_normal_exit_reap_descendants(self):
        for wait in (False, True):
            with self.subTest(wait=wait), tempfile.TemporaryDirectory() as directory:
                record = Recorder(directory, level="full")
                manager = ProcessManager(Budget(10, 0), record)
                self.assertTrue(manager.subreaper)
                code = (
                    "import json,os,subprocess,sys,time; "
                    "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']); "
                    "print(json.dumps([os.getpid(),child.pid,os.getpgrp()]),flush=True); "
                    + ("time.sleep(30)" if wait else "")
                )
                try:
                    result = manager.run([sys.executable, "-c", code], timeout_s=0.5)
                    parent, child, pgid = json.loads(result.stdout)
                    self.assertEqual(pgid, os.getpgrp())
                    self.assertEqual(result.timed_out, wait)
                    self.assertFalse(Path(f"/proc/{parent}").exists())
                    self.assertFalse(Path(f"/proc/{child}").exists())
                finally:
                    manager.close()
                    record.close()

    @unittest.skipUnless(sys.platform == "linux", "official Linux task lifecycle")
    def test_outer_group_kill_covers_stopped_agent_and_its_tool(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            record = Recorder(work / "harness", level="basic")
            manager = ProcessManager(Budget(10, 0), record)
            self.assertTrue(manager.subreaper)
            identity = work / "tool.json"
            tool = (
                "import json,os,time; from pathlib import Path; "
                f"Path({str(identity)!r}).write_text(json.dumps([os.getpid(),os.getpgrp()])); "
                "time.sleep(30)"
            )
            agent = (
                "import sys; from agent.observability.recorder import Recorder; "
                "from agent.runtime.budget import Budget; "
                "from agent.runtime.process import ProcessManager; "
                f"r=Recorder({str(work / 'agent')!r}); "
                f"ProcessManager(Budget(30,0),r).run([sys.executable,'-c',{tool!r}],timeout_s=20)"
            )
            proc = subprocess.Popen([sys.executable, "-c", agent], cwd=ROOT,
                                    start_new_session=True)
            tool_pid = None
            try:
                deadline = time.monotonic() + 5
                while not identity.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(identity.exists())
                tool_pid, tool_group = json.loads(identity.read_text())
                self.assertEqual(tool_group, proc.pid)
                os.kill(proc.pid, signal.SIGSTOP)
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=3)
                deadline = time.monotonic() + 3
                while Path(f"/proc/{tool_pid}").exists() and time.monotonic() < deadline:
                    try:
                        os.waitpid(-proc.pid, os.WNOHANG)
                    except ChildProcessError:
                        pass
                    time.sleep(0.01)
                self.assertFalse(Path(f"/proc/{tool_pid}").exists())
            finally:
                for pid in (tool_pid, proc.pid):
                    if pid:
                        try:
                            os.kill(pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                proc.wait(timeout=3)
                if tool_pid:
                    while True:
                        try:
                            os.waitpid(-proc.pid, 0)
                        except ChildProcessError:
                            break
                manager.close()
                record.close()

    @unittest.skipUnless(sys.platform == "linux", "official Linux task lifecycle")
    def test_tool_cleanup_does_not_kill_unrelated_new_child(self):
        with tempfile.TemporaryDirectory() as directory:
            record = Recorder(directory, level="basic")
            manager = ProcessManager(Budget(10, 0), record)
            other = []
            def launch():
                time.sleep(0.1)
                other.append(subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)"]))
            thread = threading.Thread(target=launch)
            thread.start()
            try:
                manager.run([sys.executable, "-c", "import time;time.sleep(30)"], timeout_s=0.4)
                thread.join(timeout=3)
                self.assertTrue(other)
                self.assertIsNone(other[0].poll())
            finally:
                thread.join(timeout=3)
                for proc in other:
                    proc.kill()
                    proc.wait(timeout=3)
                manager.close()
                record.close()

    def test_vivado_uses_official_environment_without_assumed_version(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / "vendor-layout" / "bin" / "xvlog"
            binary.parent.mkdir(parents=True)
            binary.write_text("#!/bin/sh\nexit 0\n")
            binary.chmod(0o755)
            with patch.dict(os.environ, {"PATH": "", "XILINX_VIVADO": str(binary.parent.parent)}, clear=True):
                self.assertEqual(executable("xvlog"), str(binary))
                with patch.dict(os.environ, {"RTL_TOOL_BIN": str(root / "missing")}):
                    self.assertIsNone(executable("xvlog"))

    def test_llama_launcher_preserves_thinking_and_matching_library(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            server = root / "llama-server"
            captured = root / "args.json"
            library = root / "rocblas" / "library"
            library.mkdir(parents=True)
            server.write_text(
                f"#!{sys.executable}\nimport json,os,sys\n"
                f"open({str(captured)!r},'w').write(json.dumps({{'args':sys.argv[1:],'library':os.environ.get('ROCBLAS_TENSILE_LIBPATH')}}))\n"
            )
            server.chmod(0o755)
            weights = root / "synthetic.gguf"
            weights.write_text("synthetic path only; never loaded")
            env = {k: v for k, v in os.environ.items() if k != "ROCBLAS_TENSILE_LIBPATH"}
            env.update(LLAMA_SERVER=str(server), MODEL=str(weights), MTP_MODEL=str(weights))
            subprocess.run([str(ROOT / "serve/llamacpp.sh")], env=env, check=True, timeout=5)
            data = json.loads(captured.read_text())
            self.assertIn("--jinja", data["args"])
            self.assertIn("draft-mtp", data["args"])
            self.assertEqual(data["library"], str(library))
            env["ROCBLAS_TENSILE_LIBPATH"] = "/explicit/library"
            subprocess.run([str(ROOT / "serve/llamacpp.sh")], env=env, check=True, timeout=5)
            self.assertEqual(json.loads(captured.read_text())["library"], "/explicit/library")


if __name__ == "__main__":
    unittest.main()
