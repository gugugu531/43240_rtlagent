"""The presentation and both job sources share the real admission lock."""

import json
import os
from pathlib import Path
import queue
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from serve import serve_api as api
from serve.live_runs import RunFeed


class LiveApiTests(unittest.TestCase):
    def setUp(self):
        self.directory = self.enterContext(tempfile.TemporaryDirectory())
        self.task = Path(self.directory) / "lights"
        self.task.mkdir()
        (self.task / "prompt.txt").write_text("Design a light switch.")
        self.enterContext(patch.dict(os.environ, dict(RTLAGENT_UI_TASKS=self.directory,
                                                       RTLAGENT_UI_OPERATOR_TOKEN="presenter-test"), clear=True))
        self.enterContext(patch.multiple(api, TOKEN="judge-test", SCRATCH=self.directory,
                                         _JOBS={}, _PENDING=set(), _BY_NONCE={},
                                         _RECENT=[], _ACTIVE_ID=None, _QUEUE=queue.Queue(),
                                         _UI_ON=False, _MODE="submission"))
        self.persist = self.enterContext(patch.object(api, "persist_mode"))
        self.client = TestClient(api.app)
        self.addCleanup(self.client.close)
        self.submission = {"Authorization": "Bearer judge-test"}
        self.presenter = {"Authorization": "Bearer presenter-test"}

    def submit(self):
        return self.client.post("/v1/solve", headers=self.submission,
                                json={"task_id": "remote", "prompt": "official statement", "nonce": "one"})

    def test_sources_permissions_and_switching_with_an_outstanding_job(self):
        self.assertEqual(self.client.get("/ui").status_code, 404)
        self.assertEqual(self.client.get("/ui/api/state").status_code, 404)
        api._control("ui", "on")
        self.assertEqual(self.client.get("/ui/api/state").json()["mode"], "submission")
        self.assertEqual(self.client.get("/ui/api/tasks").status_code, 409)
        self.assertEqual(self.client.get("/ui/assets/serve_api.py").status_code, 404)
        self.assertEqual(self.client.get("/ui/assets/app.js").status_code, 200)
        self.assertEqual(self.client.get("/ui/assets/story.js").status_code, 404)
        job_id = self.submit().json()["job_id"]
        r = self.client.get("/ui/api/runs/" + job_id)
        self.assertEqual(r.json()["prompt"], "official statement")
        self.assertEqual(r.headers["cache-control"], "no-store")
        self.assertNotIn("trace", r.json())
        self.assertIn("error", api._control("mode", "local"))
        self.assertEqual(self.submit().json()["job_id"], job_id)
        self.assertEqual(len(api._PENDING), 1)
        self.assertFalse(api._control("ui", "off")["ui"])
        self.assertEqual(self.client.get("/ui/api/runs/" + job_id).status_code, 404)
        self.assertEqual(self.client.get("/v1/jobs/" + job_id, headers=self.submission).status_code, 200)
        self.assertEqual(self.client.get("/v1/jobs/" + job_id).status_code, 401)
        self.persist.assert_not_called()

    def test_anonymous_model_transcript_redacts_service_secrets_without_mutating_feed(self):
        api._control("ui", "on")
        job_id = self.submit().json()["job_id"]
        feed = api._JOBS[job_id]["feed"]
        feed.attach(self.directory)
        response = dict(v=1, type="call_response", call_id="r1", content="assign token = a / b;",
                        reasoning_content="Output quotes judge-test.",
                        tool_calls=[{"function": {"arguments": "presenter-test"}}])
        context = dict(v=1, type="call_context", call_id="r1",
                       messages=[{"role": "user", "content": "echo presenter-test"}])
        (Path(self.directory) / "live.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in (context, response)))
        page = self.client.get("/ui/api/runs/" + job_id)
        self.assertEqual(page.status_code, 200)
        for credential in ("judge-test", "presenter-test"):
            self.assertNotIn(credential, page.text)
        public = page.json()["events"]
        self.assertEqual(public[0]["messages"][0]["content"], "echo [凭据已隐藏]")
        self.assertEqual(public[1]["content"], response["content"])
        self.assertIn("[凭据已隐藏]", public[1]["reasoning_content"])
        self.assertEqual(feed.page(0)["events"], [context, response])

    def test_local_selection_and_rejection_of_official_task(self):
        self.assertEqual(api._control("mode", "local")["mode"], "local")
        self.persist.assert_called_once_with("local")
        api._control("ui", "on")
        self.assertEqual(self.client.get("/v1/health", headers=self.submission).status_code, 503)
        self.assertEqual(self.submit().status_code, 503)
        self.assertEqual(self.client.get("/ui/api/tasks").json(), {"tasks": ["lights"]})
        self.assertEqual(self.client.get("/ui/api/task", params={"task_id": "lights"}).json()["prompt"],
                         "Design a light switch.")
        def post(headers):
            return self.client.post("/ui/api/runs", headers=headers, json={"task_id": "lights"})
        self.assertEqual(post({}).status_code, 401)
        self.assertEqual(post(self.submission).status_code, 401)
        self.assertEqual(self.client.get("/ui/api/task", params={"task_id": "../elsewhere"}).status_code, 404)
        started = post(self.presenter)
        self.assertEqual(started.status_code, 202)
        self.assertEqual(post(self.presenter).status_code, 409)
        self.assertIn("error", api._control("mode", "submission"))
        job_id = started.json()["job_id"]
        self.assertEqual(self.client.get("/ui/api/runs/" + job_id).json()["source"], "local")
        self.assertEqual(self.client.get("/v1/jobs/" + job_id, headers=self.submission).status_code, 404)

    def test_local_mock_is_separate_from_the_official_service(self):
        with patch.dict(os.environ, {"LLM_BACKEND": "mock", "FPGACHINA_TOKEN": "judge-test"}):
            with self.assertRaises(ValueError):
                api._service_config()
            with patch.object(api, "_run_task") as run:
                api._solve(api.SolveRequest(task_id="local", prompt="p"), time.time(), local=True, feed=RunFeed())
        env = run.call_args.kwargs["env"]
        self.assertEqual(env["LLM_BACKEND"], "mock")
        self.assertEqual(env["RTLAGENT_LIVE_EVENTS"], "1")
        for key in ("FPGACHINA_TOKEN", "RTLAGENT_UI_OPERATOR_TOKEN", "RTLAGENT_UI_TASKS"):
            self.assertNotIn(key, env)

    def test_local_only_start_without_a_judge_token(self):
        with patch.object(api, "TOKEN", ""):
            self.assertEqual(api._control("restore", "submission")["mode"], "local")
            self.assertIn("error", api._control("mode", "submission"))
            self.assertEqual(self.submit().status_code, 503)
        with patch.dict(os.environ, {"RTLAGENT_UI_OPERATOR_TOKEN": "judge-test"}):
            api._control("restore", "submission")
            self.assertIn("error", api._control("mode", "local"))

    def test_partial_event_pagination_and_cleanup(self):
        feed = RunFeed()
        feed.attach(self.directory)
        path = Path(self.directory) / "live.jsonl"
        events = [dict(v=1, type="detail", value=str(i)) for i in range(100)]
        with path.open("w") as stream:
            for row in events:
                stream.write(json.dumps(row) + "\n")
            stream.write('{"v":1,"type":"run_')
            stream.flush()
            first = feed.page(0)
            self.assertEqual(first["events"], events[:96])
            self.assertTrue(first["more"])
            self.assertEqual(feed.page(96)["events"], events[96:])
            stream.write('end"}\n')
        feed.finish()
        path.unlink()
        self.assertEqual(feed.page(100)["events"], [{"v": 1, "type": "run_end"}])
        self.assertIsNone(feed.page(0)["error"])
        fresh = RunFeed()
        fresh.attach(self.directory)
        path.write_text('{"v":1')
        fresh.finish()
        self.assertIsNotNone(fresh.page(0)["error"])

    def test_malformed_event_does_not_hide_later_valid_steps(self):
        feed = RunFeed()
        feed.attach(self.directory)
        path = Path(self.directory) / "live.jsonl"
        path.write_text('{"v":true,"type":"detail"}\n'
                        '{"v":1,"type":"detail","value":NaN}\n'
                        '{"v":1,"type":"detail","value":1e999}\n'
                        '{"v":1,"type":"run_end","elapsed_s":1.5}\n')
        feed.finish()
        result = feed.page(0)
        self.assertEqual(result["events"], [{"v": 1, "type": "run_end", "elapsed_s": 1.5}])
        self.assertEqual(result["cursor"], 1)
        self.assertTrue(result["error"])
        json.dumps(result, allow_nan=False)
