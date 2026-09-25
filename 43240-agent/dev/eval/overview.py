#!/usr/bin/env python3
"""Consolidated view of every run under dev/runs/, for model selection.

    overview.py [--runs DIR] [--out FILE] [--full-only]

Prints (and optionally writes) markdown tables built **straight from the run
artefacts** — no number is retyped by hand:

  * 全题集 baseline 筛选: every run that only ran `baseline` on the full task set
  * 联合跑分: every run that ran `agent,baseline` (currently only on `quick`)

The two are kept apart on purpose: a `quick` score runs 0.06-0.08 higher than the
same model on the full set (see dev/eval/README.md), so mixing them would be
wrong.  A model that appears in both tables therefore shows two different baselines.

Resource numbers that are not in the run artefacts (concurrency-1 probe speed,
peak VRAM, KV pool size) are deliberately left out — they live in
dev/notes/2026-09-25-screening-results.md with their sources.
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEV_ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import metrics  # noqa: E402


def _read(path: str):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def computable(sb: float, sa: float, m: float = 2.5) -> float:
    gain = sa / sb
    return 30 * sa + 40 * min(1.0, math.log(gain) / math.log(m))


def taskset_of(args: list) -> str:
    """Which task set a run used: full / quick / smoke / custom list.

    Getting this wrong is dangerous: a smoke run (8 tasks) can post a much
    higher score than a 155-task run and would sit at the top of the table.
    """
    if "--taskset" in args:
        i = args.index("--taskset")
        if i + 1 < len(args):
            return args[i + 1]
        return "?"
    if "--limit" in args:
        return "limit"
    return "full"


FULL_TASKS = {"full": 155, "quick": 34}


def collect(runs_dir: str, include_smoke: bool = False) -> list[dict]:
    out = []
    for d in sorted(glob.glob(os.path.join(runs_dir, "*"))):
        meta = _read(os.path.join(d, "meta.json")) or {}
        score = _read(os.path.join(d, "score.json"))
        if not score or not score.get("modes"):
            continue
        args = meta.get("args", [])
        modes = sorted(score["modes"])
        taskset = taskset_of(args)
        if taskset not in ("full", "quick") and not include_smoke:
            continue
        model = (meta.get("env") or {}).get("LLM_MODEL", "?")
        if model in ("?", ""):
            continue
        if modes == ["reference"]:
            continue
        m = _read(os.path.join(d, "metrics.json")) or {}
        expected = FULL_TASKS.get(taskset)
        n_tasks = max(score["modes"][k]["tasks"] for k in score["modes"])
        row = {
            "run_id": os.path.basename(d),
            "model": model,
            "modes": modes,
            "taskset": taskset,
            "partial": bool(expected and n_tasks < expected),
            "set_score": {k: v["set_score"] for k, v in score["modes"].items()},
            "levels": {k: v["level_counts"] for k, v in score["modes"].items()},
            "tasks": {k: v["tasks"] for k, v in score["modes"].items()},
            "gain": score.get("gain"),
            "capability": score.get("capability_score"),
            "gain_score": score.get("gain_score"),
        }
        base = m.get("modes", {}).get("baseline") or m.get("modes", {}).get("agent") or {}
        if base:
            row["solve_median"] = base.get("solve_s", {}).get("median")
            row["solve_p90"] = base.get("solve_s", {}).get("p90")
            row["tps_median"] = base.get("tps_percall", {}).get("median")
            row["llm_errors"] = base.get("llm_errors")
            row["truncated"] = base.get("truncated")
        if m.get("server", {}).get("available"):
            row["kv_peak"] = m["server"].get("kv_cache_usage_peak_perc")
        if "agent" in modes and "baseline" in modes:
            j = _read(os.path.join(d, "joint.json")) or metrics.joint_metrics(d)
            if j.get("available"):
                row["broke"] = j["broke_correct"]["count"]
                row["recovered_l0"] = j["recovered_l0"]["count"]
                row["to_l3_ratio"] = j["recovered_l0"]["to_l3_ratio"]
                row["fixed_l1"] = j["fixed_l1"]["count"]
                row["better"] = j["better"]
                row["worse"] = j["worse"]
        out.append(row)
    return out


def render(rows: list[dict]) -> str:
    full = [r for r in rows if r["modes"] == ["baseline"] and r["taskset"] == "full"]
    full.sort(key=lambda r: -r["set_score"]["baseline"])
    joint = [r for r in rows if "agent" in r["modes"] and "baseline" in r["modes"]]
    joint.sort(key=lambda r: -(r.get("capability", 0) + r.get("gain_score", 0)))
    lines = [
        "# 候选对照表（自动生成）",
        "",
        "本文件由 `dev/eval/overview.py` 从 `dev/runs/` 下的运行产物直接生成，**不要手改**。"
        "补跑新实验后重跑脚本即可更新：",
        "",
        "```bash",
        "python3 dev/eval/overview.py --out dev/notes/2026-09-25-candidate-tables.md",
        "```",
        "",
        "两张表必须分开看：**表 A 是全题集 baseline，表 B 是 quick 子集上的联合跑分**，"
        "两者的 `S_b` 不可直接比较（quick 偏高 0.06–0.08）。`smoke` 与 `mock` 运行已被排除——"
        "8 道题的 smoke 分数能轻易排到第一，混进来会误导判断。",
        "",
        "**并发 1 的速度、显存峰值、KV 池大小不在运行产物里**，记在 "
        "[`2026-09-25-screening-results.md`](2026-09-25-screening-results.md) 的两张表里"
        "（每个数字注明来自哪次运行）。权重 sha256 见 "
        "[`2026-09-25-model-fingerprints.md`](2026-09-25-model-fingerprints.md)。"
        "选型建议见 [`../decisions/0002-model-choice.md`](../decisions/0002-model-choice.md) 最前面一节。",
        "",
    ]

    lines += ["### 表 A：全题集 baseline 筛选（只跑 baseline，155 题，按 `S_b` 降序）", "",
              "| 运行编号 | 模型 | `S_b` | 等级分布 L0/L1/L2/L3 | 单题耗时 中位/p90 | tps(并发4) | 请求失败 | 截断 |",
              "| --- | --- | ---: | --- | --- | ---: | ---: | ---: |"]
    for r in full:
        lv = r["levels"]["baseline"]
        flag = " ⚠部分" if r["partial"] else ""
        lines.append(
            f"| `{short(r['run_id'])}` | {r['model']}{flag} | **{r['set_score']['baseline']:.3f}** | "
            f"{lv.get('L0',0)}/{lv.get('L1',0)}/{lv.get('L2',0)}/{lv.get('L3',0)} | "
            f"{r.get('solve_median','—')} / {r.get('solve_p90','—')} s | "
            f"{r.get('tps_median','—')} | {r.get('llm_errors','—')} | {r.get('truncated','—')} |")

    lines += ["", "### 表 B：联合跑分（`agent,baseline` 同一次运行，quick 34 题，按可计算分降序）", "",
              "表里的 `S_b` 与表 A 的**不可直接比较**（quick 子集偏高 0.06–0.08）。", "",
              "| 运行编号 | 模型 | `S_b`(quick) | `S_a` | 增益 | 可计算分/70 | 变好/变差 | 改坏 | 修好 L0→L3 | 修好 L1 |",
              "| --- | --- | ---: | ---: | ---: | ---: | --- | ---: | --- | ---: |"]
    for r in joint:
        if "agent" not in r["set_score"]:
            continue
        cap = (r.get("capability") or 0) + (r.get("gain_score") or 0)
        rl = r.get("recovered_l0", "—")
        ratio = f"{rl} 中 {r['to_l3_ratio']:.0%}" if r.get("to_l3_ratio") is not None else "—"
        lines.append(
            f"| `{short(r['run_id'])}` | {r['model']} | {r['set_score']['baseline']:.3f} | "
            f"**{r['set_score']['agent']:.3f}** | {r.get('gain', 0):.3f} | **{cap:.1f}** | "
            f"{r.get('better','—')} / {r.get('worse','—')} | {r.get('broke','—')} | {ratio} | "
            f"{r.get('fixed_l1','—')} |")
    return "\n".join(lines) + "\n"


def short(run_id: str) -> str:
    """20260925-194130-screen-A1-… -> 194130-screen-A1-…"""
    return run_id[9:] if len(run_id) > 9 and run_id[8] == "-" else run_id


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="汇总 dev/runs/ 下的所有跑分")
    ap.add_argument("--runs", default=os.path.join(DEV_ROOT, "runs"))
    ap.add_argument("--out", default="")
    args = ap.parse_args(argv)
    rows = collect(args.runs)
    md = render(rows)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(md)
        print(f"✓ 已写入 {args.out}（{len(rows)} 次运行）")
    else:
        print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
