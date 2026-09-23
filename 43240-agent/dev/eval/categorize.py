#!/usr/bin/env python3
"""Rough task categories, so a run can say which kind of problem fails.

    categorize.py [--tasks DIR]     rewrite tasksets/categories.tsv from the prompts

Categories come from keywords in prompt.txt (state machine, Karnaugh map,
waveform table, clk port ...). The result is written to tasksets/categories.tsv
and committed, so it can be corrected by hand; analyze.py reads that table and
falls back on the task name for tasks it does not list. Rerunning this script
overwrites hand corrections -- apply them again, or edit the rules below.
"""

from __future__ import annotations

import argparse
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
TABLE = os.path.join(HERE, "tasksets", "categories.tsv")

CATEGORY_NOTE = "按题面关键词粗分（tasksets/categories.tsv），只用于看哪类题失败多"

CATEGORIES = {
    "fsm":              "状态机",
    "waveform":         "根据仿真波形推逻辑",
    "kmap_truthtable":  "卡诺图、真值表",
    "counter_timer":    "计数器、定时器",
    "shift_lfsr_ca":    "移位寄存器、LFSR、元胞自动机",
    "sequential_other": "其他时序电路（触发器、边沿检测等）",
    "combinational":    "组合逻辑",
    "bugfix":           "改错题",
    "other":            "未分类",
}


def from_prompt(task_id: str, prompt: str) -> str:
    name, low = task_id.lower(), prompt.lower()
    if "bugs" in name:
        return "bugfix"
    if re.search(r"fsm|lemmings", name) or re.search(
            r"state machine|\bfsm\b|state diagram|state transition|next[- ]state|moore|mealy"
            r"|detect the sequence|sequence detect", low):
        return "fsm"
    if "waveform" in low or re.search(r"^\s*\d+\s*ns\b", prompt, re.M):
        return "waveform"
    if re.search(r"karnaugh|k-map|kmap|truth table", low):
        return "kmap_truthtable"
    if re.search(r"^\s*-\s*input\s+clk\b", prompt, re.M):
        if re.search(r"shift|lfsr|rotat|rule ?\d+|game of life|conway|two-dimensional grid",
                     low + name):
            return "shift_lfsr_ca"
        if re.search(r"count|timer", name) or re.search(r"\bcounter\b|timer", low):
            return "counter_timer"
        return "sequential_other"
    return "combinational"


def from_name(task_id: str) -> str:
    name = task_id.lower()
    for cat, pattern in (("bugfix", r"bugs"), ("fsm", r"fsm|lemmings"),
                         ("waveform", r"circuit\d+"), ("kmap_truthtable", r"kmap|truthtable"),
                         ("counter_timer", r"count|timer"),
                         ("shift_lfsr_ca", r"shift|lfsr|rotate|rule\d+|conwaylife")):
        if re.search(pattern, name):
            return cat
    return "other"


_table: dict[str, str] | None = None


def categorize(task_id: str) -> str:
    global _table
    if _table is None:
        _table = {}
        try:
            with open(TABLE, encoding="utf-8") as fh:
                for line in fh:
                    parts = line.split("#", 1)[0].split()
                    if len(parts) >= 2:
                        _table[parts[0]] = parts[1]
        except OSError:
            pass
    return _table.get(task_id) or from_name(task_id)


def main() -> int:
    ap = argparse.ArgumentParser(description="根据题面重新生成 tasksets/categories.tsv")
    ap.add_argument("--tasks", default=os.path.join(REPO_ROOT, "tasks"))
    args = ap.parse_args()
    rows = []
    for t in sorted(os.listdir(args.tasks)):
        path = os.path.join(args.tasks, t, "prompt.txt")
        if os.path.isfile(path):
            with open(path, encoding="utf-8", errors="replace") as fh:
                rows.append((t, from_prompt(t, fh.read())))
    with open(TABLE, "w", encoding="utf-8") as fh:
        fh.write("# 题目分类，由 categorize.py 按题面关键词生成，可以手工修正。\n")
        fh.write("# " + "；".join(f"{k} = {v}" for k, v in CATEGORIES.items()) + "\n")
        for t, c in rows:
            fh.write(f"{t}\t{c}\n")
    print(f"✓ {len(rows)} 道题 -> {os.path.relpath(TABLE)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
