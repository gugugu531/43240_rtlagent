"""Submission endpoint.

A thin HTTP shell around run.sh / run_baseline.sh. The agent itself does not
change -- it still reads a directory and writes a file.

The protocol is asynchronous. POST /v1/solve queues the task and returns a
job id at once; the organisers then poll GET /v1/jobs/<id> until it reports
"done". A synchronous request that stayed open for the whole task would not
survive the platform: its front door cuts any response that takes longer than
60 seconds (HTTP 504), while the service carries on solving. Every request
here returns in well under a second.

One worker solves one task at a time, in arrival order.

    export FPGACHINA_TOKEN=<token issued by the organisers>
    export MODEL_NAME=qwen38-27b-q4-k-m
    ./serve/run_api.sh start

Bind 127.0.0.1, not 0.0.0.0. Radeon Cloud's rc-tunnel only picks up HTTP
services bound to the loopback interface; a service on 0.0.0.0 is never
exposed, and from the organisers' side that is indistinguishable from a
crash. Expose it with `rc-tunnel expose --port 7860`; only one port per
notebook can be exposed, so leave llama.cpp's 8000 internal.

The public app URL carries no platform-level auth, so the token check below is
not optional -- without it anyone who learns the URL can submit tasks.

See README.md in this directory for the submission lifecycle, process-group cleanup and child reaping contract.
"""

from __future__ import annotations

import ctypes
from contextlib import asynccontextmanager
import hmac
import ipaddress
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import tempfile
import threading
import time
import uuid
from types import SimpleNamespace
from typing import Literal
import urllib.request
from urllib.parse import urlsplit

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from agent.observability.redaction import ENV_SECRETS
from serve.live_runs import RunFeed
from serve.ui_control import TaskCatalog, local_control, persist_mode


@asynccontextmanager
async def _lifespan(app):
    with local_control(_control):
        yield


app = FastAPI(title="rtlagent2026 submission endpoint", lifespan=_lifespan)

TOKEN = os.environ.get("FPGACHINA_TOKEN", "")
TRACK = "rtl"

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRATCH = os.environ.get("AGENT_TMP", "/var/tmp")
_ASSETS = Path(HERE) / "ui"
_UI_ON = False
_MODE = "submission"
_ACTIVE_ID = None
_RECENT = []
_PENDING = set()


class _DisplayJSON(JSONResponse):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.headers["Cache-Control"] = "no-store"

    def render(self, content):
        # Keep unpaired surrogates from external task text valid on the wire.
        # The solver doesn't receive the presentation and submission credentials.
        # Scrub their literal values here too, including any echoed in a message.
        secrets = {TOKEN, *(os.environ.get(key) for key in ENV_SECRETS)}
        secrets = tuple(sorted(filter(None, secrets), key=len, reverse=True))
        if secrets:
            content = _display_copy(content, secrets)
        return json.dumps(content, allow_nan=False, ensure_ascii=True, separators=(",", ":")).encode("ascii")


def _display_copy(value, secrets):
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, "[凭据已隐藏]")
        return value
    if isinstance(value, dict):
        return {_display_copy(k, secrets): _display_copy(v, secrets) for k, v in value.items()}
    if isinstance(value, list):
        return [_display_copy(item, secrets) for item in value]
    return value


_PAGE_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'self'; connect-src 'self'; script-src 'self'; "
                               "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                               "object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
}


def _become_subreaper() -> bool:
    """Adopt our own orphans instead of leaving them to PID 1.

    On Radeon Cloud, PID 1 in the instance is JupyterLab, and it never reaps
    the orphans it inherits. Every process of a killed task whose parent died
    first ends up there as a zombie: it holds no CPU or memory, but it keeps
    its PID forever, and enough of them exhaust the container's PID limit --
    after which no new process can start and every later task fails.

    As a child subreaper (prctl PR_SET_CHILD_SUBREAPER), this process becomes
    the new parent of any orphaned descendant, and _run_task reaps them.
    """
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        return libc.prctl(36, 1, 0, 0, 0) == 0     # 36 = PR_SET_CHILD_SUBREAPER
    except (OSError, AttributeError):
        return False


SUBREAPER = _become_subreaper()


class SolveRequest(BaseModel):
    task_id: str
    nonce: str = ""
    mode: Literal["agent", "baseline"] = "agent"
    prompt: str
    interface: str = ""
    deadline_s: int = Field(default=900, strict=True, gt=0)


def _check_token(authorization: str | None) -> None:
    if not TOKEN:
        raise HTTPException(status_code=500, detail="FPGACHINA_TOKEN not set")
    if authorization != f"Bearer {TOKEN}":
        raise HTTPException(status_code=401, detail="bad token")


@app.get("/v1/health")
def health(authorization: str | None = Header(default=None)):
    _check_token(authorization)
    with _LOCK:
        if _MODE != "submission":
            raise HTTPException(status_code=503, detail="当前只接受本地选题")
    try:
        config, _ = _service_config()
        manifest = json.loads((Path(ROOT) / "manifest.json").read_text())
        model_name = manifest["model"]["name"]
        alias = manifest["serving"]["model_alias"]
        if not isinstance(model_name, str) or not model_name:
            raise ValueError("missing declared model")
        if config.services.model.model not in (alias, model_name):
            raise ValueError("configured model differs from manifest")
        if os.environ.get("MODEL_NAME", config.services.model.model) != config.services.model.model:
            raise ValueError("baseline model differs from agent model")
        _check_agent(config)
        _check_model(config.services.model)
        vram = _vram_gb()
        if vram is None:
            raise ValueError("current GPU memory measurement unavailable")
    except Exception as exc:
        # Do not advertise readiness or fabricate a numeric measurement when
        # the service, configuration or monitoring is unavailable.
        raise HTTPException(status_code=503, detail="service readiness check failed") from exc
    return {
        "ready": True,
        "track": TRACK,          # mismatched track => the organisers refuse to submit
        "model": model_name,
        "vram_gb": vram,
    }


@app.post("/v1/solve", status_code=202)
def solve(req: SolveRequest, authorization: str | None = Header(default=None)):
    if not TOKEN:
        with _LOCK:
            if _MODE == "local":
                raise HTTPException(status_code=503, detail="当前只接受本地选题")
    _check_token(authorization)
    with _LOCK:
        # A retry, including after a mode switch, still identifies the original job.
        if req.nonce and req.nonce in _BY_NONCE:
            return _public(_JOBS[_BY_NONCE[req.nonce]])
        if _MODE != "submission":
            raise HTTPException(status_code=503, detail="当前只接受本地选题")
        return _enqueue(req, "submission")


@app.get("/v1/jobs/{job_id}")
def job_status(job_id: str, authorization: str | None = Header(default=None)):
    _check_token(authorization)
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None or job.get("source") == "local":
            raise HTTPException(status_code=404, detail="unknown job_id")
        return _public(job)


_JOBS: dict[str, dict] = {}
_BY_NONCE: dict[str, str] = {}
_LOCK = threading.Lock()
_QUEUE: queue.Queue[str] = queue.Queue()


def _enqueue(req, source):
    """Caller holds _LOCK so mode changes and admission have one ordering."""
    job_id = uuid.uuid4().hex
    job = dict(job_id=job_id, task_id=req.task_id, status="queued", source=source,
               req=req, submitted=time.time(), started=None, finished=None, feed=RunFeed())
    _JOBS[job_id] = job
    _PENDING.add(job_id)
    if source == "submission" and req.nonce:
        _BY_NONCE[req.nonce] = job_id
    _QUEUE.put(job_id)
    return _public(job)


def _operator_token():
    value = os.environ.get("RTLAGENT_UI_OPERATOR_TOKEN", "")
    return value if value and value != TOKEN else None


def _control(command, value):
    global _MODE, _UI_ON
    with _LOCK:
        if command == "restore":
            _UI_ON = False
            _MODE = "local" if not TOKEN and _operator_token() and os.environ.get("RTLAGENT_UI_TASKS") else value
        elif command == "ui":
            if value in ("on", "off"):
                _UI_ON = value == "on"
        elif command == "mode" and value != _MODE:
            if _PENDING:
                return {"error": "仍有排队或运行中的题目，结束后可切换题源。"}
            if value == "submission" and not TOKEN:
                return {"error": "投题模式需要赛事令牌。"}
            if value == "local" and not (_operator_token() and os.environ.get("RTLAGENT_UI_TASKS")):
                return {"error": "选题模式需要题库目录和独立的演示者口令。"}
            persist_mode(value)
            _MODE = value
        return {"ui": _UI_ON, "mode": _MODE, "busy": bool(_PENDING)}


def _presentation(*, local=False):
    if not _UI_ON:
        raise HTTPException(status_code=404, detail="展示页已关闭")
    if local and _MODE != "local":
        raise HTTPException(status_code=409, detail="当前只接受赛事投题")


def _display_info(job):
    fields = ("job_id", "task_id", "source", "status", "submitted", "started", "finished")
    return {key: job[key] for key in fields}


@app.get("/ui", include_in_schema=False)
@app.get("/ui/", include_in_schema=False)
def display():
    with _LOCK:
        _presentation()
    return FileResponse(_ASSETS / "index.html", media_type="text/html", headers=_PAGE_HEADERS)


@app.get("/ui/assets/{name}", include_in_schema=False)
def display_asset(name: str):
    with _LOCK:
        _presentation()
    types = {"style.css": "text/css", "app.js": "text/javascript"}
    if name not in types:
        raise HTTPException(status_code=404)
    return FileResponse(_ASSETS / name, media_type=types[name], headers=_PAGE_HEADERS)


@app.get("/ui/api/state", response_class=_DisplayJSON, include_in_schema=False)
def display_state():
    with _LOCK:
        _presentation()
        waiting = sorted((_JOBS[i] for i in _PENDING if i != _ACTIVE_ID),
                         key=lambda j: j["submitted"])
        shown = ([_JOBS[_ACTIVE_ID]] if _ACTIVE_ID else []) + waiting + [_JOBS[i] for i in _RECENT]
        return {"mode": _MODE, "active_id": _ACTIVE_ID, "runs": [_display_info(j) for j in shown]}


@app.get("/ui/api/runs/{job_id}", response_class=_DisplayJSON, include_in_schema=False)
def display_run(job_id: str, after: int = Query(default=0, ge=0)):
    with _LOCK:
        _presentation()
        if job_id not in _PENDING and job_id not in _RECENT:
            raise HTTPException(status_code=404, detail="该题已离开展示记录")
        job = _JOBS[job_id]
        info = dict(**_display_info(job), prompt=job["req"].prompt, solution=job.get("solution"))
        feed = job["feed"]
        error = job.get("display_error")
    page = feed.page(after)
    if error:
        page["error"] = error
    elif info["status"] == "done" and not page["events"] and after == 0 and job["req"].mode == "agent":
        page["error"] = page["error"] or "本题未产生可展示的流程记录。"
    return {**info, **page}


def _catalog():
    try:
        return TaskCatalog(os.environ.get("RTLAGENT_UI_TASKS"))
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="题库配置无效") from exc


@app.get("/ui/api/tasks", response_class=_DisplayJSON, include_in_schema=False)
def display_tasks():
    with _LOCK:
        _presentation(local=True)
    try:
        return {"tasks": _catalog().list()}
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="题库暂不可用") from exc


def _task_prompt(task_id):
    try:
        return _catalog().prompt(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="找不到这道题") from exc


@app.get("/ui/api/task", response_class=_DisplayJSON, include_in_schema=False)
def display_task(task_id: str):
    with _LOCK:
        _presentation(local=True)
    return {"task_id": task_id, "prompt": _task_prompt(task_id)}


class LocalSelection(BaseModel):
    task_id: str


@app.post("/ui/api/runs", status_code=202, response_class=_DisplayJSON, include_in_schema=False)
def start_local(selection: LocalSelection, authorization: str | None = Header(default=None)):
    with _LOCK:
        _presentation(local=True)
    secret = _operator_token()
    if secret is None:
        raise HTTPException(status_code=503, detail="服务尚未配置独立的演示者口令")
    if not hmac.compare_digest((authorization or "").encode(), f"Bearer {secret}".encode()):
        raise HTTPException(status_code=401, detail="请输入正确的演示者口令")
    req = SolveRequest(task_id=selection.task_id, prompt=_task_prompt(selection.task_id))
    with _LOCK:
        _presentation(local=True)
        if _PENDING:
            raise HTTPException(status_code=409, detail="当前有题目正在处理")
        return _enqueue(req, "local")


def _public(job: dict) -> dict:
    out = {k: job[k] for k in ("job_id", "task_id", "status")}
    if job["status"] == "done":
        out.update(solution=job["solution"],   # empty string means "could not solve it"
                   trace=job["trace"], elapsed_s=job["elapsed_s"])
    return out


def _worker() -> None:
    global _ACTIVE_ID
    while True:
        job_id = _QUEUE.get()
        with _LOCK:
            job = _JOBS[job_id]
            job.update(status="running", started=time.time())
            _ACTIVE_ID = job_id
        error = None
        try:
            solution, trace = _solve(job["req"], job["submitted"], feed=job["feed"],
                                     local=job["source"] == "local")
        except Exception:                      # never leave a job stuck in "running"
            solution, trace = "", ""
            error = "求解服务未能完成此题。"
        with _LOCK:
            ended = time.time()
            job.update(status="done", solution=solution, trace=trace,
                       finished=ended, elapsed_s=round(ended - job["submitted"], 1),
                       display_error=error)
            _ACTIVE_ID = None
            _PENDING.discard(job_id)
            _RECENT.insert(0, job_id)
            if len(_RECENT) > 2:
                stale = _JOBS[_RECENT.pop()]
                stale.pop("feed").discard()
                if stale["source"] == "local":
                    del _JOBS[stale["job_id"]]
            _QUEUE.task_done()


def _solve(req: SolveRequest, submitted: float, *, feed=None, local=False) -> tuple[str, str]:
    script = "run.sh" if req.mode != "baseline" else "run_baseline.sh"
    # The organisers' clock starts at submission, so time spent queued counts.
    left = req.deadline_s - (time.time() - submitted)
    if left <= 0:
        return "", ""

    config, config_path = _service_config(local=local)

    with tempfile.TemporaryDirectory(dir=SCRATCH) as work:
        in_dir = os.path.join(work, "in")
        out_dir = os.path.join(work, "out")
        os.makedirs(in_dir)
        os.makedirs(out_dir)

        with open(os.path.join(in_dir, "prompt.txt"), "w", encoding="utf-8") as fh:
            fh.write(req.prompt)
        with open(os.path.join(in_dir, "interface.txt"), "w", encoding="utf-8") as fh:
            fh.write(req.interface)

        # baseline.py intentionally does not read the agent YAML. Pass the
        # same effective endpoint/model to both entry points, including when
        # those values came from nested RTLAGENT_* environment overrides.
        model = config.services.model
        # The HTTP service is RTL-only. A stale host TRACK must not send the
        # untouched official baseline down its HLS output path.
        env = dict(os.environ, TRACK=TRACK, AGENT_CONFIG=str(config_path),
                   LLM_BACKEND=model.backend, LLM_BASE_URL=model.base_url,
                   LLM_MODEL=model.model, MODEL_NAME=model.model)
        # Inference and EDA do not need HTTP or operator credentials.
        for key in ("FPGACHINA_TOKEN", "RTLAGENT_UI_OPERATOR_TOKEN", "RTLAGENT_UI_TASKS"):
            env.pop(key, None)
        if feed is not None and req.mode == "agent":
            env["RTLAGENT_LIVE_EVENTS"] = "1"
        left = req.deadline_s - (time.time() - submitted)
        if left <= 0:
            return "", ""
        cmd = [os.path.join(ROOT, script), in_dir, out_dir]
        if req.mode == "agent":
            cmd += ["--hard-deadline-s", str(left)]
        # 在赛事方超时之前自行停止并返回已有结果。
        if feed is not None and req.mode == "agent":
            feed.attach(out_dir)
        try:
            _run_task(cmd, env=env, timeout_s=max(left - 10, 0.001))
        finally:
            if feed is not None:
                feed.finish(baseline=req.mode == "baseline")

        solution = _read(os.path.join(out_dir, "solution.v"))
        return (solution if solution.strip() else "",
                _complete_trace_fields(_read(os.path.join(out_dir, "trace.jsonl"))))


def _complete_trace_fields(trace: str) -> str:
    """Add optional API fields without inventing timestamps, usage or success.

    Keep the original trace file untouched. Invalid source lines become explicit
    API diagnostics carrying the original line, never guessed tool results.
    """
    defaults = dict(ts=None, tool=None, rc=None, excerpt="",
                    tokens_in=None, tokens_out=None)

    def reject_constant(value):
        raise ValueError("non-finite JSON constant: " + value)

    rows = []
    for number, line in enumerate(trace.split("\n"), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line, parse_constant=reject_constant)
            if not isinstance(row, dict):
                raise ValueError("trace line must be a JSON object")
            encoded = json.dumps({**defaults, **row}, ensure_ascii=True, allow_nan=False)
        except (ValueError, RecursionError):
            encoded = json.dumps({
                **defaults, "ts": time.time(), "tool": "api",
                "event": "invalid_trace_line", "source_line": number,
                "excerpt": "Invalid source trace line; original text retained.",
                "raw_line": line,
            }, ensure_ascii=True, allow_nan=False)
        rows.append(encoded)
    return "".join(row + "\n" for row in rows)


threading.Thread(target=_worker, daemon=True).start()


def _run_task(cmd: list[str], env: dict, timeout_s: float, grace_s: float = 5) -> None:
    """Run one task in its own process group and leave nothing behind.

    run.sh starts the agent, which starts Vivado / xsim. Killing run.sh alone
    (what subprocess.run(timeout=...) does) orphans all of those; they keep the
    GPU and the CPU busy while the next task runs. So run.sh gets a process
    group of its own, and the whole group is signalled: SIGTERM at the
    deadline, SIGKILL after grace_s. The group is swept once more after a
    normal exit, for anything the agent left running in the background.
    """
    proc = subprocess.Popen(
        cmd,
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        _signal_group(proc.pid, signal.SIGTERM)
        try:
            proc.wait(timeout=grace_s)
        except subprocess.TimeoutExpired:
            pass
    _signal_group(proc.pid, signal.SIGKILL)
    proc.wait()
    _reap_group(proc.pid)


def _signal_group(pgid: int, sig: int) -> None:
    try:
        os.killpg(pgid, sig)
    except ProcessLookupError:
        pass


def _reap_group(pgid: int, timeout_s: float = 5) -> None:
    """Reap the orphans of one task that were handed to us as subreaper.

    Only children in the task's process group are touched, so the exit status
    of any other subprocess (rocm-smi in /v1/health, say) is never stolen.
    SIGKILL is asynchronous, hence the short polling loop.
    """
    deadline = time.time() + timeout_s
    while True:
        left = [pid for pid, pg in _children() if pg == pgid]
        for pid in left:
            try:
                os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                pass
        if not left or time.time() > deadline:
            return
        time.sleep(0.1)


def _children() -> list[tuple[int, int]]:
    """(pid, pgid) of every direct child of this process, zombies included."""
    me, out = os.getpid(), []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/stat") as fh:
                stat = fh.read()
        except OSError:
            continue
        # The command name is in parentheses and may contain spaces.
        fields = stat[stat.rindex(")") + 2:].split()
        if int(fields[1]) == me:                   # state ppid pgrp ...
            out.append((int(entry), int(fields[2])))
    return out


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except (OSError, UnicodeDecodeError):
        return ""


def _service_config(*, local=False):
    """Resolve the same YAML/environment settings that run.sh will use."""
    from agent.config import load_config

    path = Path(os.environ.get("AGENT_CONFIG") or Path(ROOT) / "config/guided_verify.yaml")
    if not path.is_absolute():
        path = Path(ROOT) / path
    config, _ = load_config(path)
    allowed = ("openai", "mock") if local else ("openai",)
    if config.services.model.backend not in allowed or not config.services.model.model:
        raise ValueError("submission requires a configured local model service")
    _require_loopback(config.services.model.base_url)
    for profile in config.services.profiles.values():
        if profile.enabled and profile.base_url:
            _require_loopback(profile.base_url)
    _check_embedding_endpoints(config.model_dump())
    return config, path.resolve()


def _require_loopback(url: str) -> None:
    parsed = urlsplit(url)
    hostname = parsed.hostname
    if parsed.scheme not in ("http", "https") or not hostname:
        raise ValueError("submission service requires a local HTTP URL")
    # Accessing port also rejects malformed/out-of-range ports.
    _ = parsed.port
    if hostname.lower() == "localhost":
        return
    if not ipaddress.ip_address(hostname).is_loopback:
        raise ValueError("submission service must use a loopback address")


def _check_embedding_endpoints(value) -> None:
    if isinstance(value, dict):
        if value.get("embedding_url"):
            _require_loopback(value["embedding_url"])
        if value.get("embedding_transport") == "ssh":
            raise ValueError("submission embedding service must use local HTTP")
        for nested in value.values():
            _check_embedding_endpoints(nested)
    elif isinstance(value, list):
        for nested in value:
            _check_embedding_endpoints(nested)


def _check_agent(config) -> None:
    """Validate entry points and graph construction without solving a task."""
    for name in ("run.sh", "run_baseline.sh"):
        if not os.access(Path(ROOT) / name, os.X_OK):
            raise ValueError("submission entry point unavailable")
    from agent.orchestration.graph import build_graph
    from agent.tools.registry import load_plugins
    import agent.orchestration.nodes  # noqa: F401
    import agent.orchestration.workflows  # noqa: F401

    load_plugins(config.plugins)
    if config.runtime.recording.burr_tracker and config.runtime.recording.level != "full":
        raise ValueError("Burr tracker requires full recording")
    config = config.model_copy(deep=True)
    config.runtime.recording.burr_tracker = False
    with tempfile.TemporaryDirectory(dir=SCRATCH) as work:
        record = SimpleNamespace(run_id="health", record_dir=Path(work),
                                 emit=lambda *args, **kwargs: None)
        build_graph(SimpleNamespace(config=config, record=record))


def _check_model(model) -> None:
    # Probe without authentication just as the fixed baseline does. A service
    # that only the agent can access is not ready for same-service evaluation.
    base = model.base_url.rstrip("/")
    health_url = base.removesuffix("/v1") + "/health"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(health_url, timeout=2) as response:
        if response.status != 200:
            raise ValueError("model is not loaded")
    with opener.open(base + "/models", timeout=2) as response:
        models = json.load(response)
    if model.model not in {item["id"] for item in models["data"]}:
        raise ValueError("declared model is not served")


def _vram_gb(sysfs: Path = Path("/sys/class/drm"),
             devices: Path = Path("/dev/dri")) -> float | None:
    """Measure visible AMD devices in GiB; missing data remains unknown.

    mem_info_vram_used is a byte count, unlike rocm-smi --showmemuse's
    percentage. Deduplicate DRM aliases and include all visible GPU usage.
    """
    measured = {}
    try:
        for entry in sysfs.iterdir():
            if not (devices / entry.name).exists():
                continue
            device = (entry / "device").resolve()
            vendor = device / "vendor"
            if not vendor.exists() or vendor.read_text().strip().lower() != "0x1002":
                continue
            used = int((device / "mem_info_vram_used").read_text().strip())
            if used < 0:
                return None
            measured[device] = used
    except (OSError, ValueError):
        return None
    return round(sum(measured.values()) / (1024 ** 3), 3) if measured else None
