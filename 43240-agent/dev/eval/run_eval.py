#!/usr/bin/env python3
"""Parallel scoring run: solve, judge, score, analyse, record.

    run_eval.py --tag NAME [--tasks DIR] [--taskset NAME|FILE] [--modes agent,baseline]
                [--samples N] [--jobs N] [--judge-jobs N] [--limit N] ...

    run_eval.py --tag ref --modes reference              # check the judging chain
    run_eval.py --tag smoke --taskset smoke              # a few tasks, quick look
    run_eval.py --tag veval --samples 1 --jobs 8         # the whole task set

Does what selftest/run_selftest.sh does, with the same judge (selftest/judge.py)
and the same scorer (selftest/score.py), plus:

  - solving and judging run in parallel pools instead of one sample at a time
  - every sample keeps its own judge log and raw verdict (run_selftest.sh keeps
    one log per task, overwritten by each sample and mode)
  - solve wall clock per sample, a hard solve timeout, task subsets and a list
    of known-broken tasks left out by default
  - analyze.py classifies every failure; record.py writes the experiment note

Uses the LLM and Vivado environment of the calling shell; see dev/eval/README.md.
Artefacts go to dev/runs/<run_id>/, the note to dev/experiments/<run_id>.md.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
DEV_ROOT = os.path.dirname(HERE)
AGENT_ROOT = os.path.dirname(DEV_ROOT)
REPO_ROOT = os.path.dirname(AGENT_ROOT)
SELFTEST = os.path.join(REPO_ROOT, "selftest")
TASKSETS = os.path.join(HERE, "tasksets")

sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(DEV_ROOT, "remote"))
import analyze  # noqa: E402
import metrics  # noqa: E402
import record  # noqa: E402

_lock = threading.Lock()


def log(msg: str) -> None:
    with _lock:
        print(msg, flush=True)


# -------------------------------------------------------------------- tasks

def read_list(path: str) -> list[str]:
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.split("#", 1)[0].strip()
            if line:
                out.append(line)
    return out


def resolve_taskset(name: str) -> str:
    if os.path.isfile(name):
        return name
    path = os.path.join(TASKSETS, f"{name}.txt")
    if os.path.isfile(path):
        return path
    sys.exit(f"✗ 找不到题目子集 {name}（既不是文件，也不在 {os.path.relpath(TASKSETS)} 下）")


def list_tasks(args) -> list[str]:
    tasks_dir = os.path.abspath(args.tasks)
    found = sorted(n for n in os.listdir(tasks_dir)
                   if os.path.isfile(os.path.join(tasks_dir, n, "task.json")))
    if args.taskset:
        wanted = read_list(resolve_taskset(args.taskset))
        missing = [t for t in wanted if t not in found]
        if missing:
            sys.exit(f"✗ 子集中的题目在 {tasks_dir} 下不存在：{', '.join(missing[:10])}")
        found = wanted
    if not args.no_exclude:
        excluded = set(read_list(os.path.join(TASKSETS, "exclude.txt")))
        dropped = [t for t in found if t in excluded]
        if dropped:
            log(f"  已排除         {', '.join(dropped)}（见 tasksets/exclude.txt，--no-exclude 可关闭）")
        found = [t for t in found if t not in excluded]
    if args.limit:
        found = found[: args.limit]
    return [os.path.join(tasks_dir, t) for t in found]


# ------------------------------------------------------------------ checks

def check_env(args) -> None:
    missing = [c for c in ("xvlog", "xelab", "xsim", "vivado") if not shutil.which(c)]
    if missing and not args.no_judge:
        sys.exit(f"✗ PATH 中没有 {', '.join(missing)}：先 source Vivado 的 settings64.sh，"
                 "或用 --no-judge 只求解不判定")
    backend = os.environ.get("LLM_BACKEND", "mock")
    if "baseline" in args.modes and backend == "mock" and not args.force_baseline:
        # Same reasoning as run_selftest.sh: mock only applies to agent/llm.py,
        # baseline.py would still hit LLM_BASE_URL -- a gain between two
        # different models is meaningless and looks normal.
        args.modes.remove("baseline")
        log("  基线           跳过（LLM_BACKEND=mock 对 baseline.py 无效，增益不计；"
            "--force-baseline 可强制运行）")
    log(f"  LLM 后端       {backend}"
        f"{'  ->  ' + os.environ['LLM_BASE_URL'] if os.environ.get('LLM_BASE_URL') else ''}"
        f"{'  (' + os.environ['LLM_MODEL'] + ')' if os.environ.get('LLM_MODEL') else ''}")


# ------------------------------------------------------------ one sample

def solve(args, run_dir: str, mode: str, task_dir: str, k: int) -> str:
    tid = os.path.basename(task_dir)
    dst = os.path.join(run_dir, mode, tid, f"s{k}")
    os.makedirs(dst, exist_ok=True)
    info = {"task_id": tid, "mode": mode, "sample": k, "timed_out": False, "rc": 0}
    t0 = time.time()

    if mode == "reference":
        with open(os.path.join(task_dir, "task.json"), encoding="utf-8") as fh:
            ref = json.load(fh)["reference"]
        shutil.copyfile(os.path.join(task_dir, ref), os.path.join(dst, "solution.v"))
    else:
        script = os.path.join(AGENT_ROOT, "run.sh" if mode == "agent" else "run_baseline.sh")
        with open(os.path.join(dst, "run.log"), "w", encoding="utf-8") as out:
            # New session so a timeout kills the whole tree (python, xvlog, vivado).
            proc = subprocess.Popen([script, task_dir, dst], stdout=out,
                                    stderr=subprocess.STDOUT, start_new_session=True)
            try:
                info["rc"] = proc.wait(timeout=args.solve_timeout)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
                info["timed_out"] = True
                # Past the deadline the organisers score L0 whatever was written.
                with open(os.path.join(dst, "solution.v"), "w", encoding="utf-8"):
                    pass
        for name in ("solution.v", "trace.jsonl"):
            path = os.path.join(dst, name)
            if not os.path.exists(path):
                open(path, "w").close()

    info["wall_s"] = round(time.time() - t0, 2)
    with open(os.path.join(dst, "solve.json"), "w", encoding="utf-8") as fh:
        json.dump(info, fh, ensure_ascii=False, indent=2)
    return dst


def judge(args, run_dir: str, mode: str, task_dir: str, k: int, dst: str) -> dict:
    tid = os.path.basename(task_dir)
    res_path = os.path.join(run_dir, "results", f"{mode}.{tid}.s{k}.json")
    env = dict(os.environ, SELFTEST_KEEP_WORK="1")
    proc = subprocess.run(
        [sys.executable, os.path.join(SELFTEST, "judge.py"), "--task", task_dir,
         "--solution", os.path.join(dst, "solution.v"), "--outdir", dst,
         "--timeout", str(args.judge_timeout), "--json", res_path],
        capture_output=True, text=True, env=env)
    res = analyze._read_json(res_path) or {}
    if not res:
        log(f"✗ judge.py 没有产出结果：{mode} {tid} s{k}\n{proc.stderr[-500:]}")
        return res

    # Keep what we need from the judge's scratch dir, then drop it: 156 tasks of
    # Vivado work dirs fill /tmp quickly.
    work = res.pop("work_dir", None)
    if work and os.path.isdir(work):
        for src, name in (("verdict.json", "verdict.json"), ("w/judge.log", "judge.log"),
                          ("w/synth/synth.log", "synth.log")):
            if os.path.isfile(os.path.join(work, src)):
                shutil.copyfile(os.path.join(work, src), os.path.join(dst, name))
        shutil.rmtree(work, ignore_errors=True)
        with open(res_path, "w", encoding="utf-8") as fh:
            json.dump(res, fh, ensure_ascii=False, indent=2)
    return res


# -------------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description="并行跑分：求解、判定、汇总、分析、记录")
    ap.add_argument("--tag", default="eval", help="运行编号中的标签，如 veval-s1")
    ap.add_argument("--tasks", default=os.path.join(REPO_ROOT, "tasks"), help="题目目录")
    ap.add_argument("--taskset", default="", help="题目子集：tasksets/ 下的名字或一个文件")
    ap.add_argument("--no-exclude", action="store_true", help="不排除 tasksets/exclude.txt 中的题")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 道题")
    ap.add_argument("--modes", default="agent,baseline", help="agent / baseline / reference，逗号分隔")
    ap.add_argument("--force-baseline", action="store_true", help="桩模式下也运行基线")
    ap.add_argument("--samples", type=int, default=1)
    ap.add_argument("--jobs", type=int, default=4, help="同时求解的样本数")
    ap.add_argument("--judge-jobs", type=int, default=4, help="同时判定的样本数（每个都会启动 Vivado）")
    ap.add_argument("--solve-timeout", type=float, default=900, help="单个样本求解的时间上限（秒）")
    ap.add_argument("--judge-timeout", type=float, default=1800)
    ap.add_argument("--no-judge", action="store_true", help="只求解，不判定")
    ap.add_argument("--metrics-url", default="",
                    help="推理服务的地址（如 http://127.0.0.1:18000/v1），"
                         "跑分期间轮询 /metrics 采 KV Cache 使用率；不填则跳过")
    ap.add_argument("--metrics-interval", type=float, default=5.0,
                    help="轮询 /metrics 的间隔（秒）")
    args = ap.parse_args()
    args.modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    bad = [m for m in args.modes if m not in ("agent", "baseline", "reference")]
    if bad:
        sys.exit(f"✗ 未知模式：{', '.join(bad)}")

    check_env(args)
    tasks = list_tasks(args)
    if not tasks or not args.modes:
        sys.exit("✗ 没有要跑的题目或模式")

    run_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{args.tag}"
    run_dir = os.path.join(DEV_ROOT, "runs", run_id)
    record.write_meta(run_dir, "run_eval", sys.argv[1:])
    os.makedirs(os.path.join(run_dir, "results"), exist_ok=True)
    log(f"✓ 运行目录       dev/runs/{run_id}")
    log(f"  {len(tasks)} 题 × {args.samples} 次 × {args.modes}，"
        f"求解并发 {args.jobs}，判定并发 {args.judge_jobs}")

    # Interleave modes so agent and baseline progress together; a run cut short
    # still has comparable halves.
    jobs = [(m, t, k) for t in tasks for k in range(args.samples) for m in args.modes]
    total, done = len(jobs), [0]
    t_start = time.time()

    judge_pool = ThreadPoolExecutor(max_workers=max(1, args.judge_jobs))
    judged = []

    watcher = None
    if args.metrics_url:
        watcher = metrics.MetricsWatcher(args.metrics_url, args.metrics_interval)
        watcher.start()
        log(f"  指标轮询       {args.metrics_url} 每 {args.metrics_interval:g}s 读一次 /metrics")

    def after_solve(mode, task_dir, k, dst):
        tid = os.path.basename(task_dir)
        wall = (analyze._read_json(os.path.join(dst, "solve.json")) or {}).get("wall_s", 0)
        if args.no_judge:
            status = "（未判定）"
        else:
            res = judge(args, run_dir, mode, task_dir, k, dst)
            status = (f"L{res.get('level', 0)}" if not res.get("tool_error")
                      else f"环境失败：{str(res['tool_error'])[:60]}")
        with _lock:
            done[0] += 1
            print(f"[{done[0]:>4}/{total}] {mode:<9} {tid:<34} s{k}  "
                  f"{status:<4} 求解 {wall:6.1f}s", flush=True)

    def one(job):
        mode, task_dir, k = job
        dst = solve(args, run_dir, mode, task_dir, k)
        judged.append(judge_pool.submit(after_solve, mode, task_dir, k, dst))

    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        list(pool.map(one, jobs))
    for f in judged:
        f.result()
    judge_pool.shutdown()
    if watcher:
        watcher.stop()
    log(f"\n全部完成，用时 {time.time() - t_start:.0f}s")

    if args.no_judge:
        return 0

    with open(os.path.join(run_dir, "score.txt"), "w", encoding="utf-8") as fh:
        proc = subprocess.run(
            [sys.executable, os.path.join(SELFTEST, "score.py"),
             "--results", os.path.join(run_dir, "results"),
             "--json", os.path.join(run_dir, "score.json")],
            capture_output=True, text=True)
        fh.write(proc.stdout + proc.stderr)
    print(proc.stdout, end="")

    summary = analyze.analyze(run_dir)
    if summary:
        print(analyze.render_md(summary))

    # Resource and speed metrics. Written before the experiment note so that
    # record.write_summary() can fold them into it.
    m = metrics.run_metrics(run_dir, args.jobs)
    if watcher:
        m["server"] = watcher.summary()
    with open(os.path.join(run_dir, "metrics.json"), "w", encoding="utf-8") as fh:
        json.dump(m, fh, ensure_ascii=False, indent=2)
    md = metrics.render_md(m)
    with open(os.path.join(run_dir, "metrics.md"), "w", encoding="utf-8") as fh:
        fh.write(md + "\n")
    print(md)

    # With both modes in one run, what the agent fixed and what it broke is the
    # number that decides model choice; see dev/failures/agent-repair.md.
    if "agent" in args.modes and "baseline" in args.modes:
        jd = metrics.joint_metrics(run_dir)
        with open(os.path.join(run_dir, "joint.json"), "w", encoding="utf-8") as fh:
            json.dump(jd, fh, ensure_ascii=False, indent=2)
        jmd = metrics.render_joint_md(jd)
        with open(os.path.join(run_dir, "joint.md"), "w", encoding="utf-8") as fh:
            fh.write(jmd + "\n")
        print(jmd)

    record.write_summary(run_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
