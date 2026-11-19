"""本机控制通道和题库边界测试，使用合成目录和独立的运行状态。"""

import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from serve import ui_control
from serve.ui_control import TaskCatalog, local_control, persist_mode


ROOT = Path(ui_control.__file__).resolve().parents[1]
SCRIPT = ROOT / "serve/run_api.sh"


class TaskCatalogTests(unittest.TestCase):
    def setUp(self):
        work = tempfile.TemporaryDirectory()
        self.addCleanup(work.cleanup)
        self.root = Path(work.name) / "tasks"
        self.root.mkdir()
        self.catalog = TaskCatalog(self.root)

    def test_only_regular_prompt_files_are_listed_and_read(self):
        first = self.root / "set" / "alpha"
        first.mkdir(parents=True)
        (first / "prompt.txt").write_bytes("公开题面\r\n".encode())
        (first / "notes.txt").write_text("unrelated")
        (self.root / "empty").mkdir()
        (self.root / "prompt.txt").write_text("root prompt")
        (self.root / "beta").mkdir()
        os.mkfifo(self.root / "beta" / "prompt.txt")
        with patch.object(ui_control, "_read_file", side_effect=AssertionError("列表不读取文件内容")):
            self.assertEqual(self.catalog.list(), [".", "set/alpha"])
        self.assertEqual(self.catalog.prompt("set/alpha"), "公开题面\r\n")
        self.assertEqual(self.catalog.prompt("."), "root prompt")
        for task_id in ("empty", "set/alpha/notes.txt", "beta"):
            with self.subTest(task_id=task_id), self.assertRaises(ValueError):
                self.catalog.prompt(task_id)

    def test_invalid_utf8_missing_root_and_unconfigured_catalog(self):
        (self.root / "prompt.txt").write_bytes(b"\xff")
        with self.assertRaises(ValueError):
            self.catalog.prompt(".")
        self.assertEqual(TaskCatalog(None).list(), [])
        with self.assertRaises(ValueError):
            TaskCatalog(None).prompt("x")
        with self.assertRaises(ValueError):
            TaskCatalog("relative")
        with self.assertRaises(ValueError):
            TaskCatalog(self.root / "missing").list()

    def test_refuses_symlinks_at_each_level_and_noncanonical_ids(self):
        outside = self.root.parent / "other"
        target = outside / "nested"
        target.mkdir(parents=True)
        (target / "prompt.txt").write_text("dummy")
        (self.root / "directory-link").symlink_to(outside, target_is_directory=True)
        (self.root / "file-link").mkdir()
        (self.root / "file-link" / "prompt.txt").symlink_to(target / "prompt.txt")
        self.assertEqual(self.catalog.list(), [])
        for task_id in ("directory-link/nested", "file-link", "", "/etc", str(target), "../other/nested",
                        "x/../../other", "x//y", "x/.", "x/", r"C:\other", "C:/other", "x\0y"):
            with self.subTest(task_id=task_id), self.assertRaises(ValueError):
                self.catalog.prompt(task_id)
        for root in (self.root / "directory-link", self.root / "directory-link" / "nested"):
            with self.subTest(root=root), self.assertRaises(ValueError):
                TaskCatalog(root).list()


@unittest.skipUnless(sys.platform == "linux", "本机控制使用 Linux 的套接字和目录锁")
class ControlTests(unittest.TestCase):
    def setUp(self):
        work = tempfile.TemporaryDirectory()
        self.addCleanup(work.cleanup)
        self.root = Path(work.name)
        clean_env = {"AGENT_TMP": work.name, "API_PORT": "17860", "PATH": os.defpath,
                     "PYTHONDONTWRITEBYTECODE": "1"}
        env = patch.dict(os.environ, clean_env, clear=True)
        env.start()
        self.addCleanup(env.stop)
        self.state = {}

    def dispatch(self, command, value):
        if command == "restore":
            self.state = {"ui": False, "mode": value}
        elif command == "mode":
            persist_mode(value)
            self.state["mode"] = value
        elif command == "ui" and value != "status":
            self.state["ui"] = value == "on"
        return self.state.copy()

    def cli(self, *args, **override):
        return subprocess.run([str(SCRIPT), *args], env=dict(os.environ, **override),
                              capture_output=True, text=True, timeout=8)

    def status_after(self, *args):
        result = self.cli(*args)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_switches_reach_live_handler_and_restart_restores_only_mode(self):
        with local_control(self.dispatch):
            self.assertEqual(self.status_after("ui", "status"), {"ui": False, "mode": "submission"})
            self.assertTrue(self.status_after("ui", "on")["ui"])
            self.assertEqual(self.status_after("mode", "local"), {"ui": True, "mode": "local"})
            self.assertEqual(self.status_after("ui", "off"), {"ui": False, "mode": "local"})
            self.status_after("ui", "on")
            private, = self.root.iterdir()
            for path, mode in ((private, 0o700), (private / "control.sock", 0o600),
                               (private / "mode", 0o600)):
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), mode)
        self.assertNotEqual(self.cli("ui", "on").returncode, 0)
        with local_control(self.dispatch):
            self.assertEqual(self.status_after("ui", "status"), {"ui": False, "mode": "local"})
            self.assertEqual(self.status_after("mode", "submission")["mode"], "submission")

    def test_cli_reports_errors_without_starting_or_targeting_other_instances(self):
        self.assertEqual(self.cli("ui", "toggle").returncode, 2)
        self.assertEqual(self.cli("mode", "local", "extra").returncode, 2)
        self.assertNotEqual(self.cli("mode", "local").returncode, 0)
        self.assertEqual(list(self.root.iterdir()), [])
        with local_control(lambda command, value: {} if command == "restore" else {"error": "busy"}):
            busy = self.cli("mode", "local")
            self.assertEqual(busy.returncode, 1)
            self.assertEqual(json.loads(busy.stderr), {"error": "busy"})
            other = self.root / "another"
            other.mkdir()
            self.assertEqual(self.cli("ui", "on", AGENT_TMP=str(other)).returncode, 1)
            self.assertEqual(self.cli("ui", "on", API_PORT="17861").returncode, 1)
            self.assertEqual(self.cli("ui", "on", API_PORT="../17860").returncode, 1)
            self.assertEqual(list(other.iterdir()), [])

    def test_only_one_owner_accepts_commands_and_old_socket_recovers_after_crash(self):
        process = subprocess.run([sys.executable, "-B", "-c", """
import os
from serve.ui_control import local_control, persist_mode
with local_control(lambda command, value: {}):
    persist_mode("local")
    os._exit(0)
"""], cwd=ROOT, capture_output=True, text=True, timeout=8)
        self.assertEqual(process.returncode, 0, process.stderr)
        private, = self.root.iterdir()
        self.assertTrue((private / "control.sock").is_socket())
        with local_control(self.dispatch):
            unused = Mock()
            with self.assertRaises(RuntimeError), local_control(unused):
                self.fail("重复控制进程获得了目录锁")
            unused.assert_not_called()
            self.assertEqual(self.status_after("ui", "status"), {"ui": False, "mode": "local"})

    def test_failed_mode_write_preserves_existing_mode(self):
        with local_control(self.dispatch):
            self.status_after("mode", "local")
            with patch.object(ui_control.os, "replace", side_effect=OSError("disk unavailable")):
                self.assertEqual(self.cli("mode", "submission").returncode, 1)
            self.assertEqual(self.status_after("ui", "status")["mode"], "local")
        with local_control(self.dispatch):
            self.assertEqual(self.status_after("ui", "status")["mode"], "local")

    def test_corrupt_state_and_redirected_control_paths_fail_closed(self):
        with local_control(self.dispatch):
            persist_mode("local")
        private, = self.root.iterdir()
        saved = private / "mode"
        saved.write_text("invalid")
        unused = Mock()
        with self.assertRaises(ValueError), local_control(unused):
            self.fail("损坏的模式被采用")
        unused.assert_not_called()
        saved.unlink()
        target = self.root / "unrelated"
        target.write_text("dummy")
        saved.symlink_to(target)
        with self.assertRaises(OSError), local_control(unused):
            self.fail("跟随了模式文件链接")
        unused.assert_not_called()
        saved.unlink()
        (private / "control.sock").symlink_to(target)
        with self.assertRaises(ValueError), local_control(self.dispatch):
            self.fail("覆盖了无关的路径")
        self.assertTrue((private / "control.sock").is_symlink())
        self.assertEqual(target.read_text(), "dummy")
        private.chmod(0o755)
        with self.assertRaises(ValueError), local_control(unused):
            self.fail("使用了非私有的控制目录")
        unused.assert_not_called()

    def test_long_scratch_path_works_and_shared_scratch_requires_sticky_bit(self):
        scratch = self.root / ("long" * 40)
        scratch.mkdir()
        with patch.dict(os.environ, {"AGENT_TMP": str(scratch)}):
            scratch.chmod(0o777)
            with self.assertRaises(ValueError), local_control(self.dispatch):
                self.fail("在没有 sticky 位的共享目录中创建了控制端")
            scratch.chmod(0o1777)
            with local_control(self.dispatch):
                self.assertEqual(self.status_after("ui", "on")["mode"], "submission")

    def test_watchdog_allows_local_credentials_only_when_both_are_configured(self):
        # 让依赖检查停在 uvicorn，测试这一路径不拉起服务。
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        for command in ("bash", "dirname", "mkdir", "setsid"):
            (bin_dir / command).symlink_to(shutil.which(command))
        tasks = {"RTLAGENT_UI_TASKS": str(self.root / "synthetic")}
        token = {"RTLAGENT_UI_OPERATOR_TOKEN": "synthetic-local"}
        for settings in ({}, tasks, token):
            with self.subTest(settings=settings):
                result = self.cli("start", PATH=str(bin_dir), **settings)
                self.assertEqual(result.returncode, 1)
                self.assertIn("FPGACHINA_TOKEN is not set", result.stderr)
        configured = self.cli("start", PATH=str(bin_dir), **tasks, **token)
        self.assertIn("required executable not found: uvicorn", configured.stderr)

    def test_watchdog_status_uses_the_selected_port(self):
        default = self.root / "run_api"
        default.mkdir()
        for filename in ("run_api.pid", "serve_api.pid"):
            (default / filename).write_text(str(os.getpid()))
        self.assertEqual(self.cli("status", API_PORT="07860").returncode, 0)
        self.assertEqual(self.cli("status", API_PORT="17860").returncode, 1)
        self.assertEqual(self.cli("status", API_PORT="../invalid").returncode, 2)


if __name__ == "__main__":
    unittest.main()
