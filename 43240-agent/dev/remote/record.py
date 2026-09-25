"""Run bookkeeping for dev/runs/ and dev/experiments/.

    record.py meta    <run_dir> <kind> [args...]   write <run_dir>/meta.json
    record.py summary <run_dir>                    write dev/experiments/<run_id>.md

meta.json pins what produced a run (commit, dirty flag, model, LLM env, args),
so a score in experiments/ can always be traced back to the code behind it.
The experiment note is a skeleton: numbers are filled in, conclusions are not.
If the run has an analysis.md (dev/eval/analyze.py), it is included.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
AGENT_ROOT = os.path.dirname(os.path.dirname(HERE))
DEV_ROOT = os.path.join(AGENT_ROOT, "dev")

ENV_KEYS = ("LLM_BACKEND", "LLM_BASE_URL", "LLM_MODEL", "MODEL_NAME",
            "LLM_MAX_TOKENS", "LLM_TEMPERATURE", "AGENT_MAX_ROUNDS",
            "AGENT_DEADLINE_S", "REMOTE_HOST", "REMOTE_MODEL", "REMOTE_MAX_LEN")


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=AGENT_ROOT, capture_output=True,
                              text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def write_meta(run_dir: str, kind: str, args: list[str]) -> dict:
    # dev/ itself is excluded: notes changing must not mark the agent dirty.
    dirty = _git("status", "--porcelain", "--", ".", ":(exclude)dev")
    meta = {
        "run_id": os.path.basename(os.path.normpath(run_dir)),
        "kind": kind,
        "started": time.strftime("%Y-%m-%d %H:%M:%S"),
        "commit": _git("rev-parse", "--short", "HEAD"),
        "dirty": bool(dirty),
        "args": args,
        "env": {k: os.environ[k] for k in ENV_KEYS if os.environ.get(k)},
    }
    os.makedirs(run_dir, exist_ok=True)
    with open(os.path.join(run_dir, "meta.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)
    return meta


def write_summary(run_dir: str) -> str | None:
    with open(os.path.join(run_dir, "meta.json"), encoding="utf-8") as fh:
        meta = json.load(fh)
    try:
        with open(os.path.join(run_dir, "score.json"), encoding="utf-8") as fh:
            score = json.load(fh)
    except (OSError, ValueError):
        print(f"record.py: {run_dir}/score.json 不存在，不生成实验记录", file=sys.stderr)
        return None

    env = meta.get("env", {})
    lines = [
        f"# {meta['run_id']}",
        "",
        "| 项 | 值 |",
        "| --- | --- |",
        f"| 类型 | {meta['kind']} |",
        f"| 时间 | {meta['started']} |",
        f"| git commit | `{meta['commit']}`{'（有未提交改动）' if meta['dirty'] else ''} |",
        f"| 模型 | {env.get('LLM_MODEL', '?')} |",
        f"| 参数 | `{' '.join(meta['args']) or '（默认）'}` |",
        f"| 原始文件 | `dev/runs/{meta['run_id']}/` |",
        "",
        "## 结果",
        "",
        "| 模式 | 题数 | 题集得分 (pass@1) | pass@5 | 等级分布 | 环境失败 |",
        "| --- | ---: | ---: | ---: | --- | ---: |",
    ]
    for mode, s in score.get("modes", {}).items():
        lines.append(f"| {mode} | {s['scored_tasks']}/{s['tasks']} | {s['set_score']:.3f} "
                     f"| {s['pass@5']:.3f} | {s['level_counts']} | {s['tool_errors']} |")
    lines.append("")
    if "gain" in score:
        lines.append(f"增益：{score['gain']} 倍，增益得分 {score.get('gain_score')} / 40"
                     f"（满分线 {score.get('gain_full_mark')} 为占位值）")
    if "wallclock" in score:
        w = score["wallclock"]
        lines.append(f"请求耗时（客户端计时）：合计 {w['total_s']} s，单题最长 {w['max_s']} s，"
                     f"请求失败 {w['transport_errors']} 次")
    # Failure breakdown from dev/eval/analyze.py, when the run has one.
    try:
        with open(os.path.join(run_dir, "analysis.md"), encoding="utf-8") as fh:
            lines += ["", fh.read().rstrip()]
    except OSError:
        pass
    # Resource and speed metrics from dev/eval/metrics.py, when the run has them.
    try:
        with open(os.path.join(run_dir, "metrics.md"), encoding="utf-8") as fh:
            lines += ["", fh.read().rstrip()]
    except OSError:
        pass
    # Agent vs baseline comparison, for runs that have both modes.
    try:
        with open(os.path.join(run_dir, "joint.md"), encoding="utf-8") as fh:
            lines += ["", fh.read().rstrip()]
    except OSError:
        pass
    server = None
    try:
        with open(os.path.join(run_dir, "metrics.json"), encoding="utf-8") as fh:
            server = json.load(fh).get("server")
    except (OSError, ValueError):
        pass
    if server:
        if server.get("available"):
            lines += ["", "服务端 /metrics（跑分期间轮询）", "",
                      f"- KV Cache 使用率峰值 {server.get('kv_cache_usage_peak_perc')}、"
                      f"中位数 {server.get('kv_cache_usage_median_perc')}",
                      f"- 同时在跑的请求数峰值 {server.get('num_requests_running_max')}",
                      f"- 服务端计数的生成 token {server.get('generation_tokens_delta')}、"
                      f"输入 token {server.get('prompt_tokens_delta')}",
                      f"- 共采样 {server.get('samples')} 次"
                      + (f"，最后一次出错：{server['last_error']}"
                         if server.get("last_error") else "")]
        else:
            lines += ["", f"服务端 /metrics 不可用：{server.get('error')}"]
    lines += ["", "## 改动与假设", "", "TODO：这一轮相对上一轮改了什么、预期效果",
              "", "## 结论", "", "TODO：结果是否符合预期；失败原因分析写在 dev/failures/", ""]

    exp_dir = os.path.join(DEV_ROOT, "experiments")
    os.makedirs(exp_dir, exist_ok=True)
    path = os.path.join(exp_dir, f"{meta['run_id']}.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    print(f"✓ 实验记录       {os.path.relpath(path, AGENT_ROOT)}")
    return path


def main(argv: list[str]) -> int:
    if len(argv) >= 3 and argv[0] == "meta":
        write_meta(argv[1], argv[2], argv[3:])
        return 0
    if len(argv) == 2 and argv[0] == "summary":
        return 0 if write_summary(argv[1]) else 1
    print("\n".join(__doc__.strip().splitlines()[2:4]), file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
