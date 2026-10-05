#!/usr/bin/env python3
"""Compare two runs task by task: what got better, what got worse.

    compare.py <old_run> <new_run> [--mode agent] [--mode baseline=agent] [--md FILE]

A run is a directory under dev/runs/ or just its run id. Only tasks graded in
both runs count, and samples with an environment failure are left out, as in
selftest/score.py. The set score over the common tasks is printed for both
runs, so a run cut short still compares fairly.

Each task is 1/156 = 0.0064 of a 156-task set score (times the coefficient
change), and single-sample runs flip a few tasks by chance alone. Read small differences
with that in mind; rerun with --samples 3 or more before trusting them.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
RUNS = os.path.join(os.path.dirname(HERE), "runs")


def resolve(run: str) -> str:
    for cand in (run, os.path.join(RUNS, run)):
        if os.path.isdir(os.path.join(cand, "results")):
            return cand
    sys.exit(f"✗ 找不到运行 {run}（需要含 results/ 的目录，或 dev/runs/ 下的运行编号）")


def load(run_dir: str) -> dict[str, dict[str, list[tuple[int, float]]]]:
    """mode -> task -> [(level, coefficient)]"""
    out: dict = defaultdict(lambda: defaultdict(list))
    for path in glob.glob(os.path.join(run_dir, "results", "*.json")):
        m = re.fullmatch(r"(\w+)\.(.+)\.s\d+\.json", os.path.basename(path))
        if not m:
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                res = json.load(fh)
        except (OSError, ValueError):
            continue
        if res.get("tool_error"):
            continue
        out[m.group(1)][res.get("task_id", m.group(2))].append(
            (res.get("level", 0), res.get("coefficient", 0.0)))
    return out


def fmt_levels(samples: list[tuple[int, float]]) -> str:
    return ",".join(f"L{lv}" for lv, _ in samples)


def mean(samples: list[tuple[int, float]]) -> float:
    return sum(c for _, c in samples) / len(samples)


def compare(old_dir: str, new_dir: str, modes: list[str]) -> str:
    old, new = load(old_dir), load(new_dir)
    lines = [f"# 对比：{os.path.basename(os.path.normpath(old_dir))} → "
             f"{os.path.basename(os.path.normpath(new_dir))}", ""]
    pairs = [tuple(m.split("=", 1)) if "=" in m else (m, m) for m in modes] \
        or [(m, m) for m in sorted(set(old) & set(new))]
    if not pairs:
        lines.append(f"两次运行没有共同的模式（旧：{sorted(old)}，新：{sorted(new)}），"
                     "可以用 --mode 旧模式=新模式 指定。")
    for mo, mn in pairs:
        title = mo if mo == mn else f"{mo} → {mn}"
        if mo not in old or mn not in new:
            lines += [f"## {title}", "", "旧运行中没有这个模式，或新运行中没有。", ""]
            continue
        common = sorted(set(old[mo]) & set(new[mn]))
        if not common:
            continue
        o = {t: mean(old[mo][t]) for t in common}
        n = {t: mean(new[mn][t]) for t in common}
        so, sn = sum(o.values()) / len(common), sum(n.values()) / len(common)
        up = sorted((t for t in common if n[t] > o[t] + 1e-9), key=lambda t: o[t] - n[t])
        down = sorted((t for t in common if n[t] < o[t] - 1e-9), key=lambda t: n[t] - o[t])
        only_old = sorted(set(old[mo]) - set(new[mn]))
        only_new = sorted(set(new[mn]) - set(old[mo]))

        lines += [f"## {title}", "",
                  f"共同题目 {len(common)} 道。题集得分 {so:.3f} → {sn:.3f}"
                  f"（{sn - so:+.3f}）；变好 {len(up)} 道，变差 {len(down)} 道，"
                  f"不变 {len(common) - len(up) - len(down)} 道。", ""]
        if only_old or only_new:
            lines += [f"只在旧运行中有 {len(only_old)} 道，只在新运行中有 {len(only_new)} 道，"
                      "不参与比较。", ""]
        for heading, items in (("变好", up), ("变差", down)):
            if not items:
                continue
            lines += [f"### {heading}", "", "| 题目 | 旧 | 新 |", "| --- | --- | --- |"]
            for t in items:
                lines.append(f"| {t} | {fmt_levels(old[mo][t])} | {fmt_levels(new[mn][t])} |")
            lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="逐题对比两次运行")
    ap.add_argument("old")
    ap.add_argument("new")
    ap.add_argument("--mode", action="append", default=[],
                    help="只比较这个模式，可重复；写成 旧=新 可比较不同模式，"
                         "如 baseline=agent。默认比较两次运行共有的全部模式")
    ap.add_argument("--md", default="", help="同时写入这个 markdown 文件")
    args = ap.parse_args()
    text = compare(resolve(args.old), resolve(args.new), args.mode)
    print(text)
    if args.md:
        with open(args.md, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
