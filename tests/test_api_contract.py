"""Submission HTTP contract; no real model or EDA tool is contacted."""

import io
import json
import os
from pathlib import Path
import queue
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from serve import serve_api as api


class ApiContractTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(api.app)
        self.addCleanup(self.client.close)
        self.addCleanup(patch.stopall)
        patch.object(api, "TOKEN", "test-token").start()
        patch.dict(os.environ, {}, clear=True).start()
        self.headers = {"Authorization": "Bearer test-token"}

    def health(self):
        return self.client.get("/v1/health", headers=self.headers)

    def test_authentication_is_required(self):
        self.assertEqual(self.client.get("/v1/health").status_code, 401)
        response = self.client.post("/v1/solve", json={"task_id": "t", "prompt": "p"})
        self.assertEqual(response.status_code, 401)

    def test_health_validates_real_graph_and_reports_declared_model(self):
        with patch.object(api, "_check_model") as model_check, \
             patch.object(api, "_vram_gb", return_value=27.981):
            response = self.health()
        self.assertEqual(response.status_code, 200, response.text)
        manifest = json.loads((Path(api.ROOT) / "manifest.json").read_text())
        self.assertEqual(response.json(), {
            "ready": True, "track": "rtl", "model": manifest["model"]["name"],
            "vram_gb": 27.981,
        })
        model_check.assert_called_once()

    def test_health_rejects_mock_and_model_alias_mismatch(self):
        for setting in ({"LLM_BACKEND": "mock"}, {"LLM_MODEL": "another-model"},
                        {"MODEL_NAME": "another-baseline-model"}):
            with self.subTest(setting=setting), patch.dict(os.environ, setting):
                self.assertEqual(self.health().status_code, 503)

    def test_health_rejects_unknown_workflow(self):
        with patch.dict(os.environ, {"RTLAGENT_WORKFLOW": "does_not_exist"}):
            self.assertEqual(self.health().status_code, 503)

    def test_submission_rejects_external_model_profile_and_embedding_urls(self):
        settings = (
            {"LLM_BASE_URL": "https://api.example.invalid/v1"},
            {"LLM_BASE_URL": "http://10.0.0.1:8000/v1"},
            {"LLM_BASE_URL": "file:///tmp/model"},
            {"RTLAGENT_SERVICES__PROFILES__SMALL": json.dumps({
                "enabled": True, "model": "small", "base_url": "https://example.invalid/v1"})},
            {"RTLAGENT_PARAMS": json.dumps({"embedding_url": "https://example.invalid"})},
            {"RTLAGENT_PARAMS": json.dumps({"embedding_transport": "ssh"})},
        )
        for setting in settings:
            with self.subTest(setting=setting), patch.dict(os.environ, setting), \
                 patch.object(api, "_check_model") as probe:
                self.assertEqual(self.health().status_code, 503)
                with self.assertRaises(ValueError):
                    api._service_config()
                probe.assert_not_called()

    def test_loopback_urls_are_accepted_without_network_lookup(self):
        for url in ("http://127.0.0.1:8000/v1", "http://localhost:8000/v1", "https://[::1]/v1"):
            with self.subTest(url=url):
                api._require_loopback(url)

    def test_health_rejects_unavailable_model_and_unknown_memory(self):
        with patch.object(api, "_check_model", side_effect=OSError("unavailable")):
            self.assertEqual(self.health().status_code, 503)
        with patch.object(api, "_check_model"), patch.object(api, "_vram_gb", return_value=None):
            response = self.health()
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("vram_gb", response.json())

    def test_health_rejects_missing_entry_point(self):
        with patch.object(api.os, "access", return_value=False):
            self.assertEqual(self.health().status_code, 503)

    def test_invalid_mode_and_deadline_never_enter_queue(self):
        with patch.object(api, "_QUEUE", queue.Queue()) as pending:
            for values in ({"mode": "other"}, {"deadline_s": 0}, {"deadline_s": -1},
                           {"deadline_s": True}, {"deadline_s": "60"}, {"deadline_s": 1.5}):
                with self.subTest(values=values):
                    response = self.client.post("/v1/solve", headers=self.headers,
                                                json={"task_id": "t", "prompt": "p", **values})
                    self.assertEqual(response.status_code, 422)
            self.assertTrue(pending.empty())

    def test_nonce_retry_preserves_original_job_and_one_queue_entry(self):
        with patch.object(api, "_QUEUE", queue.Queue()) as pending, \
             patch.object(api, "_JOBS", {}), patch.object(api, "_BY_NONCE", {}):
            payload = {"task_id": "t", "prompt": "p", "nonce": "once", "deadline_s": 60}
            first = self.client.post("/v1/solve", headers=self.headers, json=payload)
            second = self.client.post("/v1/solve", headers=self.headers, json=payload)
            self.assertEqual(first.status_code, 202)
            self.assertEqual(first.json(), second.json())
            self.assertEqual(pending.qsize(), 1)
            job = self.client.get("/v1/jobs/" + first.json()["job_id"], headers=self.headers)
            self.assertEqual(job.json()["task_id"], "t")

    def test_expired_queue_job_does_not_start_a_process(self):
        with patch.object(api, "_run_task") as run:
            result = api._solve(api.SolveRequest(task_id="t", prompt="p", deadline_s=1),
                                time.time() - 2)
        self.assertEqual(result, ("", ""))
        run.assert_not_called()

    def test_trace_fields_preserve_evidence_and_unknowns(self):
        records = [
            {"tool": "baseline_meta", "generation": {"reasoning_effort": "medium"}},
            {"tool": "llm", "ts": 123.25, "tokens_in": 20, "tokens_out": 0, "finish": "stop"},
            {"tool": "llm", "ts": 124.5, "tokens_in": None, "tokens_out": None, "error": "timeout"},
            {"tool": "lint", "ts": 125.5, "rc": 1, "excerpt": "compile failed"},
        ]
        result = api._complete_trace_fields("\n".join(map(json.dumps, records)))
        rows = [json.loads(line) for line in result.splitlines()]
        for original, row in zip(records, rows):
            self.assertTrue({"ts", "tool", "rc", "excerpt", "tokens_in", "tokens_out"} <= row.keys())
            self.assertEqual({key: row[key] for key in original}, original)
        self.assertIsNone(rows[0]["ts"])
        self.assertIsNone(rows[1]["rc"])
        self.assertEqual(rows[1]["tokens_out"], 0)
        self.assertIsNone(rows[2]["tokens_out"])
        self.assertEqual(api._complete_trace_fields(result), result)
        self.assertEqual(api._complete_trace_fields("\n"), "")

    def test_invalid_trace_lines_are_explicit_diagnostics(self):
        invalid = ['{"tool":', '[]', '{"tool":"llm","tokens_out":NaN}']
        with patch.object(api.time, "time", return_value=123.5):
            rows = [json.loads(line) for line in api._complete_trace_fields("\n".join(invalid)).splitlines()]
        for number, (raw, row) in enumerate(zip(invalid, rows), 1):
            self.assertEqual(row["event"], "invalid_trace_line")
            self.assertEqual(row["tool"], "api")
            self.assertEqual(row["source_line"], number)
            self.assertEqual(row["raw_line"], raw)
            self.assertEqual(row["ts"], 123.5)
            self.assertIsNone(row["rc"])
            self.assertIsNone(row["tokens_out"])

    def test_trace_unicode_separators_preserve_one_record(self):
        original = {"tool": "llm", "excerpt": "a\u2028b\u2029c"}
        trace = api._complete_trace_fields(json.dumps(original, ensure_ascii=False) + "\r\n")
        self.assertEqual(len(trace.splitlines()), 1)
        self.assertEqual(json.loads(trace)["excerpt"], original["excerpt"])

    def test_trace_surrogate_escapes_remain_safe_in_http_response(self):
        original = '{"tool":"llm","excerpt":"\\ud800"}\n'
        trace = api._complete_trace_fields(original)
        job = {"job_id": "unicode", "task_id": "unicode", "status": "done",
               "solution": "", "trace": trace, "elapsed_s": 1.0}
        with patch.object(api, "_JOBS", {"unicode": job}):
            response = self.client.get("/v1/jobs/unicode", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.json()["trace"])["excerpt"], "\ud800")

    def test_both_modes_complete_response_trace_without_rewriting_source(self):
        original = '{"tool":"baseline_meta"}\n{"tool":"llm","ts":123,"tokens_in":4,"tokens_out":5}\n'

        def run(cmd, **kwargs):
            out = Path(cmd[2])
            (out / "trace.jsonl").write_text(original)
            (out / "solution.v").write_text("module TopModule; endmodule\n")

        with patch.object(api, "_run_task", side_effect=run), \
             patch.object(api, "_complete_trace_fields", wraps=api._complete_trace_fields) as complete:
            for mode in ("agent", "baseline"):
                solution, trace = api._solve(api.SolveRequest(task_id="trace", prompt="p", mode=mode), time.time())
                self.assertTrue(solution.startswith("module"))
                complete.assert_called_with(original)
                self.assertTrue(all("rc" in json.loads(line) for line in trace.splitlines()))

    def test_modes_receive_same_effective_model_and_remaining_timeout(self):
        settings = {"RTLAGENT_SERVICES__MODEL__BASE_URL": "http://127.0.0.1:8123/v1",
                    "RTLAGENT_SERVICES__MODEL__MODEL": "configured-model",
                    "TRACK": "hls"}
        with patch.dict(os.environ, settings), patch.object(api.time, "time", return_value=100), \
             patch.object(api, "_run_task") as run:
            for mode in ("agent", "baseline"):
                api._solve(api.SolveRequest(task_id="t", prompt="p", mode=mode, deadline_s=60), 90)
        agent, baseline = run.call_args_list
        for call in (agent, baseline):
            self.assertEqual(call.kwargs["timeout_s"], 40)
            env = call.kwargs["env"]
            self.assertEqual(env["LLM_BASE_URL"], "http://127.0.0.1:8123/v1")
            self.assertEqual(env["LLM_MODEL"], "configured-model")
            self.assertEqual(env["MODEL_NAME"], "configured-model")
            self.assertEqual(env["LLM_BACKEND"], "openai")
            self.assertEqual(env["TRACK"], "rtl")
            self.assertTrue(Path(env["AGENT_CONFIG"]).is_absolute())
        self.assertEqual(agent.args[0][-2:], ["--hard-deadline-s", "50"])
        self.assertEqual(Path(baseline.args[0][0]).name, "run_baseline.sh")

    def test_whitespace_answers_are_empty_for_both_modes(self):
        for mode in ("agent", "baseline"):
            for output in (" \n\t", "module TopModule; endmodule\n"):
                with self.subTest(mode=mode, output=output):
                    def run(cmd, **kwargs):
                        (Path(cmd[2]) / "solution.v").write_text(output)
                    with patch.object(api, "_run_task", side_effect=run):
                        solution, _ = api._solve(api.SolveRequest(task_id="t", prompt="p", mode=mode),
                                                 time.time())
                    self.assertEqual(solution, output if output.strip() else "")

    def test_model_probe_requires_loaded_service_and_expected_model(self):
        model = SimpleNamespace(base_url="http://127.0.0.1:8000/v1", model="expected")
        def response(body, status=200):
            value = io.BytesIO(json.dumps(body).encode())
            value.status = status
            return value
        for listed, valid in (("expected", True), ("wrong", False)):
            with self.subTest(listed=listed), patch.object(api.urllib.request, "build_opener") as build:
                build.return_value.open.side_effect = [response({"status": "ok"}),
                                                       response({"data": [{"id": listed}]})]
                if valid:
                    api._check_model(model)
                else:
                    with self.assertRaises(ValueError):
                        api._check_model(model)
        with patch.object(api.urllib.request, "build_opener") as build:
            build.return_value.open.return_value = response({}, status=503)
            with self.assertRaises(ValueError):
                api._check_model(model)

    def test_vram_counts_bytes_deduplicates_devices_and_preserves_unknown(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            sysfs, devices, gpu = root / "sys", root / "dev", root / "gpu"
            for path in (sysfs, devices, gpu):
                path.mkdir()
            (gpu / "vendor").write_text("0x1002\n")
            (gpu / "mem_info_vram_used").write_text(str(3 * 1024 ** 3))
            for name in ("card1", "renderD128"):
                (sysfs / name).mkdir()
                (sysfs / name / "device").symlink_to(gpu)
                (devices / name).touch()
            self.assertEqual(api._vram_gb(sysfs, devices), 3.0)
            (gpu / "mem_info_vram_used").write_text("invalid")
            self.assertIsNone(api._vram_gb(sysfs, devices))
            (gpu / "mem_info_vram_used").unlink()
            self.assertIsNone(api._vram_gb(sysfs, devices))
            self.assertIsNone(api._vram_gb(root / "missing", devices))

    @unittest.skipUnless(sys.platform == "linux", "process-group cleanup requires Linux")
    def test_timeout_kills_and_reaps_task_descendants(self):
        with tempfile.TemporaryDirectory() as work:
            pidfile = Path(work) / "child.pid"
            code = (
                "import pathlib, subprocess, sys, time; "
                "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
                "pathlib.Path(sys.argv[1]).write_text(str(child.pid)); time.sleep(30)"
            )
            api._run_task([sys.executable, "-c", code, str(pidfile)],
                          env=dict(os.environ), timeout_s=0.5, grace_s=0.1)
            self.assertTrue(pidfile.is_file())
            self.assertFalse(Path("/proc", pidfile.read_text()).exists())


@unittest.skipUnless(sys.platform == "linux", "watchdog uses Linux sessions")
class ApiStartupTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.root = Path(self.work.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for name in ("bash", "dirname", "mkdir", "cat", "setsid", "sleep", "rm", "date"):
            (self.bin / name).symlink_to(shutil.which(name))
        self.env = {"PATH": str(self.bin), "AGENT_TMP": str(self.root),
                    "FPGACHINA_TOKEN": "test-token"}
        self.script = str(Path(api.ROOT) / "serve/run_api.sh")
        self.addCleanup(self.stop_watchdog)

    def stop_watchdog(self):
        path = self.root / "run_api/run_api.pid"
        if path.exists():
            pid = int(path.read_text())
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                os.waitpid(pid, 0)
            except ChildProcessError:
                pass

    def invoke(self, command):
        return subprocess.run([self.script, command], env=self.env, cwd=api.ROOT,
                              text=True, capture_output=True, timeout=15)

    def fake_uvicorn(self, body):
        path = self.bin / "uvicorn"
        path.write_text("#!/bin/sh\n" + body + "\n")
        path.chmod(0o755)

    def test_missing_uvicorn_fails_without_starting_watchdog(self):
        result = self.invoke("start")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("required executable not found: uvicorn", result.stderr)
        self.assertFalse((self.root / "run_api/run_api.pid").exists())

    def test_immediately_exiting_api_is_not_reported_started(self):
        self.fake_uvicorn("exit 7")
        result = self.invoke("start")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("run_api.sh: started", result.stdout)
        self.assertFalse((self.root / "run_api/run_api.pid").exists())

    def test_live_api_and_watchdog_start_without_model_health_probe(self):
        self.fake_uvicorn("exec /bin/sleep 30")
        result = self.invoke("start")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("run_api.sh: started", result.stdout)
        self.assertEqual(self.invoke("status").returncode, 0)


if __name__ == "__main__":
    unittest.main()
