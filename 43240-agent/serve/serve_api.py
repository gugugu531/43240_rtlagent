"""Submission endpoint.

A thin HTTP shell around run.sh / run_baseline.sh. The agent itself does not
change -- it still reads a directory and writes a file.

    export FPGACHINA_TOKEN=<token issued by the organisers>
    export MODEL_NAME=Qwen/Qwen3-8B
    uvicorn serve.serve_api:app --host 127.0.0.1 --port 7860

Bind 127.0.0.1, not 0.0.0.0. Radeon Cloud's rc-tunnel only picks up HTTP
services bound to the loopback interface; a service on 0.0.0.0 is never
exposed, and from the organisers' side that is indistinguishable from a
crash. Expose it with `rc-tunnel expose --port 7860`; only one port per
notebook can be exposed, so leave vLLM's 8000 internal.

The public app URL carries no platform-level auth, so the token check below is
not optional -- without it anyone who learns the URL can submit tasks.

See docs/API_CONTRACT.md for the full contract.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import time

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from agent.services.processes import ProcessExecutor, ProcessRequest
from agent.core.configuration import load_config, resolve_config

app = FastAPI(title="rtlagent2026 submission endpoint")

TOKEN = os.environ.get("FPGACHINA_TOKEN", "")
MODEL_NAME = os.environ.get("MODEL_NAME", os.environ.get("LLM_MODEL", "unknown"))
TRACK = "rtl"

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRATCH = os.environ.get("AGENT_TMP", "/tmp")


class SolveRequest(BaseModel):
    task_id: str
    nonce: str = ""
    mode: str = "agent"           # "agent" or "baseline"
    prompt: str
    interface: str = ""
    deadline_s: int = Field(default=360, gt=0)


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
    except Exception:
        raise HTTPException(status_code=503, detail="agent configuration unavailable") from None
    return {
        "ready": True,
        "track": TRACK,          # mismatched track => the organisers refuse to submit
        "model": os.environ.get("MODEL_NAME") or config.agent.services.model.model,
        "vram_gb": _vram_gb(),
    }


@app.post("/v1/solve")
def solve(req: SolveRequest, authorization: str | None = Header(default=None)):
    started = time.monotonic()
    _check_token(authorization)

    script = "run.sh" if req.mode != "baseline" else "run_baseline.sh"
    t0 = time.time()

    with tempfile.TemporaryDirectory(dir=SCRATCH) as work:
        in_dir = os.path.join(work, "in")
        out_dir = os.path.join(work, "out")
        os.makedirs(in_dir)
        os.makedirs(out_dir)

        with open(os.path.join(in_dir, "prompt.txt"), "w", encoding="utf-8") as fh:
            fh.write(req.prompt)
        with open(os.path.join(in_dir, "interface.txt"), "w", encoding="utf-8") as fh:
            fh.write(req.interface)

        remaining = max(0.0, started + req.deadline_s - time.monotonic())
        return_reserve = min(0.25, req.deadline_s * 0.1)
        env = dict(os.environ, AGENT_TASK_ID=req.task_id)
        command = (os.path.join(ROOT, script), in_dir, out_dir)
        if req.mode != "baseline":
            command += ("--hard-deadline-s", str(max(0.001, remaining - return_reserve)))
        # Includes preparation, execution and group cleanup; tiny deadlines have
        # no artificial five-second floor. Baseline only receives supervision.
        if remaining > return_reserve:
            executor = ProcessExecutor()
            executor.run(ProcessRequest(command, ROOT,
                         remaining - return_reserve, env,
                         terminate_grace_s=min(0.6, remaining - return_reserve)))

        solution = _read(os.path.join(out_dir, "solution.v"))
        trace = _read(os.path.join(out_dir, "trace.jsonl"))

    return {
        "task_id": req.task_id,
        "solution": solution,       # empty string means "could not solve it"
        "trace": trace,
        "elapsed_s": round(time.time() - t0, 1),
    }


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except (OSError, UnicodeDecodeError):
        return ""


def _vram_gb() -> float:
    """Best-effort VRAM reading. Reported in health, not used for scoring."""
    try:
        out = subprocess.run(
            ["rocm-smi", "--showmemuse", "--csv"],
            capture_output=True, text=True, timeout=10,
        ).stdout
        for line in out.splitlines():
            parts = line.split(",")
            if len(parts) >= 2 and parts[-1].strip().isdigit():
                return round(int(parts[-1]) / (1024 ** 3), 1)
    except (OSError, subprocess.SubprocessError):
        pass
    return 0.0
