#!/usr/bin/env python3
"""Submission emulation, client side: play the organisers' submission machine.

    ./submit_client.py [--url URL] [--tasks DIR] [--samples N] [--tag NAME] ...

    ./submit_client.py --tag smoke --limit 3
    ./submit_client.py --tag soak --tasks ../../../tasks --samples 5

Follows docs/API_CONTRACT.md to the letter:

  - GET /v1/health first; refuse to submit unless ready and track == "rtl",
    and check that a request without the token is rejected
  - POST /v1/solve per task and sample, mode "agent" and "baseline" against the
    same endpoint, interface always "" (the evaluation set never sends one),
    client timeout deadline_s + 20
  - wall clock measured here, request sent to response received -- the number
    that scores, unlike the self-reported elapsed_s
  - any transport failure (timeout, disconnect, bad JSON, task_id not echoed)
    counts as L0, no retry

Outputs use selftest/out's layout, so judge.py and score.py grade them
unchanged. Defaults come from remote.env; only the standard library is used.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
AGENT_ROOT = os.path.dirname(os.path.dirname(HERE))
REPO_ROOT = os.path.dirname(AGENT_ROOT)
SELFTEST = os.path.join(REPO_ROOT, "selftest")

sys.path.insert(0, HERE)
import record  # noqa: E402

_print_lock = threading.Lock()


def log(msg: str) -> None:
    with _print_lock:
        print(msg, flush=True)


def load_remote_env() -> dict:
    """KEY=VALUE lines of remote.env, without running it through a shell."""
    env = {}
    try:
        with open(os.path.join(HERE, "remote.env"), encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip().strip("'\"")
    except OSError:
        pass
    return env


def http(method: str, url: str, token: str | None, body: dict | None,
         timeout: float) -> tuple[int, dict | str]:
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
            status = r.status
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")[:500]
    try:
        return status, json.loads(raw)
    except ValueError:
        return status, raw[:500]


def check_health(url: str, token: str) -> str:
    status, body = http("GET", url + "/v1/health", token, None, 30)
    if status != 200 or not isinstance(body, dict):
        sys.exit(f"✗ /v1/health 失败：HTTP {status} {body}")
    if body.get("track") != "rtl":
        sys.exit(f"✗ track 为 {body.get('track')!r}，不是 'rtl'，赛事方会拒绝投题")
    if body.get("ready") is not True:
        sys.exit(f"✗ ready 不是 true：{body}")
    log(f"✓ health         model={body.get('model')}  vram_gb={body.get('vram_gb')}")

    status, _ = http("GET", url + "/v1/health", None, None, 30)
    if status != 401:
        log(f"⚠ 不带令牌的请求返回 HTTP {status}，而不是 401，说明没有验证令牌，公网上任何人都能调用")
    return str(body.get("model"))


def list_tasks(tasks_dir: str) -> list[str]:
    out = []
    for name in sorted(os.listdir(tasks_dir)):
        d = os.path.join(tasks_dir, name)
        if os.path.isfile(os.path.join(d, "task.json")) and \
                os.path.isfile(os.path.join(d, "prompt.txt")):
            out.append(d)
    return out


def solve_one(args, run_dir: str, mode: str, task_dir: str, k: int) -> dict:
    tid = os.path.basename(task_dir)
    dst = os.path.join(run_dir, mode, tid, f"s{k}")
    os.makedirs(dst, exist_ok=True)
    with open(os.path.join(task_dir, "prompt.txt"), encoding="utf-8") as fh:
        prompt = fh.read()

    req = {
        "task_id": tid,
        "nonce": f"{tid}-{mode}-{k}-{secrets.token_hex(8)}",
        "mode": mode,
        "prompt": prompt,
        "interface": "",
        "deadline_s": args.deadline,
    }
    t0 = time.time()
    error = None
    try:
        status, body = http("POST", args.url + "/v1/solve", args.token, req,
                            args.deadline + 20)
        if status != 200:
            error = f"HTTP {status}: {str(body)[:200]}"
        elif not isinstance(body, dict):
            error = f"响应不是 JSON 对象：{str(body)[:200]}"
        elif body.get("task_id") != tid:
            error = f"task_id 未原样带回：{body.get('task_id')!r}"
        elif not isinstance(body.get("solution"), str) or not isinstance(body.get("trace"), str):
            error = "solution / trace 字段缺失或不是字符串"
    except Exception as exc:  # timeout, reset, DNS ... all L0 per contract
        body, error = None, f"{type(exc).__name__}: {exc}"
    wall = round(time.time() - t0, 2)

    ok = error is None
    solution = body["solution"] if ok else ""
    with open(os.path.join(dst, "solution.v"), "w", encoding="utf-8") as fh:
        fh.write(solution)
    with open(os.path.join(dst, "trace.jsonl"), "w", encoding="utf-8") as fh:
        fh.write(body["trace"] if ok else "")
    info = {"task_id": tid, "mode": mode, "sample": k, "wall_s": wall,
            "reported_elapsed_s": body.get("elapsed_s") if ok else None,
            "transport_error": error, "solution_bytes": len(solution)}
    with open(os.path.join(dst, "response.json"), "w", encoding="utf-8") as fh:
        json.dump(info, fh, ensure_ascii=False, indent=2)

    head = f"{mode:<8} {tid:<24} s{k}  {wall:7.1f}s"
    log(f"{head}  ✗ {error}" if error else f"{head}  {len(solution)} B")

    if not args.no_judge:
        # Same file naming as run_selftest.sh so score.py aggregates it as is.
        res = subprocess.run(
            [sys.executable, os.path.join(SELFTEST, "judge.py"),
             "--task", task_dir, "--solution", os.path.join(dst, "solution.v"),
             "--outdir", os.path.join(run_dir, "logs"),
             "--json", os.path.join(run_dir, "results", f"{mode}.{tid}.s{k}.json")],
            capture_output=True, text=True)
        log("         " + (res.stdout.strip() or res.stderr.strip()[-300:]))
    return info


def main() -> int:
    renv = load_remote_env()
    ap = argparse.ArgumentParser(description="模拟赛事方投题机")
    ap.add_argument("--url", default=f"http://127.0.0.1:{renv.get('LOCAL_API_PORT', '7860')}",
                    help="投题接口根地址，默认本机 serve_local.sh")
    ap.add_argument("--token", default=os.environ.get("FPGACHINA_TOKEN")
                    or renv.get("FPGACHINA_TOKEN", ""))
    ap.add_argument("--tasks", default=os.path.join(REPO_ROOT, "tasks"))
    ap.add_argument("--modes", default="agent,baseline")
    ap.add_argument("--samples", type=int, default=1)
    ap.add_argument("--deadline", type=int, default=360, help="deadline_s，单题时间上限（秒）")
    ap.add_argument("--concurrency", type=int, default=1)
    ap.add_argument("--limit", type=int, default=0, help="只投前 N 道题")
    ap.add_argument("--tag", default="submit")
    ap.add_argument("--no-judge", action="store_true", help="只投题，不做 Vivado 判定")
    args = ap.parse_args()
    args.url = args.url.rstrip("/")
    if not args.token:
        sys.exit("✗ 没有令牌：请用 --token 指定，或在 remote.env 中设置 FPGACHINA_TOKEN")

    tasks = list_tasks(args.tasks)[: args.limit or None]
    if not tasks:
        sys.exit(f"✗ {args.tasks} 下没有题目")
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]

    model = check_health(args.url, args.token)
    os.environ.setdefault("LLM_MODEL", model)

    run_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{args.tag}"
    run_dir = os.path.join(AGENT_ROOT, "dev", "runs", run_id)
    record.write_meta(run_dir, "submit_client", sys.argv[1:])
    os.makedirs(os.path.join(run_dir, "results"), exist_ok=True)
    log(f"✓ 运行目录       dev/runs/{run_id}")
    log(f"  {len(tasks)} 题 × {args.samples} 次 × {modes}，并发 {args.concurrency}")

    jobs = [(m, t, k) for m in modes for t in tasks for k in range(args.samples)]
    with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as pool:
        infos = list(pool.map(lambda j: solve_one(args, run_dir, *j), jobs))

    # Sum of request round trips only: local judging runs in the same worker and
    # must not leak into the number the cost item is scored on.
    walls = [i["wall_s"] for i in infos]
    total = round(sum(walls), 1)
    wallclock = {"total_s": total, "max_s": max(walls), "mean_s": round(total / len(walls), 2),
                 "transport_errors": sum(1 for i in infos if i["transport_error"])}
    with open(os.path.join(run_dir, "responses.json"), "w", encoding="utf-8") as fh:
        json.dump({"wallclock": wallclock, "samples": infos}, fh, ensure_ascii=False, indent=2)
    log(f"\n请求耗时合计 {total}s（不含本地判定），单题最长 {wallclock['max_s']}s，"
        f"请求失败 {wallclock['transport_errors']} 次（按 L0 未通过计）")

    if args.no_judge:
        return 0
    score_path = os.path.join(run_dir, "score.json")
    subprocess.run([sys.executable, os.path.join(SELFTEST, "score.py"),
                    "--results", os.path.join(run_dir, "results"), "--json", score_path])
    try:
        with open(score_path, encoding="utf-8") as fh:
            score = json.load(fh)
        score["wallclock"] = wallclock
        with open(score_path, "w", encoding="utf-8") as fh:
            json.dump(score, fh, ensure_ascii=False, indent=2)
    except (OSError, ValueError):
        pass
    record.write_summary(run_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
