"""Meaningful checks for submission isolation and relocated development tools."""
import hashlib
import http.server
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from dev.tools.submission import check_submission_layout, stage_submission, smoke_submission


class SubmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)

    def test_isolated_agent_and_baseline_entries(self):
        staged = self.work/'submission'
        manifest = stage_submission(ROOT, staged)
        self.assertTrue((staged/'serve/start.sh').is_file())
        self.assertTrue(os.access(staged/'serve/start.sh', os.X_OK))
        self.assertFalse((staged/'dev').exists())
        self.assertFalse((staged/'__pycache__').exists())
        self.assertEqual((staged/'baseline.py').read_bytes(), (ROOT/'baseline.py').read_bytes())
        self.assertTrue(any(f['path']=='config/example.yaml' for f in manifest.files))
        for row in manifest.files:
            self.assertEqual(row['sha256'], hashlib.sha256((staged/row['path']).read_bytes()).hexdigest())
        result = smoke_submission(staged, ROOT.parent/'tasks/example/example_ex03_lfsr8', self.work/'mock')
        self.assertTrue(result.ok)
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                request=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                self.server.messages=request['messages']
                body=json.dumps({'choices':[{'message':{'content':'module TopModule(); endmodule'},'finish_reason':'stop'}],
                                 'usage':{'prompt_tokens':7,'completion_tokens':8}}).encode()
                self.send_response(200); self.send_header('Content-Type','application/json'); self.end_headers(); self.wfile.write(body)
            def log_message(self, *args): pass
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        try:
            env=dict(os.environ,LLM_BASE_URL=f'http://127.0.0.1:{server.server_port}/v1',LLM_MODEL='local-test')
            env.pop('PYTHONPATH',None)
            completed=subprocess.run([str(staged/'run_baseline.sh'),str(ROOT.parent/'tasks/example/example_ex03_lfsr8'),str(self.work/'baseline')],
                                      env=env,cwd=staged,capture_output=True,timeout=10)
            self.assertEqual(completed.returncode,0)
            self.assertIn('module TopModule', (self.work/'baseline/solution.v').read_text())
            self.assertTrue(server.messages)
        finally:
            server.shutdown(); server.server_close(); thread.join()

    def test_detect_missing_config_and_docker_baseline(self):
        staged=self.work/'submission'; stage_submission(ROOT,staged)
        (staged/'config/example.yaml').unlink()
        p=staged/'Dockerfile'; p.write_text(p.read_text().replace('run_baseline.sh baseline.py','run_baseline.sh'))
        report=check_submission_layout(staged)
        self.assertFalse(report.ok)
        self.assertIn('missing required file: config/example.yaml', report.errors)
        self.assertIn('file absent from Docker COPY destinations: baseline.py',report.errors)

    def test_reject_dev_import_and_symlink(self):
        staged=self.work/'submission'; stage_submission(ROOT,staged)
        (staged/'agent/bad.py').write_text('from dev.tools.run import main\n')
        (staged/'agent/secret.py').symlink_to(ROOT/'baseline.py')
        report=check_submission_layout(staged)
        self.assertIn('development import in submission: agent/bad.py',report.errors)
        self.assertIn('symlink is not a submission file: agent/secret.py',report.errors)

    def test_refuse_overwrite_and_source_destination(self):
        with self.assertRaises(ValueError): stage_submission(ROOT,ROOT/'out')
        with self.assertRaises(FileExistsError): stage_submission(ROOT,self.work)

    def test_remote_root_loading_without_credentials_or_network(self):
        # Test a copy of _common.sh with synthetic local configuration, not the user's credentials.
        remote=self.work/'agent/dev/tools/remote'; remote.mkdir(parents=True)
        shutil.copy2(ROOT/'dev/tools/remote/_common.sh',remote/'_common.sh')
        (remote/'remote.env').write_text('REMOTE_HOST=test-host\nREMOTE_SSH_OPTS=\nRC_COOKIE="a;b"\n')
        script='source "$1"; printf "%s\\n" "$AGENT_ROOT" "$DEV_ROOT" "$REMOTE_HOST"'
        result=subprocess.run(['bash','-c',script,'test',str(remote/'_common.sh')],capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout.splitlines(),[str(self.work/'agent'),str(self.work/'agent/dev'),'test-host'])
        self.assertNotIn('a;b',result.stdout+result.stderr)

    def test_joint_remote_wrapper_calls_unified_entry_and_cleans_sampler(self):
        # Run from a different directory with local stand-ins for remote operations.
        root=self.work/'agent'; remote=root/'dev/tools/remote'; remote.mkdir(parents=True)
        shutil.copy2(ROOT/'dev/tools/remote/joint_run.sh',remote/'joint_run.sh')
        (root/'dev/tools/analysis').mkdir()
        (root/'dev/configs').mkdir()
        (root/'dev/runs').mkdir()
        (remote/'_common.sh').write_text('REMOTE_HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\n'
            'AGENT_ROOT="$(cd "$REMOTE_HERE/../../.." && pwd)"\nexport DEV_ROOT="$AGENT_ROOT/dev"\n'
            'LOCAL_BASE_URL=test\nrssh() { return 0; }\nexport_llm_env() { export LLM_BASE_URL=test LLM_MODEL=test; }\n')
        for name in ('weights.sh','remote_vllm.sh','vram_watch.sh'):
            p2=remote/name; p2.write_text('#!/bin/bash\nprintf "%s %s\\n" "$(basename "$0")" "$*" >> "$DEV_ROOT/runs/operations"\n')
            p2.chmod(0o755)
        (root/'dev/tools/analysis/metrics.py').write_text("print(" + repr('{"tps_decode_median":1,"ttft_median":1}') + ")\n")
        (root/'dev/tools/run.py').write_text('import sys,pathlib\n'
            'root=pathlib.Path(__file__).parents[1]\n(root/"runs/arguments").write_text(" ".join(sys.argv[1:]))\n'
            'print(root/"runs/result"); print("completed")\n')
        # Avoid curl readiness retries without running a model service.
        bin_dir=self.work/'bin'; bin_dir.mkdir()
        curl=bin_dir/'curl'; curl.write_text("#!/bin/bash\necho '{\"id\":\"test\"}'\n"); curl.chmod(0o755)
        env=dict(os.environ,PATH=str(bin_dir)+os.pathsep+os.environ['PATH'])
        result=subprocess.run([str(remote/'joint_run.sh'),'/weights','test','quick'],cwd=self.work,
                              env=env,capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        arguments=(root/'dev/runs/arguments').read_text()
        self.assertIn('--config '+str(root/'dev/configs/joint-quick.yaml'),arguments)
        self.assertIn('--modes agent baseline',arguments)
        self.assertNotIn('--taskset',arguments)
        self.assertIn('vram_watch.sh stop',(root/'dev/runs/operations').read_text())
        self.assertIn('完成：dev/runs/result',result.stdout)


if __name__=='__main__': unittest.main()
