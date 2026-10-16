"""Offline startup tests with disposable model/CLI stand-ins."""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class StartupTests(unittest.TestCase):
    def test_vllm_budget_model_name_and_both_logging_flags(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for directory in ('vllm', 'vllm/entrypoints', 'vllm/entrypoints/openai'):
                (root/directory).mkdir(exist_ok=True)
                (root/directory/'__init__.py').write_text('')
            (root/'torch.py').write_text('class cuda:\n'
                ' @staticmethod\n def get_device_properties(index):\n'
                '  return type("GPU", (), {"total_memory":48*2**30})()\n')
            (root/'vllm/entrypoints/openai/api_server.py').write_text(
                'import json,os,sys\n'
                'print(os.environ["HELP_FLAG"] if "--help" in sys.argv else json.dumps(sys.argv[1:]))\n')
            env = dict(os.environ, PYTHONPATH=temp, MODEL='/models/local-weights',
                       MODEL_NAME='declared-model', VRAM_BUDGET_GB='30',
                       VLLM_EXTRA_ARGS='--reasoning-parser qwen3')
            env.pop('GPU_UTIL', None)
            for flag in ('--no-enable-log-requests', '--disable-log-requests'):
                env['HELP_FLAG'] = flag
                result = subprocess.run(['bash', str(ROOT/'serve/vllm.sh')], env=env,
                                        text=True, capture_output=True, timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                args = json.loads(result.stdout)
                self.assertEqual(args[args.index('--gpu-memory-utilization')+1], '0.6250')
                self.assertEqual(args[args.index('--served-model-name')+1], 'declared-model')
                self.assertIn(flag, args)
                self.assertEqual(args[-2:], ['--reasoning-parser', 'qwen3'])
            env['GPU_UTIL'] = '0.5'
            result = subprocess.run(['bash', str(ROOT/'serve/vllm.sh')], env=env,
                                    text=True, capture_output=True, timeout=5)
            self.assertEqual(json.loads(result.stdout)[json.loads(result.stdout).index('--gpu-memory-utilization')+1], '0.5')
            env.pop('GPU_UTIL')
            env['VRAM_BUDGET_GB'] = '33'
            self.assertNotEqual(subprocess.run(['bash', str(ROOT/'serve/vllm.sh')], env=env,
                                 capture_output=True, timeout=5).returncode, 0)

    def test_start_detaches_reuses_services_and_reports_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            serve = root/'serve'; serve.mkdir()
            shutil.copy2(ROOT/'serve/start.sh', serve/'start.sh')
            binary = root/'bin'; binary.mkdir()
            # The real setsid is used; record only test-owned groups for cleanup.
            (binary/'setsid').write_text('#!/bin/bash\necho $$ >> "$TEST_ROOT/groups"\n'
                f'exec {shutil.which("setsid")} "$@"\n')
            (binary/'curl').write_text('#!/bin/bash\ntest -e "$TEST_ROOT/ready"\n')
            # Short poll interval, without changing the production script.
            (binary/'sleep').write_text(f'#!/bin/bash\nexec {shutil.which("sleep")} 0.02\n')
            for path in binary.iterdir(): path.chmod(0o755)
            model = serve/'vllm.sh'
            model.write_text('#!/bin/bash\necho $$ >> "$TEST_ROOT/models"\n'
                'touch "$TEST_ROOT/ready"\n'
                f'exec {shutil.which("sleep")} 60\n')
            model.chmod(0o755)
            env = dict(os.environ, PATH=str(binary)+os.pathsep+os.environ['PATH'],
                       TEST_ROOT=temp, SERVE_LOG_DIR=str(root/'logs'), EDA_TMP=str(root/'eda'),
                       START_TIMEOUT_S='5')
            try:
                for _ in range(2):
                    result = subprocess.run(['bash', str(serve/'start.sh')], env=env,
                                            capture_output=True, text=True, timeout=5)
                    self.assertEqual(result.returncode, 0, result.stderr)
                model_pids = (root/'models').read_text().splitlines()
                self.assertEqual(len(model_pids), 1)
                pid = int(model_pids[0])
                self.assertEqual(os.getsid(pid), pid)
                os.killpg(pid, signal.SIGTERM)
                (root/'ready').unlink()
                model.write_text('#!/bin/bash\nexit 7\n')
                result = subprocess.run(['bash', str(serve/'start.sh')], env=env,
                                        capture_output=True, text=True, timeout=5)
                self.assertNotEqual(result.returncode, 0)
                self.assertRegex(result.stderr, 'not ready|exited during startup')
            finally:
                if (root/'groups').exists():
                    for pid in (root/'groups').read_text().splitlines():
                        try: os.killpg(int(pid), signal.SIGKILL)
                        except ProcessLookupError: pass


if __name__ == '__main__':
    unittest.main()
