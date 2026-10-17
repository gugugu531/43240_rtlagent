"""Asynchronous, authenticated submission endpoint; one solver at a time.

Run one uvicorn worker on 127.0.0.1:7860. Job IDs, results and nonce mappings
live in this process until shutdown. The solver and official baseline remain
file-based commands, supervised in separate process groups.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
import ctypes
import json
import os
import queue
import subprocess
import tempfile
import threading
import time
import uuid
from typing import Literal

import requests
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from agent.services.processes import ProcessExecutor, ProcessRequest
from agent.core.configuration import load_config, resolve_config
from agent.services.model import load_shared_generation

TOKEN = os.environ.get("FPGACHINA_TOKEN", "")
TRACK = "rtl"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRATCH = os.environ.get("AGENT_TMP", "/tmp")


class SolveRequest(BaseModel):
    task_id: str
    nonce: str = ""
    mode: Literal["agent", "baseline"] = "agent"
    prompt: str
    interface: str = ""
    deadline_s: int = Field(default=900, gt=0, le=900)


def _event(event: str, **fields) -> str:
    return json.dumps(dict(ts=time.time(), tool="submission", event=event, **fields)) + "\n"


def _public(job: dict) -> dict:
    out = {key: job[key] for key in ("job_id", "task_id", "status")}
    if job["status"] == "done":
        out.update({key: job[key] for key in ("solution", "trace", "elapsed_s")})
    return out


class JobManager:
    """Own the FIFO worker, nonce deduplication and immutable public snapshots."""
    def __init__(self):
        self.jobs = {}
        self.nonces = {}
        self.lock = threading.Lock()
        self.queue = queue.Queue()
        self.stopping = threading.Event()
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self._worker, name="submission-worker", daemon=True)
        self.thread.start()

    def close(self):
        with self.lock:
            self.stopping.set()
            self.queue.put(None)
        self.thread.join()

    def submit(self, req):
        with self.lock:
            if self.stopping.is_set() or self.thread is None or not self.thread.is_alive():
                raise HTTPException(status_code=503, detail="submission worker unavailable")
            if req.nonce and req.nonce in self.nonces:
                job = self.jobs[self.nonces[req.nonce]]
                self._expire_queued(job)
                return _public(job)
            job_id = uuid.uuid4().hex
            job = dict(job_id=job_id, task_id=req.task_id, status="queued",
                       req=req.model_copy(deep=True), submitted=time.monotonic())
            self.jobs[job_id] = job
            if req.nonce:
                self.nonces[req.nonce] = job_id
            # Keep insertion and queuing under one lock to preserve arrival order.
            self.queue.put(job_id)
            return _public(job)

    def get(self, job_id):
        with self.lock:
            if job_id not in self.jobs:
                raise HTTPException(status_code=404, detail="unknown job_id")
            job = self.jobs[job_id]
            self._expire_queued(job)
            return _public(job)

    def _expire_queued(self, job):
        # Called only under the manager lock. A busy worker must not postpone
        # the result of a queued request beyond its own wall-clock deadline.
        elapsed = time.monotonic() - job['submitted']
        if job['status'] == 'queued' and elapsed >= job['req'].deadline_s:
            job.update(status='done', solution='', trace=_event('expired', reason='queue_deadline'),
                       elapsed_s=round(elapsed, 3))
            del job['req']

    def _worker(self):
        while True:
            job_id = self.queue.get()
            try:
                if job_id is None:
                    return
                with self.lock:
                    job = self.jobs[job_id]
                    self._expire_queued(job)
                    if job['status'] == 'done':
                        continue
                    job["status"] = "running"
                try:
                    solution, trace = _solve(job["req"], job["submitted"], self.stopping)
                except Exception as exc:
                    # Do not leak request content, paths or credentials in errors.
                    solution, trace = "", _event("failed", error_type=type(exc).__name__)
                with self.lock:
                    job.update(status="done", solution=solution, trace=trace,
                               elapsed_s=round(time.monotonic() - job["submitted"], 3))
                    del job["req"]
            finally:
                self.queue.task_done()


@asynccontextmanager
async def lifespan(app):
    # Adopt killed baseline descendants on Linux; JupyterLab's PID 1 does not
    # reap them. Reap only our task groups, never another subprocess's status.
    libc = None
    previous = ctypes.c_int(0)
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(37, ctypes.byref(previous), 0, 0, 0) != 0 or libc.prctl(36, 1, 0, 0, 0) != 0:
            libc = None
    except (OSError, AttributeError):
        libc = None
    manager = JobManager()
    app.state.jobs = manager
    manager.start()
    try:
        yield
    finally:
        manager.close()
        if libc is not None:
            libc.prctl(36, previous.value, 0, 0, 0)


app = FastAPI(title="rtlagent2026 submission endpoint", lifespan=lifespan)


def _check_token(authorization: str | None) -> None:
    if not TOKEN:
        raise HTTPException(status_code=500, detail="FPGACHINA_TOKEN not set")
    if authorization != f"Bearer {TOKEN}":
        raise HTTPException(status_code=401, detail="bad token")


@app.get("/v1/health")
def health(authorization: str | None = Header(default=None)):
    _check_token(authorization)
    try:
        config = resolve_config(load_config(os.environ.get("AGENT_CONFIG")), env=os.environ)
        model = config.agent.services.model
        options = {} if model.enable_thinking is None else {'enable_thinking': model.enable_thinking}
        load_shared_generation(options)
        manager = app.state.jobs
        if manager.stopping.is_set() or not manager.thread.is_alive():
            raise ValueError("worker unavailable")
        name = model.baseline_model_name or model.model
        if model.backend != "mock":
            headers = {"Authorization": f"Bearer {model.api_key}"} if model.api_key else {}
            response = requests.get(model.base_url + "/models", headers=headers, timeout=1)
            response.raise_for_status()
            names = [row["id"] for row in response.json()["data"]]
            if name not in names:
                raise ValueError("configured model unavailable")
    except Exception:
        raise HTTPException(status_code=503, detail="agent or model unavailable") from None
    return dict(ready=True, track=TRACK, model=name, vram_gb=_vram_gb())


@app.post("/v1/solve", status_code=202)
def solve(req: SolveRequest, authorization: str | None = Header(default=None)):
    _check_token(authorization)
    return app.state.jobs.submit(req)


@app.get("/v1/jobs/{job_id}")
def job_status(job_id: str, authorization: str | None = Header(default=None)):
    _check_token(authorization)
    return app.state.jobs.get(job_id)


def _reap_groups(groups, deadline):
    remaining = set(groups)
    while remaining and time.monotonic() < deadline:
        for pgid in tuple(remaining):
            try:
                pid, _ = os.waitpid(-pgid, os.WNOHANG)
                if pid == 0:
                    continue
            except ChildProcessError:
                remaining.discard(pgid)
        if remaining:
            time.sleep(0.005)
    return sorted(remaining)


def _solve(req: SolveRequest, submitted: float, stopping=None) -> tuple[str, str]:
    deadline = submitted + req.deadline_s
    reserve = min(0.25, req.deadline_s * 0.1)
    if time.monotonic() >= deadline - reserve:
        return "", _event("expired", reason="queue_deadline")
    if stopping is not None and stopping.is_set():
        return "", _event("cancelled", reason="service_shutdown")
    script = "run_baseline.sh" if req.mode == "baseline" else "run.sh"
    with tempfile.TemporaryDirectory(dir=SCRATCH) as work:
        in_dir, out_dir = os.path.join(work, "in"), os.path.join(work, "out")
        os.makedirs(in_dir)
        os.makedirs(out_dir)
        for name, content in (("prompt.txt", req.prompt), ("interface.txt", req.interface)):
            with open(os.path.join(in_dir, name), "w", encoding="utf-8") as fh:
                fh.write(content)
        remaining = deadline - reserve - time.monotonic()
        if remaining <= 0:
            return "", _event("expired", reason="preparation_deadline")
        env = dict(os.environ, AGENT_TASK_ID=req.task_id)
        command = (os.path.join(ROOT, script), in_dir, out_dir)
        if req.mode == "agent":
            command += ("--hard-deadline-s", str(remaining))
        executor = ProcessExecutor()
        result = None
        diagnostic = ""
        try:
            identity = executor.start(ProcessRequest(command, ROOT, remaining, env,
                                      terminate_grace_s=min(0.6, remaining * 0.25)))
            while stopping is None or not stopping.is_set():
                result = executor.poll(identity)
                if result is not None:
                    break
                time.sleep(0.005)
        except Exception as exc:
            diagnostic = _event("failed", error_type=type(exc).__name__)
        finally:
            executor.cancel_all(deadline - reserve)
            unreaped = _reap_groups(executor.groups, deadline)
        if result is not None and result.status != "ok":
            diagnostic += _event("process_result", status=result.status, rc=result.rc)
        if stopping is not None and stopping.is_set():
            diagnostic += _event("cancelled", reason="service_shutdown")
        if unreaped:
            diagnostic += _event("cleanup_incomplete", unreaped_groups=unreaped)
        trace = _read(os.path.join(out_dir, "trace.jsonl"))
        if trace and diagnostic and not trace.endswith("\n"):
            trace += "\n"
        return _read(os.path.join(out_dir, "solution.v")), trace + diagnostic


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except (OSError, UnicodeDecodeError):
        return ""


def _vram_gb() -> float:
    """Best-effort current VRAM reading; health is not a peak measurement."""
    try:
        out = subprocess.run(["rocm-smi", "--showmemuse", "--csv"],
                             capture_output=True, text=True, timeout=1).stdout
        for line in out.splitlines():
            parts = line.split(",")
            if len(parts) >= 2 and parts[-1].strip().isdigit():
                return round(int(parts[-1]) / (1024 ** 3), 1)
    except (OSError, subprocess.SubprocessError):
        pass
    return 0.0
