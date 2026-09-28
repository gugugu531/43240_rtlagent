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

Generated markdown goes to dev/notes/generated/ -- that directory holds only files a
script produces, so nobody should hand-edit them.
"""

from __future__ import annotations

import argparse
import io
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
            row["solve_max"] = base.get("solve_s", {}).get("max")
            row["tps_median"] = base.get("tps_percall", {}).get("median")
            row["llm_errors"] = base.get("llm_errors")
            row["truncated"] = base.get("truncated")
        if m.get("server", {}).get("available"):
            row["kv_peak"] = m["server"].get("kv_cache_usage_peak_perc")
        # Per-sample breakdown: which failure reasons, and which task types it
        # actually solves. That is what "baseline 的做题情况与错因" means.
        reasons: dict[str, int] = {}
        cats: dict[str, tuple] = {}
        csv_path = os.path.join(d, "samples.csv")
        if os.path.isfile(csv_path):
            import csv as _csv
            with open(csv_path, encoding="utf-8") as fh:
                for r in _csv.DictReader(fh):
                    if r.get("mode") != "baseline":
                        continue
                    key = r.get("reason") or "?"
                    reasons[key] = reasons.get(key, 0) + 1
                    c = r.get("category") or "?"
                    l3, n = cats.get(c, (0, 0))
                    cats[c] = (l3 + int(r.get("level") == "3"), n + 1)
        if reasons:
            row["reasons"] = reasons
            row["cat_pass"] = {c: l3 / n for c, (l3, n) in cats.items()}
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
        "python3 dev/eval/overview.py --out dev/notes/generated/2026-09-25-candidate-tables.md",
        "```",
        "",
        "四张表：**A 是全题集 baseline 的分数，B 是 quick 子集上的联合跑分，C 是错因分布，D 是各题型的通过率**。A 与 B 必须分开看——"
        "两者的 `S_b` 不可直接比较（quick 偏高 0.06–0.08）。`smoke` 与 `mock` 运行已被排除——"
        "8 道题的 smoke 分数能轻易排到第一，混进来会误导判断。",
        "",
        "**并发 1 的速度、显存峰值、KV 池大小不在运行产物里**，记在 "
        "[`2026-09-25-screening-results.md`](../2026-09-25-screening-results.md) 的两张表里"
        "（每个数字注明来自哪次运行）。权重 sha256 见 "
        "[`2026-09-25-model-fingerprints.md`](../2026-09-25-model-fingerprints.md)。"
        "选型建议见 [`../decisions/0002-model-choice.md`](../../decisions/0002-model-choice.md) 最前面一节。",
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

    # 表 C / 表 D 只放全题集 baseline，这样各行可比。
    with_bd = [r for r in full if r.get("reasons")]
    if with_bd:
        order = ["pass", "sim_mismatch", "syntax", "elab", "interface", "llm_error"]
        zh = {"pass": "通过 L3", "sim_mismatch": "仿真失配 L1", "syntax": "语法 L0",
              "elab": "详细描述 L0", "interface": "接口 L0", "llm_error": "请求失败 L0"}
        lines += ["", "### 表 C：错因分布（全题集 baseline，占该次运行题数的百分比）", "",
                  "原因定义见 [`../eval/README.md`](../../eval/README.md)「失败原因」。"
                  "「请求失败」是模型请求超时或出错，不是模型答错。"
                  "同一个模型名出现多行时用运行编号区分（例如 Qwen3-8B 那几行是不同服务配置）。", "",
                  "| 运行编号 | 模型 | " + " | ".join(zh[k] for k in order) + " | 其他 |",
                  "| --- | --- | " + " | ".join("---:" for _ in order) + " | ---: |"]
        for r in with_bd:
            total = sum(r["reasons"].values())
            cells = [f"{100 * r['reasons'].get(k, 0) / total:.1f}%" for k in order]
            other = total - sum(r["reasons"].get(k, 0) for k in order)
            lines.append(f"| `{short(r['run_id'])}` | {r['model']} | " + " | ".join(cells)
                         + f" | {100 * other / total:.1f}% |")

        cats = sorted({c for r in with_bd for c in r.get("cat_pass", {})})
        lines += ["", "### 表 D：按题型的 L3 通过率（全题集 baseline）", "",
                  "题型由 `dev/eval/categorize.py` 按题面关键词粗分，只用来看短板在哪一类。", "",
                  "| 运行编号 | 模型 | " + " | ".join(cats) + " |",
                  "| --- | --- | " + " | ".join("---:" for _ in cats) + " |"]
        for r in with_bd:
            cells = [f"{r['cat_pass'][c]:.2f}" if c in r.get("cat_pass", {})
                     else "—" for c in cats]
            lines.append(f"| `{short(r['run_id'])}` | {r['model']} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def short(run_id: str) -> str:
    """20260925-194130-screen-A1-… -> 194130-screen-A1-…"""
    return run_id[9:] if len(run_id) > 9 and run_id[8] == "-" else run_id



# ---------------------------------------------------------------- 主表（选型用）
#
# 与上面的「表 A–D」不同，主表按**模型**一行，把判断选型要看的指标并排放在一起。
# 数据来源分两类：
#   * 运行产物（dev/runs/<运行编号>/）：分数、等级分布、错因、耗时、tps、显存峰值、KV 使用率
#   * 手工登记（dev/notes/model-metrics-manual.json）：权重显存、KV 池 token 数、并发 1 的 tps
#     —— 这三项运行产物里没有，登记时要求带 source，没有实测就不写。

MANUAL_PATH = os.path.join(DEV_ROOT, "notes", "model-metrics-manual.json")
BASE_MODEL = "Qwen3-4B-BF16"      # 参照系：看谁能在可计算分上反超它


def load_manual() -> dict:
    return _read(MANUAL_PATH) or {}


def vram_peak_gib(run_dir: str):
    """从 vram_watch.sh 采的 CSV 里取显存峰值（GiB）。"""
    path = os.path.join(run_dir, "vram.log")
    if not os.path.isfile(path):
        return None
    peak = 0
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            parts = line.strip().split(",")
            if len(parts) >= 3:
                try:
                    peak = max(peak, int(parts[2]))
                except ValueError:
                    continue
    return peak / 2 ** 30 if peak else None


def threshold_sa(sb: float, base: float, m: float = 2.5):
    """要在可计算分上超过 base，S_a 至少要多少。"""
    lo, hi = sb, 1.0
    if computable(sb, hi, m) <= base:
        return None
    for _ in range(60):
        mid = (lo + hi) / 2
        if computable(sb, mid, m) > base:
            hi = mid
        else:
            lo = mid
    return hi


def master_rows(runs_dir: str) -> list[dict]:
    manual = load_manual()
    rows = collect(runs_dir)
    # 只保留候选：2026-09-25 起的筛选批次、全题集、题数完整
    keep = []
    for r in rows:
        rid = r["run_id"]
        if rid.startswith("20260924"):
            continue
        if r["taskset"] != "full" or r["partial"]:
            continue
        keep.append(r)

    # 参照系：4B BF16 的联合跑分
    base = None
    for r in rows:
        if r["model"] == BASE_MODEL and "agent" in r["set_score"]:
            base = (r.get("capability") or 0) + (r.get("gain_score") or 0)
            break

    # quick 基线与联合结果，按模型名索引
    quick, joint = {}, {}
    for r in rows:
        if r["taskset"] == "quick" and "baseline" in r["set_score"]:
            quick.setdefault(r["model"], r["set_score"]["baseline"])
        if "agent" in r["set_score"]:
            joint.setdefault(r["model"], r)

    out = []
    for r in keep:
        model = r["model"]
        lv = r["levels"]["baseline"]
        n = r["tasks"]["baseline"] or 155
        m = manual.get(model, {})
        j = joint.get(model)
        sb = r["set_score"]["baseline"]
        out.append({
            "model": model, "run_id": r["run_id"], "quant": model,
            "sb": sb, "levels": lv, "synth": lv.get("L3", 0) / n,
            "reasons": r.get("reasons", {}),
            "median": r.get("solve_median"), "p90": r.get("solve_p90"), "max": r.get("solve_max"),
            "tps": r.get("tps_median"), "errors": r.get("llm_errors"),
            "truncated": r.get("truncated"),
            "vram": vram_peak_gib(os.path.join(runs_dir, r["run_id"])),
            "kv_peak": r.get("kv_peak"),
            "quick": quick.get(model),
            "sa": (j or {}).get("set_score", {}).get("agent"),
            "cap": ((j or {}).get("capability") or 0) + ((j or {}).get("gain_score") or 0) if j else None,
            "need_sa": threshold_sa(sb, base) if base else None,
            "weights": m.get("weights_gib"), "kv_tokens": m.get("kv_tokens"),
            "probe": m.get("probe_tps"),
        })
    out.sort(key=lambda x: -x["sb"])
    return out


def _pct(v, total):
    return f"{100 * v / total:.1f}%" if v is not None and total else "—"


def render_master(rows: list[dict]) -> str:
    L = ["<!-- 本段由 dev/eval/overview.py 注入（--inject）；不要手改，改生成脚本 -->", ""]

    L += ["### 表 1：选型主表（每行一个已测模型，按 `S_b` 降序）", "",
          "「反超所需 `S_a`」= 要在可计算分上超过 4B 方案，该模型自己的 `S_a` 至少要达到多少；"
          "这一列越低越容易翻盘，与模型强弱无关。", "",
          "| 模型 | `S_b`（全题集） | 可综合率 | 反超所需 `S_a` | `S_b`（quick） | `S_a`（联合） | 可计算分/70 | 单题中位 | tps(并发4) | 显存峰值 | 运行编号 |",
          "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |"]
    for r in rows:
        f = lambda v, s="{:.3f}": (s.format(v) if isinstance(v, (int, float)) else "—")
        L.append("| `{m}` | **{sb:.4f}** | {sy:.3f} | {ns} | {q} | {sa} | {cap} | {md} s | {tp} | {vr} | `{rid}` |".format(
            m=r["model"], sb=r["sb"], sy=r["synth"],
            ns=(f"{r['need_sa']:.3f}" if r["need_sa"] else "—"),
            q=f(r["quick"]), sa=f(r["sa"]), cap=(f"{r['cap']:.1f}" if r["cap"] else "—"),
            md=(f"{r['median']:.2f}" if r["median"] is not None else "—"),
            tp=f(r["tps"], "{:.1f}"),
            vr=(f"{r['vram']:.2f} GiB" if r["vram"] else "—"),
            rid=short(r["run_id"])))

    L += ["", "### 表 2：失败结构（占 155 题的比例）", "",
          "等级分布与错因由 `samples.csv` 统计；「请求失败」是模型请求超时或出错，不是答错。", "",
          "| 模型 | L0 / L1 / L2 / L3 | 通过 L3 | 仿真失配 L1 | 语法 L0 | 详细描述 L0 | 接口 L0 | 请求失败 L0 | 截断 | 单题 p90 | 单题最长 |",
          "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for r in rows:
        lv, rs = r["levels"], r["reasons"]
        total = sum(rs.values()) or 155
        L.append("| `{m}` | {l0}/{l1}/{l2}/{l3} | {p} | {sm} | {sy} | {el} | {it} | {er} | {tr} | {p90} s | {mx} s |".format(
            m=r["model"], l0=lv.get("L0",0), l1=lv.get("L1",0), l2=lv.get("L2",0), l3=lv.get("L3",0),
            p=_pct(rs.get("pass", 0), total), sm=_pct(rs.get("sim_mismatch", 0), total),
            sy=_pct(rs.get("syntax", 0), total), el=_pct(rs.get("elab", 0), total),
            it=_pct(rs.get("interface", 0), total), er=_pct(rs.get("llm_error", 0), total),
            tr=(r["truncated"] if r["truncated"] is not None else "—"),
            p90=(f"{r['p90']:.1f}" if r["p90"] is not None else "—"),
            mx=(f"{r['max']:.1f}" if r.get("max") is not None else "—")))

    L += ["", "### 表 3：资源与单路速度", "",
          "「权重显存」「KV 池」「tps(并发1)」三项运行产物里没有，手工登记在 "
          "[`../notes/model-metrics-manual.json`](../notes/model-metrics-manual.json)（每项带来源）。", "",
          "| 模型 | 权重显存 | KV 池 | tps(并发1) | tps(并发4) | 显存峰值 | 服务端 KV 使用峰值 |",
          "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for r in rows:
        L.append("| `{m}` | {w} | {k} | {p} | {t} | {v} | {kp} |".format(
            m=r["model"],
            w=(f"{r['weights']:.2f} GiB" if r["weights"] else "—"),
            k=(f"{r['kv_tokens']:,} token" if r["kv_tokens"] else "—"),
            p=(f"{r['probe']:.1f}" if r["probe"] else "—"),
            t=(f"{r['tps']:.1f}" if r["tps"] is not None else "—"),
            v=(f"{r['vram']:.2f} GiB" if r["vram"] else "—"),
            kp=(f"{100 * r['kv_peak']:.1f}%" if r.get("kv_peak") else "—")))

    # 自动警告：请求失败多 = 分数不是能力分，门槛那一列会误导
    risky = [r for r in rows if (r["errors"] or 0) >= 15]
    if risky:
        L += ["", "> ⚠ **下面这些行的请求失败偏多**，`S_b` 里有一部分是超时造成的 L0，"
                  "「反超所需 `S_a`」那一列因此偏低。引用它们的数字前先看这一条：", ">"]
        for r in risky:
            L.append(f"> - `{r['model']}`：请求失败 **{r['errors']}** 次、单题耗时中位 "
                     f"{r['median']} 秒、tps {r['tps']}（运行 `{short(r['run_id'])}`）")
    return "\n".join(L) + "\n"


def inject(path: str, block: str) -> None:
    """把 block 替换进 path 里 `<!-- BEGIN:master-table -->` 与 `<!-- END:master-table -->` 之间。"""
    begin, end = "<!-- BEGIN:master-table -->", "<!-- END:master-table -->"
    text = io.open(path, encoding="utf-8").read() if os.path.exists(path) else ""
    if begin not in text or end not in text:
        raise SystemExit(f"✗ {path} 里找不到 {begin} / {end} 标记")
    head, rest = text.split(begin, 1)
    _, tail = rest.split(end, 1)
    new = f"{head}{begin}\n\n{block}\n{end}{tail}"
    with io.open(path, "w", encoding="utf-8") as fh:
        fh.write(new)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="汇总 dev/runs/ 下的所有跑分")
    ap.add_argument("--runs", default=os.path.join(DEV_ROOT, "runs"))
    ap.add_argument("--out", default="")
    ap.add_argument("--master-out", default="", help="把选型主表写到这个文件")
    ap.add_argument("--inject", default="", help="把选型主表注入到这份手写文档的标记块之间")
    args = ap.parse_args(argv)
    rows = collect(args.runs)
    if args.master_out or args.inject:
        master = render_master(master_rows(args.runs))
        if args.master_out:
            with open(args.master_out, "w", encoding="utf-8") as fh:
                fh.write(master)
            print(f"✓ 主表已写入 {args.master_out}")
        if args.inject:
            inject(args.inject, master)
            print(f"✓ 主表已注入 {args.inject}")
        return 0
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
