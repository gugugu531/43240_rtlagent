#!/usr/bin/env python3
"""Per-sample analysis of one run: why each sample stopped where it did.

    analyze.py <run_dir>

Reads the layout written by run_eval.py (and, with less detail, by
selftest/run_selftest.sh and dev/remote/submit_client.py):

    <run_dir>/<mode>/<task>/s<k>/solution.v, trace.jsonl
                                 solve.json      solve wall clock (run_eval.py)
                                 response.json   request wall clock (submit_client.py)
                                 verdict.json    raw veval-judge verdict (run_eval.py)
                                 judge.log       full tool log (run_eval.py)
    <run_dir>/results/<mode>.<task>.s<k>.json    judge.py result

Writes <run_dir>/analysis.json, samples.csv and analysis.md. The markdown is
appended to the experiment note by dev/remote/record.py.

score.py answers "how much"; this answers "where did the rest go": a failure
reason per sample, a rough task category (categorize.py), trace statistics
(model calls, tokens, truncation) and the Vivado error ids behind L0.
"""

from __future__ import annotations

import csv
import glob
import json
import os
import re
import statistics
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from categorize import CATEGORIES, CATEGORY_NOTE, categorize  # noqa: E402

COEFFICIENT = {0: 0.0, 1: 0.2, 2: 0.7, 3: 1.0}

# --------------------------------------------------------- failure reasons

# One reason per sample. The level says how far it got; the reason says why it
# did not get further. Order of the table is the order printed.
REASONS = {
    "pass":           "L3 通过",
    "synth_fail":     "L2：综合失败",
    "synth_timeout":  "L2：综合超时（按 L2 计分）",
    "sim_mismatch":   "L1：仿真结果与参考实现不一致",
    "sim_timeout":    "L1：仿真超时",
    "sim_no_samples": "L1：仿真没有产生比对结果",
    "interface":      "L0：模块名或端口与测试台不符",
    "elab":           "L0：详细描述（xelab）失败，非接口问题",
    "syntax":         "L0：语法分析（xvlog）失败",
    "truncated":      "L0：模型输出被截断（finish_reason=length）",
    "empty_reply":    "L0：模型回复内容为空",
    "llm_error":      "L0：模型请求失败",
    "solve_timeout":  "L0：求解超时被终止",
    "deadline":       "L0：agent 用完时间预算，没有产出代码",
    "agent_error":    "L0：agent 异常",
    "transport":      "L0：投题接口请求失败",
    "no_code":        "L0：没有提取到代码",
    "env":            "环境失败（不计分）",
}

INTERFACE_ERR = re.compile(
    r"VRFC 10-3180|VRFC 10-2063|cannot find port|Module <?\w+>? not found", re.I)
ERROR_ID = re.compile(r"ERROR:\s*\[([A-Za-z]+ [\d-]+)\]")


def _read_json(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _read_text(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def read_trace(path: str) -> list[dict]:
    out = []
    for line in _read_text(path).splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def trace_stats(events: list[dict]) -> dict:
    llm = [e for e in events if e.get("tool") == "llm"]
    tools = Counter(e.get("tool") for e in events
                    if e.get("tool") not in ("llm", "agent", "baseline_meta",
                                             "env", "skills", "budget", None))
    finishes = [e.get("finish") for e in llm if e.get("finish")]
    return {
        "llm_calls": len(llm),
        "llm_errors": sum(1 for e in llm if e.get("error") or e.get("rc") == 1),
        "tokens_in": sum(int(e.get("tokens_in") or 0) for e in llm),
        "tokens_out": sum(int(e.get("tokens_out") or 0) for e in llm),
        "llm_s": round(sum(float(e.get("sec") or e.get("elapsed_s") or 0) for e in llm), 2),
        "truncated": sum(1 for f in finishes if f == "length"),
        "empty_reply": sum(1 for e in llm if e.get("empty_content")),
        "rounds": max([int(e.get("round") or 0) for e in events] or [0]),
        "tool_calls": dict(tools),
        "agent_error": any(e.get("tool") == "agent" and e.get("event") == "error"
                           for e in events),
        "deadline_stop": any(e.get("tool") == "budget" and e.get("event") == "stop"
                             for e in events),
    }


def classify(res: dict, solution: str, ts: dict, verdict: dict | None,
             log: str, solve: dict | None) -> str:
    if res.get("tool_error"):
        return "env"
    level = res.get("level", 0)
    if level == 3:
        return "pass"
    if level == 2:
        return "synth_timeout" if (verdict or {}).get("synth_timeout") else "synth_fail"
    if level == 1:
        if res.get("sim_timeout"):
            return "sim_timeout"
        if not res.get("samples"):
            return "sim_no_samples"
        return "sim_mismatch"

    # L0 with no code: find out why from the trace.
    if not solution.strip():
        if solve and solve.get("transport_error"):
            return "transport"
        if solve and solve.get("timed_out"):
            return "solve_timeout"
        if ts["truncated"]:
            return "truncated"
        if ts["llm_errors"]:
            return "llm_error"
        if ts["empty_reply"]:
            return "empty_reply"
        if ts["agent_error"]:
            return "agent_error"
        if ts["deadline_stop"]:
            return "deadline"
        return "no_code"

    # L0 with code: which Vivado stage refused it.
    stages = (verdict or {}).get("stages", {})
    if stages:
        if stages.get("xvlog_dut", {}).get("rc", 0) != 0:
            return "syntax"
        return "interface" if INTERFACE_ERR.search(log) else "elab"
    # No verdict.json (selftest / submit_client runs): fall back on the log.
    if INTERFACE_ERR.search(log):
        return "interface"
    return "elab" if "xelab" in log else "syntax"


# ------------------------------------------------------------------ collect

def collect(run_dir: str) -> list[dict]:
    rows = []
    for path in sorted(glob.glob(os.path.join(run_dir, "results", "*.json"))):
        name = os.path.basename(path)
        m = re.fullmatch(r"(\w+)\.(.+)\.s(\d+)\.json", name)
        res = _read_json(path)
        if not m or res is None:
            continue
        mode, k = m.group(1), int(m.group(3))
        tid = res.get("task_id", m.group(2))
        sdir = os.path.join(run_dir, mode, tid, f"s{k}")

        solution = _read_text(os.path.join(sdir, "solution.v"))
        ts = trace_stats(read_trace(os.path.join(sdir, "trace.jsonl")))
        verdict = _read_json(os.path.join(sdir, "verdict.json"))
        log = _read_text(os.path.join(sdir, "judge.log")) or \
            _read_text(os.path.join(sdir, f"{tid}.judge.log")) or \
            _read_text(os.path.join(run_dir, "logs", f"{tid}.judge.log"))
        solve = _read_json(os.path.join(sdir, "solve.json")) or \
            _read_json(os.path.join(sdir, "response.json"))

        reason = classify(res, solution, ts, verdict, log, solve)
        wall = None
        if solve:
            wall = solve.get("wall_s")
        rows.append({
            "mode": mode,
            "task_id": tid,
            "sample": k,
            "category": categorize(tid),
            "level": None if res.get("tool_error") else res.get("level", 0),
            "coefficient": None if res.get("tool_error") else res.get("coefficient", 0.0),
            "reason": reason,
            "mismatches": res.get("mismatches"),
            "sim_samples": res.get("samples"),
            "error_ids": sorted(set(ERROR_ID.findall(log))) if reason in (
                "syntax", "elab", "interface", "synth_fail") else [],
            "solve_s": wall,
            "judge_s": res.get("elapsed_s"),
            "solution_bytes": len(solution),
            **{k2: v for k2, v in ts.items() if k2 not in ("tool_calls",)},
            "tool_calls": ts["tool_calls"],
        })
    return rows


# ---------------------------------------------------------------- summarize

def _pct(values: list[float], q: float) -> float:
    s = sorted(values)
    return s[min(len(s) - 1, int(round(q * (len(s) - 1))))]


def summarize(rows: list[dict]) -> dict:
    by_mode: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_mode[r["mode"]].append(r)

    out: dict = {"modes": {}, "category_note": CATEGORY_NOTE}
    for mode, rs in sorted(by_mode.items()):
        scored = [r for r in rs if r["level"] is not None]
        reasons = Counter(r["reason"] for r in rs)
        examples = defaultdict(list)
        for r in rs:
            if len(examples[r["reason"]]) < 5 and r["task_id"] not in examples[r["reason"]]:
                examples[r["reason"]].append(r["task_id"])

        cats: dict[str, dict] = {}
        per_task: dict[str, list[float]] = defaultdict(list)
        for r in scored:
            per_task[r["task_id"]].append(r["coefficient"])
        cat_tasks: dict[str, list[float]] = defaultdict(list)
        cat_reasons: dict[str, Counter] = defaultdict(Counter)
        for tid, coeffs in per_task.items():
            cat_tasks[categorize(tid)].append(sum(coeffs) / len(coeffs))
        for r in scored:
            cat_reasons[r["category"]][r["reason"]] += 1
        for cat, vals in sorted(cat_tasks.items()):
            cats[cat] = {"tasks": len(vals), "pass@1": round(sum(vals) / len(vals), 4),
                         "reasons": dict(cat_reasons[cat].most_common())}

        err_ids = Counter(e for r in rs for e in r["error_ids"])
        solve = [r["solve_s"] for r in rs if r["solve_s"] is not None]
        timing = {}
        if solve:
            timing = {"total_s": round(sum(solve), 1), "mean_s": round(statistics.mean(solve), 1),
                      "median_s": round(statistics.median(solve), 1),
                      "p90_s": round(_pct(solve, 0.9), 1), "max_s": round(max(solve), 1)}
        n = len(rs) or 1
        out["modes"][mode] = {
            "samples": len(rs),
            "scored_samples": len(scored),
            "reasons": dict(reasons.most_common()),
            "reason_examples": dict(examples),
            "categories": cats,
            "error_ids": dict(err_ids.most_common(15)),
            "solve_time": timing,
            "llm": {
                "calls_mean": round(sum(r["llm_calls"] for r in rs) / n, 2),
                "tokens_in_mean": round(sum(r["tokens_in"] for r in rs) / n),
                "tokens_out_mean": round(sum(r["tokens_out"] for r in rs) / n),
                "tokens_out_max": max([r["tokens_out"] for r in rs] or [0]),
                "truncated_samples": sum(1 for r in rs if r["truncated"]),
                "error_samples": sum(1 for r in rs if r["llm_errors"]),
            },
        }

    # agent vs baseline, task by task, within this run.
    if "agent" in by_mode and "baseline" in by_mode:
        def mean_by_task(rs):
            d = defaultdict(list)
            for r in rs:
                if r["coefficient"] is not None:
                    d[r["task_id"]].append(r["coefficient"])
            return {t: sum(v) / len(v) for t, v in d.items()}
        a, b = mean_by_task(by_mode["agent"]), mean_by_task(by_mode["baseline"])
        common = sorted(set(a) & set(b))
        better = [t for t in common if a[t] > b[t] + 1e-9]
        worse = [t for t in common if a[t] < b[t] - 1e-9]
        out["agent_vs_baseline"] = {
            "tasks": len(common), "better": len(better), "worse": len(worse),
            "same": len(common) - len(better) - len(worse),
            "better_tasks": better, "worse_tasks": worse,
        }
    return out


# ------------------------------------------------------------------- render

def render_md(summary: dict) -> str:
    lines = ["## 失败原因分析（analyze.py 自动生成）", ""]
    for mode, s in summary["modes"].items():
        lines += [f"### {mode}", "",
                  f"样本 {s['samples']} 个，其中计分 {s['scored_samples']} 个。", "",
                  "| 原因 | 样本数 | 例子 |", "| --- | ---: | --- |"]
        for reason, cnt in s["reasons"].items():
            ex = ", ".join(s["reason_examples"].get(reason, []))
            lines.append(f"| {REASONS.get(reason, reason)} | {cnt} | {ex} |")
        lines += ["", f"按题型（{summary['category_note']}）：", "",
                  "| 题型 | 题数 | pass@1 | 主要原因 |", "| --- | ---: | ---: | --- |"]
        for cat, c in sorted(s["categories"].items(), key=lambda kv: kv[1]["pass@1"]):
            top = ", ".join(f"{k} {v}" for k, v in list(c["reasons"].items())[:3])
            lines.append(f"| {CATEGORIES.get(cat, cat)} | {c['tasks']} | {c['pass@1']:.3f} | {top} |")
        llm = s["llm"]
        lines += ["", f"模型调用：平均每个样本 {llm['calls_mean']} 次，输入 {llm['tokens_in_mean']} "
                  f"token，输出 {llm['tokens_out_mean']} token（最多 {llm['tokens_out_max']}）；"
                  f"被截断的样本 {llm['truncated_samples']} 个，请求失败的样本 {llm['error_samples']} 个。"]
        if s["solve_time"]:
            t = s["solve_time"]
            lines.append(f"求解耗时：合计 {t['total_s']} s，平均 {t['mean_s']} s，中位数 "
                         f"{t['median_s']} s，90% 分位 {t['p90_s']} s，最长 {t['max_s']} s。"
                         "并行运行时各样本互相影响，只作相对比较。")
        if s["error_ids"]:
            lines.append("Vivado 报错编号（L0 和综合失败的样本）：" + ", ".join(
                f"`{k}` × {v}" for k, v in s["error_ids"].items()))
        lines.append("")
    avb = summary.get("agent_vs_baseline")
    if avb:
        lines += ["### agent 与 baseline 逐题对比", "",
                  f"共同题目 {avb['tasks']} 道：agent 更好 {avb['better']} 道，更差 "
                  f"{avb['worse']} 道，相同 {avb['same']} 道。"]
        if avb["worse_tasks"]:
            lines.append("agent 更差的题：" + ", ".join(avb["worse_tasks"][:20]))
        lines.append("")
    return "\n".join(lines)


def write_csv(rows: list[dict], path: str) -> None:
    cols = ["mode", "task_id", "sample", "category", "level", "coefficient", "reason",
            "mismatches", "sim_samples", "solve_s", "judge_s", "llm_calls", "llm_errors",
            "tokens_in", "tokens_out", "llm_s", "truncated", "rounds", "solution_bytes",
            "error_ids"]
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({**r, "error_ids": " ".join(r["error_ids"])})


def analyze(run_dir: str) -> dict | None:
    rows = collect(run_dir)
    if not rows:
        print(f"analyze.py: {run_dir}/results 下没有判定结果", file=sys.stderr)
        return None
    summary = summarize(rows)
    with open(os.path.join(run_dir, "analysis.json"), "w", encoding="utf-8") as fh:
        json.dump({"summary": summary, "samples": rows}, fh, ensure_ascii=False, indent=2)
    write_csv(rows, os.path.join(run_dir, "samples.csv"))
    md = render_md(summary)
    with open(os.path.join(run_dir, "analysis.md"), "w", encoding="utf-8") as fh:
        fh.write(md)
    return summary


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__.strip().splitlines()[2], file=sys.stderr)
        return 2
    summary = analyze(argv[0])
    if summary is None:
        return 1
    print(render_md(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
