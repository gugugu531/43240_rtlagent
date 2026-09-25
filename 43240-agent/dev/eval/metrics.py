#!/usr/bin/env python3
"""Run metrics: VRAM, KV cache, tokens per second, per-task wall clock.

    metrics.py run    <run_dir>                 summarise one finished run
    metrics.py joint  <run_dir>                 compare two modes of one run
                                                (what the agent fixed and broke)
    metrics.py probe  <base_url> [--model M]    single-stream speed probe (concurrency 1)
    metrics.py scrape <base_url>                read the server's /metrics (KV cache use)
    metrics.py kv     <config.json|HF repo id>  KV cache size worked out from config.json
    metrics.py vram   <rocm-smi csv file>       peak and steady VRAM from a sample log

analyze.py answers "where did each sample stop and why"; this answers "how much
memory did it take and how fast was it", which is what model selection needs:
see dev/notes/2026-09-25-model-screening-plan.md sections 5.3 to 5.5.

Two caveats this script keeps repeating, because they are easy to get wrong:

  * A rate measured while several samples run in parallel is NOT the single
    stream rate an agent sees. Every number it prints carries the concurrency it
    was measured at; use `probe` for the concurrency-1 figure.
  * Theoretical KV sizes assume the server understands the model's layer types
    (sliding window, linear attention). If it does not, the real pool is many
    times bigger. Compare `kv` against the server's own numbers, never alone.

Writes <run_dir>/metrics.json and <run_dir>/metrics.md for `run`.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analyze  # noqa: E402

BYTES_PER_GIB = 1024 ** 3

# Metrics we look for in the server's Prometheus output. Older vLLM builds call
# the KV cache counter gpu_cache_usage_perc; newer ones kv_cache_usage_perc.
PROM_KEYS = (
    "vllm:kv_cache_usage_perc",
    "vllm:gpu_cache_usage_perc",
    "vllm:num_requests_running",
    "vllm:num_requests_waiting",
    "vllm:num_requests_swapped",
    "vllm:prompt_tokens_total",
    "vllm:generation_tokens_total",
    "vllm:request_success_total",
)


def _fmt(v, digits: int = 2) -> str:
    return "—" if v is None else f"{v:.{digits}f}"


def _stats(values: list[float]) -> dict:
    vals = [v for v in values if v is not None]
    if not vals:
        return {}
    return {
        "n": len(vals),
        "mean": round(statistics.fmean(vals), 3),
        "median": round(statistics.median(vals), 3),
        "p90": round(analyze._pct(vals, 0.90), 3),
        "max": round(max(vals), 3),
    }


# ------------------------------------------------------------------ one run

def _call_rates(run_dir: str, mode: str, tid: str, k: int) -> list[dict]:
    """Per model call: output tokens, seconds, tokens/s.

    baseline.py writes `sec`, agent/main.py writes `elapsed_s`; both are the
    wall clock of one HTTP request, so the ratio is a per-request rate.
    """
    sdir = os.path.join(run_dir, mode, tid, f"s{k}")
    out = []
    for e in analyze.read_trace(os.path.join(sdir, "trace.jsonl")):
        if e.get("tool") != "llm":
            continue
        sec = float(e.get("sec") or e.get("elapsed_s") or 0)
        tokens = int(e.get("tokens_out") or 0)
        if sec > 0 and tokens > 0:
            out.append({"tokens_out": tokens, "sec": round(sec, 3),
                        "tps": round(tokens / sec, 2)})
    return out


def run_metrics(run_dir: str, concurrency: int | None = None) -> dict:
    rows = analyze.collect(run_dir)
    by_mode: dict[str, list[dict]] = {}
    for r in rows:
        by_mode.setdefault(r["mode"], []).append(r)

    out: dict = {
        "run_id": os.path.basename(os.path.normpath(run_dir)),
        "concurrency": concurrency,
        "modes": {},
    }
    for mode, rs in sorted(by_mode.items()):
        calls: list[dict] = []
        per_sample_tps: list[float] = []
        walls, tins, touts, ncalls, rounds = [], [], [], [], []
        truncated = empty = llm_errors = solve_timeouts = 0

        for r in rs:
            mine = _call_rates(run_dir, mode, r["task_id"], r["sample"])
            calls += mine
            if mine:
                per_sample_tps.append(statistics.median([c["tps"] for c in mine]))
            if r.get("solve_s"):
                walls.append(float(r["solve_s"]))
            tins.append(int(r.get("tokens_in") or 0))
            touts.append(int(r.get("tokens_out") or 0))
            ncalls.append(int(r.get("llm_calls") or 0))
            rounds.append(int(r.get("rounds") or 0))
            truncated += int(bool(r.get("truncated")))
            empty += int(bool(r.get("empty_reply")))
            llm_errors += int(r.get("llm_errors") or 0)
            solve_timeouts += int(bool((analyze._read_json(
                os.path.join(run_dir, mode, r["task_id"], f"s{r['sample']}",
                             "solve.json")) or {}).get("timed_out")))

        total_out = sum(c["tokens_out"] for c in calls)
        total_sec = sum(c["sec"] for c in calls)
        n = len(rs) or 1
        out["modes"][mode] = {
            "samples": len(rs),
            "tasks": len({r["task_id"] for r in rs}),
            "solve_s": _stats(walls),
            "solve_s_sum": round(sum(walls), 1),
            "tps_percall": {**_stats([c["tps"] for c in calls]),
                            "p10": round(analyze._pct([c["tps"] for c in calls], 0.10), 2)
                            if calls else None},
            "tps_per_sample_median": _stats(per_sample_tps),
            "tps_aggregate": round(total_out / total_sec, 2) if total_sec else None,
            "tokens_in_total": sum(tins),
            "tokens_out_total": sum(touts),
            "tokens_in_mean": round(sum(tins) / n, 1),
            "tokens_out_mean": round(sum(touts) / n, 1),
            "llm_calls_mean": round(sum(ncalls) / n, 2),
            "rounds_mean": round(sum(rounds) / n, 2),
            "rounds_max": max(rounds or [0]),
            "truncated": truncated,
            "truncated_rate": round(truncated / n, 3),
            "empty_reply": empty,
            "llm_errors": llm_errors,
            "solve_timeouts": solve_timeouts,
        }
        if concurrency and concurrency > 1:
            out["modes"][mode]["note"] = (
                f"tps 在并发 {concurrency} 下测得，是单路速率的下界；"
                "单路值用 metrics.py probe")
    return out


def render_md(m: dict) -> str:
    lines = ["## 资源与速度指标（metrics.py 自动生成）", ""]
    conc = m.get("concurrency")
    if conc:
        lines.append(f"求解并发：{conc}。并发行测得的 tps 只作相对比较，"
                     "单路速率用 `metrics.py probe`。")
    else:
        lines.append("求解并发未记录，tps 只作相对比较。")
    lines.append("")
    for mode, s in sorted(m.get("modes", {}).items()):
        lines += [f"### {mode}", "",
                  "| 指标 | 值 |", "| --- | ---: |",
                  f"| 样本数 | {s['samples']}（{s['tasks']} 题） |",
                  f"| 单题耗时 均值 / 中位数 / p90 / 最长 | "
                  f"{_fmt(s['solve_s'].get('mean'), 1)} / {_fmt(s['solve_s'].get('median'), 1)} / "
                  f"{_fmt(s['solve_s'].get('p90'), 1)} / {_fmt(s['solve_s'].get('max'), 1)} s |",
                  f"| 单题耗时合计 | {_fmt(s['solve_s_sum'], 0)} s |",
                  f"| tps（每次调用）中位数 / 均值 / p10 | "
                  f"{_fmt(s['tps_percall'].get('median'))} / {_fmt(s['tps_percall'].get('mean'))} / "
                  f"{_fmt(s['tps_percall'].get('p10'))} |",
                  f"| tps（按题取中位数再平均） | {_fmt(s['tps_per_sample_median'].get('mean'))} |",
                  f"| tps（聚合：总输出 token ÷ 总生成时间） | {_fmt(s['tps_aggregate'])} |",
                  f"| token 输入/输出 合计 | {s['tokens_in_total']} / {s['tokens_out_total']} |",
                  f"| 每题模型调用次数 均值 | {_fmt(s['llm_calls_mean'])} |",
                  f"| 每题轮数 均值 / 最多 | {_fmt(s['rounds_mean'])} / {s['rounds_max']} |",
                  f"| 输出被截断 | {s['truncated']}（{s['truncated_rate']:.1%}） |",
                  f"| 空回复 | {s['empty_reply']} |",
                  f"| 模型请求失败 | {s['llm_errors']} |",
                  f"| 求解超时 | {s['solve_timeouts']} |",
                  ""]
    return "\n".join(lines)


# --------------------------------------------------------------- speed probe

PROBE_SYSTEM = ("You are an expert Verilog designer. Reply with a single "
                "synthesizable SystemVerilog module named TopModule. "
                "Output only code.")
PROBE_USER = ("I would like you to implement a module named TopModule with the "
              "following interface. All input and output ports are one bit "
              "unless otherwise specified.\n\n"
              " - input  clk\n - input  reset\n - output [7:0] count\n\n"
              "Implement an 8-bit counter that increments on each rising edge "
              "of clk and is cleared synchronously when reset is high.")


def _endpoint(base_url: str, path: str) -> str:
    """base_url 可以是 http://host:port 或 http://host:port/v1；path 以 / 开头。"""
    base = base_url.rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    return base + path


def probe(base_url: str, model: str | None = None, max_tokens: int = 512,
          repeat: int = 1, timeout: float = 600) -> dict:
    """One request at a time: the rate an agent actually sees.

    Measures time to first token and decode rate separately, because a long
    context makes first-token latency dominate the per-task wall clock while the
    decode rate decides how many repair rounds fit in the budget.
    """
    import requests

    url = _endpoint(base_url, "/v1/chat/completions")
    runs = []
    for i in range(max(1, repeat)):
        payload = {
            "model": model or "default",
            "messages": [{"role": "system", "content": PROBE_SYSTEM},
                         {"role": "user", "content": PROBE_USER}],
            "max_tokens": max_tokens,
            "temperature": 0.0,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        t0 = time.time()
        ttft = None
        chunks = 0
        chars = 0
        usage = None
        with requests.post(url, json=payload, stream=True, timeout=timeout) as r:
            r.raise_for_status()
            for line in r.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except ValueError:
                    continue
                if obj.get("usage"):
                    usage = obj["usage"]
                choices = obj.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                piece = delta.get("content") or ""
                if piece:
                    if ttft is None:
                        ttft = time.time() - t0
                    chunks += 1
                    chars += len(piece)
        elapsed = time.time() - t0
        tokens = int((usage or {}).get("completion_tokens") or chunks)
        decode_s = max(0.0, elapsed - (ttft or 0.0))
        runs.append({
            "tokens_out": tokens,
            "ttft_s": round(ttft, 3) if ttft is not None else None,
            "elapsed_s": round(elapsed, 3),
            "tps_decode": round(tokens / decode_s, 2) if decode_s > 0 else None,
            "tps_total": round(tokens / elapsed, 2) if elapsed > 0 else None,
            "chars": chars,
            "usage": usage,
        })
    return {
        "base_url": base_url,
        "model": model,
        "max_tokens": max_tokens,
        "repeat": len(runs),
        "runs": runs,
        "tps_decode_median": _median([r["tps_decode"] for r in runs]),
        "ttft_median": _median([r["ttft_s"] for r in runs]),
    }


def _median(values: list) -> float | None:
    vals = [v for v in values if v is not None]
    return round(statistics.median(vals), 3) if vals else None


# ------------------------------------------------------------ server metrics

def parse_prometheus(text: str) -> dict:
    """Collect the metrics we care about. Values are summed per name, so a
    per-model label set does not hide the series."""
    sums: dict[str, float] = {}
    last: dict[str, float] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.rsplit(" ", 1)
        if len(parts) != 2:
            continue
        name = parts[0].split("{", 1)[0]
        if name not in PROM_KEYS:
            continue
        try:
            value = float(parts[1])
        except ValueError:
            continue
        sums[name] = sums.get(name, 0.0) + value
        last[name] = value
    kv = last.get("vllm:kv_cache_usage_perc",
                  last.get("vllm:gpu_cache_usage_perc"))
    return {
        "kv_cache_usage_perc": kv,
        "num_requests_running": last.get("vllm:num_requests_running"),
        "num_requests_waiting": last.get("vllm:num_requests_waiting"),
        "prompt_tokens_total": sums.get("vllm:prompt_tokens_total"),
        "generation_tokens_total": sums.get("vllm:generation_tokens_total"),
        "request_success_total": sums.get("vllm:request_success_total"),
        "raw": {k: round(v, 4) for k, v in sorted(last.items())},
    }


def scrape(base_url: str, timeout: float = 15) -> dict:
    import requests

    url = _endpoint(base_url, "/metrics")
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    out = parse_prometheus(resp.text)
    out["url"] = url
    return out


class MetricsWatcher:
    """Poll the server's /metrics while a run is in flight.

    Scraping once after the run is useless: by then the KV pool is empty again.
    The values worth having are the peaks seen while samples are running, plus
    the generation-token counter delta, which is an independent check on the
    tokens/s worked out from the traces.
    """

    def __init__(self, base_url: str, interval: float = 5.0):
        self.base_url = base_url
        self.interval = max(1.0, interval)
        self.samples: list[dict] = []
        self.first: dict | None = None
        self.error: str | None = None
        self._stop = None
        self._thread = None

    def _poll(self) -> None:
        while not self._stop.is_set():
            try:
                s = scrape(self.base_url)
            except Exception as exc:                      # noqa: BLE001
                self.error = f"{type(exc).__name__}: {exc}"[:200]
            else:
                self.error = None
                if self.first is None:
                    self.first = s
                self.samples.append({"t": round(time.time(), 3), **{
                    k: s.get(k) for k in ("kv_cache_usage_perc", "num_requests_running",
                                          "prompt_tokens_total",
                                          "generation_tokens_total")}})
            self._stop.wait(self.interval)

    def start(self) -> None:
        import threading

        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._poll, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._stop:
            self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def summary(self) -> dict:
        if not self.samples:
            return {"available": False, "error": self.error}
        kv = [s["kv_cache_usage_perc"] for s in self.samples
              if s.get("kv_cache_usage_perc") is not None]
        running = [s["num_requests_running"] for s in self.samples
                   if s.get("num_requests_running") is not None]
        first, last = self.samples[0], self.samples[-1]
        gen_first = (self.first or {}).get("generation_tokens_total")
        gen_last = last.get("generation_tokens_total")
        return {
            "available": True,
            "url": _endpoint(self.base_url, "/metrics"),
            "samples": len(self.samples),
            "kv_cache_usage_peak_perc": round(max(kv), 4) if kv else None,
            "kv_cache_usage_median_perc": round(statistics.median(kv), 4) if kv else None,
            "num_requests_running_max": max(running) if running else None,
            "generation_tokens_delta": (round(gen_last - gen_first, 1)
                                        if gen_first is not None and gen_last is not None
                                        else None),
            "prompt_tokens_delta": (
                round(last["prompt_tokens_total"] - first["prompt_tokens_total"], 1)
                if first.get("prompt_tokens_total") is not None
                and last.get("prompt_tokens_total") is not None else None),
            "last_error": self.error,
        }


# ------------------------------------------------------- joint run analysis

def joint_metrics(run_dir: str, before: str = "baseline",
                  after: str = "agent") -> dict:
    """Compare two modes of the same run, task by task.

    What matters for model selection is not the two scores but what happened
    between them: how many already-correct designs the agent broke, how many L0
    it recovered and where those landed (L1 = compiles but still wrong, L3 =
    the fix was real), and how much of the loss the repairs offset.
    See dev/failures/agent-repair.md.
    """
    rows = analyze.collect(run_dir)
    by_mode: dict[str, list[dict]] = {}
    for r in rows:
        by_mode.setdefault(r["mode"], []).append(r)
    if before not in by_mode or after not in by_mode:
        return {"available": False, "present": sorted(by_mode),
                "before": before, "after": after}

    def key(r: dict) -> tuple:
        return (r["task_id"], r["sample"])

    first = {key(r): r for r in by_mode[before]}
    second = {key(r): r for r in by_mode[after]}
    common = sorted(set(first) & set(second))

    transition: dict[tuple[int, int], int] = {}
    better: list[tuple[str, int, int]] = []
    worse: list[tuple[str, int, int]] = []
    same = 0
    broke: list[tuple[str, int]] = []
    recovered: list[tuple[str, int]] = []
    repairs: list[tuple[str, int, int]] = []
    skipped_env = 0

    for k in common:
        bl, al = first[k]["level"], second[k]["level"]
        if bl is None or al is None:
            skipped_env += 1
            continue
        transition[(bl, al)] = transition.get((bl, al), 0) + 1
        if al > bl:
            better.append((k[0], bl, al))
            if bl == 0:
                recovered.append((k[0], al))
            elif bl == 1:
                repairs.append((k[0], bl, al))
        elif al < bl:
            worse.append((k[0], bl, al))
        else:
            same += 1
        if bl == 3 and al < 3:
            broke.append((k[0], al))

    def set_score(rs: list[dict]) -> float | None:
        scored = [r for r in rs if r["level"] is not None]
        if not scored:
            return None
        return round(sum(r["coefficient"] for r in scored) / len(scored), 4)

    def levels(rs: list[dict]) -> dict:
        counts = {0: 0, 1: 0, 2: 0, 3: 0}
        env = 0
        for r in rs:
            if r["level"] is None:
                env += 1
            else:
                counts[r["level"]] += 1
        return {"L0": counts[0], "L1": counts[1], "L2": counts[2],
                "L3": counts[3], "env": env}

    sb, sa = set_score(by_mode[before]), set_score(by_mode[after])
    gain = round(sa / sb, 4) if sb and sa is not None else None
    reaches = {f"L{n}": sum(1 for _, al in recovered if al == n) for n in (1, 2, 3)}

    # Which task types does the agent help, and which does it damage?  This is
    # the table the skill package and REPORT.md are built from.
    cats: dict[str, dict] = {}
    for k in common:
        r0, r1 = first[k], second[k]
        if r0["level"] is None or r1["level"] is None:
            continue
        d = cats.setdefault(r0.get("category") or "未分类",
                            {"n": 0, "before_l3": 0, "after_l3": 0,
                             "better": 0, "worse": 0, "broke": 0})
        d["n"] += 1
        d["before_l3"] += int(r0["level"] == 3)
        d["after_l3"] += int(r1["level"] == 3)
        d["better"] += int(r1["level"] > r0["level"])
        d["worse"] += int(r1["level"] < r0["level"])
        d["broke"] += int(r0["level"] == 3 and r1["level"] < 3)

    # How far did the extra rounds actually get?  A proxy for the marginal value
    # of another repair round: pass rate grouped by the number of rounds used.
    by_rounds: dict[str, dict] = {}
    for k in common:
        r1 = second[k]
        if r1["level"] is None:
            continue
        n = str(int(r1.get("rounds") or 0))
        d = by_rounds.setdefault(n, {"n": 0, "l3": 0})
        d["n"] += 1
        d["l3"] += int(r1["level"] == 3)

    return {
        "available": True,
        "before": before,
        "after": after,
        "by_category": cats,
        "by_rounds": by_rounds,
        "tasks_common": len(common),
        "skipped_env": skipped_env,
        "set_score": {before: sb, after: sa,
                      "delta": round(sa - sb, 4)
                      if sb is not None and sa is not None else None},
        "gain": gain,
        "levels": {before: levels(by_mode[before]), after: levels(by_mode[after])},
        "better": len(better),
        "worse": len(worse),
        "same": same,
        "transition": {f"{b}->{a}": n for (b, a), n in sorted(transition.items())},
        "broke_correct": {"count": len(broke),
                          "tasks": [{"task": t, "level": al} for t, al in broke]},
        "recovered_l0": {"count": len(recovered), "reaches": reaches,
                         "to_l3_ratio": round(reaches["L3"] / len(recovered), 3)
                         if recovered else None},
        "fixed_l1": {"count": len(repairs),
                     "tasks": [{"task": t, "to": al} for t, _, al in repairs]},
        "examples": {
            "better": [{"task": t, "from": b, "to": a} for t, b, a in better[:12]],
            "worse": [{"task": t, "from": b, "to": a} for t, b, a in worse[:12]],
        },
    }


def _levels_txt(d: dict) -> str:
    return f"{d['L0']}/{d['L1']}/{d['L2']}/{d['L3']}" + (
        f"（环境失败 {d['env']}）" if d.get("env") else "")


def render_joint_md(d: dict) -> str:
    if not d.get("available"):
        return ("## 联合跑分对比\n\n本次运行没有同时包含 "
                f"{d.get('before')} 与 {d.get('after')} 两个模式"
                f"（现有：{', '.join(d.get('present') or [])}），跳过。")
    b, a = d["before"], d["after"]
    lines = ["## 联合跑分对比（`metrics.py joint` 自动生成）", "",
             f"共同题目 {d['tasks_common']} 道"
             + (f"，另有 {d['skipped_env']} 道因环境失败无法比较"
                if d["skipped_env"] else "") + "。", "",
             f"| 指标 | {b} | {a} |", "| --- | ---: | ---: |",
             f"| 题集得分 | {_fmt(d['set_score'].get(b), 4)} "
             f"| {_fmt(d['set_score'].get(a), 4)} |",
             f"| 等级分布 | {_levels_txt(d['levels'][b])} "
             f"| {_levels_txt(d['levels'][a])} |", "",
             f"得分变化 **{_fmt(d['set_score'].get('delta'), 4)}**"
             + (f"，增益 **{d['gain']}**" if d.get("gain") else "") + "。", "",
             f"逐题：**变好 {d['better']} 道，变差 {d['worse']} 道，"
             f"不变 {d['same']} 道**。", ""]
    lines += [f"### 等级转移（行 = {b}，列 = {a}）", "",
              "| 从 \\ 到 | L0 | L1 | L2 | L3 |", "| --- | ---: | ---: | ---: | ---: |"]
    for bl in (0, 1, 2, 3):
        cells = [str(d["transition"].get(f"{bl}->{al}", 0)) for al in (0, 1, 2, 3)]
        lines.append(f"| L{bl} | " + " | ".join(cells) + " |")
    lines.append("")
    rec = d["recovered_l0"]
    broke_txt = "、".join(f"{x['task']}→L{x['level']}"
                          for x in d["broke_correct"]["tasks"][:6])
    lines += ["### 两个关键读数", "",
              f"- **把本来做对的题改坏**：{d['broke_correct']['count']} 道"
              + (f"（{broke_txt}）" if broke_txt else ""),
              f"- **修好的 L0**：{rec['count']} 道，其中到 L1 {rec['reaches']['L1']}、"
              f"L2 {rec['reaches']['L2']}、L3 {rec['reaches']['L3']}"
              + (f"，真正做对的比例 **{rec['to_l3_ratio']:.0%}**"
                 if rec["to_l3_ratio"] is not None else ""),
              f"- **修好的 L1（真正的功能修复）**：{d['fixed_l1']['count']} 道", ""]
    if d.get("by_category"):
        lines += ["### 按题型看 agent 帮了什么、坏了什么", "",
                  "| 题型 | 题数 | L3（前→后） | 变好 | 变差 | 改坏 |",
                  "| --- | ---: | --- | ---: | ---: | ---: |"]
        for c, v in sorted(d["by_category"].items(),
                           key=lambda kv: (-kv[1]["broke"], -kv[1]["n"])):
            lines.append(f"| {c} | {v['n']} | {v['before_l3']} → {v['after_l3']} "
                         f"| {v['better']} | {v['worse']} | {v['broke']} |")
        lines.append("")
    if d.get("by_rounds"):
        lines += ["### 用了几轮、结果如何（agent 侧，轮数越多不代表越好）", "",
                  "| 用了几轮 | 题数 | 其中 L3 |", "| ---: | ---: | ---: |"]
        for n, v in sorted(d["by_rounds"].items()):
            lines.append(f"| {n} | {v['n']} | {v['l3']} |")
        lines.append("")
    if d["examples"]["worse"]:
        lines += ["变差的题：", ""]
        lines += [f"- {e['task']}：L{e['from']} → L{e['to']}"
                  for e in d["examples"]["worse"]]
        lines.append("")
    return "\n".join(lines)


# ------------------------------------------------------------- KV cache size

def _config_of(spec: str) -> dict:
    if os.path.isfile(spec):
        with open(spec, encoding="utf-8") as fh:
            return json.load(fh)
    import requests

    url = f"https://huggingface.co/{spec}/raw/main/config.json"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.json()


def kv_theory(config: dict, contexts=(8192, 16384, 32768, 65536),
              dtype_bytes: int = 2) -> dict:
    """KV bytes per token, split by layer type.

    full attention grows with the sequence; sliding window stops at the window;
    linear attention keeps a fixed state and contributes no KV at all.
    """
    cfg = config.get("text_config", config)
    layers = int(cfg.get("num_hidden_layers") or 0)
    heads = cfg.get("num_attention_heads") or 0
    kv_heads = cfg.get("num_key_value_heads") or heads
    head_dim = cfg.get("head_dim") or (cfg.get("hidden_size", 0) // heads if heads else 0)
    ltypes = cfg.get("layer_types")
    window = cfg.get("sliding_window")

    if ltypes:
        n_full = sum(1 for t in ltypes if "full" in t)
        n_slide = sum(1 for t in ltypes if "sliding" in t)
        n_linear = sum(1 for t in ltypes if "linear" in t)
    else:
        n_full, n_slide, n_linear = layers, 0, 0
        window = None

    per_layer = 2 * int(kv_heads) * int(head_dim) * dtype_bytes   # K and V
    full_per_token = n_full * per_layer
    slide_bytes = n_slide * per_layer * int(window) if window else 0

    at = {}
    for ctx in contexts:
        at[str(ctx)] = {
            "full_bytes": full_per_token * ctx,
            "sliding_bytes": slide_bytes,
            "total_bytes": full_per_token * ctx + slide_bytes,
            "total_gib": round((full_per_token * ctx + slide_bytes) / BYTES_PER_GIB, 3),
        }
    return {
        "model_type": cfg.get("model_type"),
        "layers": layers,
        "full_layers": n_full,
        "sliding_layers": n_slide,
        "linear_layers": n_linear,
        "sliding_window": window,
        "kv_heads": kv_heads,
        "head_dim": head_dim,
        "dtype_bytes": dtype_bytes,
        "kv_bytes_per_token": full_per_token,
        "kv_kib_per_token": round(full_per_token / 1024, 1),
        "sliding_bytes_total": slide_bytes,
        "at_context": at,
        "note": ("线性注意力层不产生 KV；滑动窗口层封顶在窗口长度。"
                 "若服务端不识别 layer_types，会按全注意力分配，实际值可能大 8–30 倍。"
                 if ltypes else
                 "config.json 没有 layer_types，按全部是全注意力层计算。"),
    }


def render_kv_md(rep: dict) -> str:
    lines = [f"模型类型 `{rep['model_type']}`：{rep['layers']} 层 = "
             f"{rep['full_layers']} 全注意力 + {rep['sliding_layers']} 滑动窗口"
             f"（窗口 {rep['sliding_window']}） + {rep['linear_layers']} 线性注意力",
             "",
             f"每 token {rep['kv_kib_per_token']} KiB（kv_heads {rep['kv_heads']} × "
             f"head_dim {rep['head_dim']}，dtype {rep['dtype_bytes']} 字节）", "",
             "| 上下文 | 全注意力部分 | 滑动窗口部分 | 合计 |",
             "| ---: | ---: | ---: | ---: |"]
    for ctx, v in rep["at_context"].items():
        lines.append(f"| {int(ctx) // 1024}k | {v['full_bytes'] / BYTES_PER_GIB:.2f} GiB "
                     f"| {v['sliding_bytes'] / BYTES_PER_GIB:.2f} GiB "
                     f"| {v['total_gib']:.2f} GiB |")
    lines += ["", rep["note"]]
    return "\n".join(lines)


# --------------------------------------------------------------------- VRAM

def parse_rocm_smi(text: str) -> dict:
    """Parse `rocm-smi --showmeminfo vram --csv` output (one row per card)."""
    total = used = None
    for line in text.splitlines():
        fields = [f.strip() for f in line.split(",")]
        if len(fields) < 3 or not fields[0].lower().startswith("card"):
            continue
        try:
            t, u = int(float(fields[1])), int(float(fields[2]))
        except ValueError:
            continue
        total = t if total is None else max(total, t)
        used = u if used is None else max(used, u)
    if total is None:
        return {}
    return {"total_bytes": total, "used_bytes": used,
            "total_gib": round(total / BYTES_PER_GIB, 2),
            "used_gib": round(used / BYTES_PER_GIB, 2),
            "used_perc": round(100.0 * used / total, 1) if total else None}


def summarize_vram(text: str) -> dict:
    """Peak and steady VRAM from a log of `rocm-smi --showmeminfo vram --csv`."""
    samples = [parse_rocm_smi(block) for block in re.split(r"\n\s*\n", text)]
    used = [s["used_gib"] for s in samples if s]
    if not used:
        return {}
    used_sorted = sorted(used)
    return {
        "samples": len(used),
        "peak_gib": round(max(used), 2),
        "steady_gib": round(statistics.median(used_sorted[len(used_sorted) // 4:]) , 2)
        if len(used) > 3 else round(statistics.median(used), 2),
        "min_gib": round(min(used), 2),
        "total_gib": samples[0].get("total_gib") if samples else None,
    }


# --------------------------------------------------------------------- main

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="跑分指标：显存、KV Cache、tps、单题耗时")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="汇总一次跑分，写 metrics.json / metrics.md")
    p_run.add_argument("run_dir")
    p_run.add_argument("--concurrency", type=int, default=None, help="跑分时的求解并发")

    p_joint = sub.add_parser("joint", help="对比同一次运行的两个模式，写 joint.json / joint.md")
    p_joint.add_argument("run_dir")
    p_joint.add_argument("--before", default="baseline", help="对比前的模式（默认 baseline）")
    p_joint.add_argument("--after", default="agent", help="对比后的模式（默认 agent）")

    p_probe = sub.add_parser("probe", help="并发 1 的速度探测")
    p_probe.add_argument("base_url")
    p_probe.add_argument("--model", default=None)
    p_probe.add_argument("--max-tokens", type=int, default=512)
    p_probe.add_argument("--repeat", type=int, default=1)

    p_scrape = sub.add_parser("scrape", help="读服务端 /metrics")
    p_scrape.add_argument("base_url")

    p_kv = sub.add_parser("kv", help="由 config.json 算 KV Cache 大小")
    p_kv.add_argument("spec", help="config.json 路径，或 HF 仓库名")
    p_kv.add_argument("--contexts", default="8192,16384,32768,65536")
    p_kv.add_argument("--dtype-bytes", type=int, default=2)

    p_vram = sub.add_parser("vram", help="解析 rocm-smi 采样日志")
    p_vram.add_argument("log")

    args = ap.parse_args(argv)

    if args.cmd == "run":
        m = run_metrics(args.run_dir, args.concurrency)
        with open(os.path.join(args.run_dir, "metrics.json"), "w", encoding="utf-8") as fh:
            json.dump(m, fh, ensure_ascii=False, indent=2)
        md = render_md(m)
        with open(os.path.join(args.run_dir, "metrics.md"), "w", encoding="utf-8") as fh:
            fh.write(md + "\n")
        print(md)
        return 0

    if args.cmd == "joint":
        d = joint_metrics(args.run_dir, args.before, args.after)
        with open(os.path.join(args.run_dir, "joint.json"), "w", encoding="utf-8") as fh:
            json.dump(d, fh, ensure_ascii=False, indent=2)
        md = render_joint_md(d)
        with open(os.path.join(args.run_dir, "joint.md"), "w", encoding="utf-8") as fh:
            fh.write(md + "\n")
        print(md)
        return 0

    if args.cmd == "probe":
        print(json.dumps(probe(args.base_url, args.model, args.max_tokens, args.repeat),
                         ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "scrape":
        print(json.dumps(scrape(args.base_url), ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "kv":
        rep = kv_theory(_config_of(args.spec),
                        contexts=[int(c) for c in args.contexts.split(",")],
                        dtype_bytes=args.dtype_bytes)
        print(render_kv_md(rep))
        print()
        print(json.dumps(rep, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "vram":
        with open(args.log, encoding="utf-8", errors="replace") as fh:
            print(json.dumps(summarize_vram(fh.read()), ensure_ascii=False, indent=2))
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
