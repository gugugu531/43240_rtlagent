# eval/ — 评测与实验工具

团队开发用的跑分和分析工具，不随方案提交。判定和算分直接调用官方的 `selftest/judge.py`
和 `selftest/score.py`，口径与 `selftest/run_selftest.sh` 完全一致，在此基础上补充了：

| 问题 | `run_selftest.sh` | 本目录 |
| --- | --- | --- |
| 速度 | 逐个样本串行 | 求解和判定分别并行 |
| 判定日志 | 每道题只留一份，不同样本、不同模式互相覆盖 | 每个样本单独保留完整日志和原始判定结果 |
| 失败原因 | 只有等级 | 每个样本一个失败原因（见下表） |
| 模型调用 | 不统计 | 调用次数、token 数、是否截断、求解耗时 |
| 题型 | 无 | 按题型分别统计 |
| 两次运行对比 | 无 | `compare.py` 逐题对比 |
| 题目子集 | 只能换题目目录 | `--taskset smoke` / `quick`；默认排除已知有问题的题 |

目录内容：

| 文件 | 作用 |
| --- | --- |
| `run_eval.py` | 跑分入口：求解 → 判定 → 汇总 → 分析 → 生成实验记录 |
| `remote_eval.sh` | 同上，但模型服务在远端服务器（经 SSH 隧道连接） |
| `analyze.py` | 给一次运行的每个样本归类失败原因，生成 `analysis.md` 等 |
| `compare.py` | 逐题对比两次运行 |
| `categorize.py` | 根据题面关键词给题目分类，重新生成 `tasksets/categories.tsv` |
| `tasksets/` | 题目子集、排除清单、分类表 |

## 用法

以下命令都在 `43240-agent/` 目录下运行。

### 1. 先检查判定链路

```bash
python3 dev/eval/run_eval.py --tag ref --modes reference --judge-jobs 8
```

用参考答案跑一遍，不需要模型。所有题都应该是 L3（可综合），否则说明本机 Vivado 有问题，
后面的分数都不可信。

### 2. 使用 API 或本机模型服务

`run_eval.py` 使用当前 shell 中的 LLM 和 Vivado 环境变量，**不会**自己读取
`selftest/env.sh`。要使用那里的配置：

```bash
(set -a; . ../selftest/env.sh; set +a; python3 dev/eval/run_eval.py --tag smoke --taskset smoke)
```

注意 `baseline.py` 发请求时不带 API key，连不上商用 API。用商用 API 时只能跑
`--modes agent`，增益要用本机或远端的模型服务测。

### 3. 使用远端模型服务

```bash
dev/eval/remote_eval.sh --tag veval-s1 --jobs 8
```

会先建立 SSH 隧道，再让 agent 和基线都连到远端模型（与 `dev/remote/` 的配置相同），
其余参数原样传给 `run_eval.py`。

### 常用参数

| 参数 | 含义 | 默认值 |
| --- | --- | --- |
| `--tag` | 运行编号中的标签 | `eval` |
| `--tasks` | 题目目录 | 仓库根目录的 `tasks/` |
| `--taskset` | 题目子集：`smoke`（8 题，几分钟）、`quick`（34 题），或一个每行一个题名的文件 | 全部题目 |
| `--modes` | `agent`、`baseline`、`reference`，逗号分隔 | `agent,baseline` |
| `--samples` | 每题采样次数 | 1 |
| `--jobs` | 同时求解的样本数 | 4 |
| `--judge-jobs` | 同时判定的样本数，每个都会启动 Vivado | 4 |
| `--solve-timeout` | 单个样本求解的时间上限（秒），超时会结束整个进程树，按 L0 计 | 900 |
| `--no-exclude` | 不跳过 `tasksets/exclude.txt` 中的题 | |
| `--limit` | 只跑前 N 道题 | |

桩模式（`LLM_BACKEND` 未设置或为 `mock`）下自动跳过基线，理由与 `run_selftest.sh` 相同。

关于并发：判定主要受 CPU 和内存限制，开发机（16 核、30 GB 内存）上 `--judge-jobs 4`
判 8 道题约 90 秒，可以按机器情况调整。求解并发取决于模型服务能承受多少并发请求。
并行时各样本互相影响，所以求解耗时**只能用来相对比较**，不等于赛事方计分的墙钟时间
（那个要用 `dev/remote/submit_client.py` 在独占环境下测）。

### 对比两次运行

```bash
python3 dev/eval/compare.py <旧运行编号> <新运行编号>
python3 dev/eval/compare.py <运行A> <运行B> --mode agent
python3 dev/eval/compare.py <运行A> <运行B> --mode baseline=agent   # 对比不同模式
```

只比较两次运行中都判定过的题。每题只采样一次时，有几道题的等级会因为随机性而变化，
差别不大时要用 `--samples 3` 以上再确认。

## 输出

全部写在 `dev/runs/<运行编号>/`（不提交到 git），布局与 `run_selftest.sh` 一致，
`score.py` 可以直接汇总：

```
dev/runs/<运行编号>/
├── meta.json                       git commit、模型、参数
├── <模式>/<题目>/s<k>/
│   ├── solution.v、trace.jsonl、run.log
│   ├── solve.json                  求解耗时、是否超时
│   ├── verdict.json、judge.log     判定器的原始结果和完整日志
│   └── synth.log                   综合日志（跑到综合时才有）
├── results/<模式>.<题目>.s<k>.json judge.py 的结果
├── score.json、score.txt           score.py 汇总
├── analysis.json、analysis.md      analyze.py 分析
└── samples.csv                     每个样本一行，方便用表格软件筛选
```

实验记录 `dev/experiments/<运行编号>.md` 自动生成，并附上分析结果。其中「改动与假设」
「结论」两节需要手动填写。

`dev/remote/` 中的 `remote_selftest.sh` 和 `submit_client.py` 也会调用 `analyze.py`，
但它们没有逐个样本保留判定日志，L0 的原因会粗一些。

## 失败原因

每个样本只归入一类。等级说明它走到了哪一步，原因说明它为什么没有走得更远。

| 原因 | 含义 | 判断依据 |
| --- | --- | --- |
| `pass` | L3 | |
| `synth_fail` / `synth_timeout` | L2，综合失败 / 综合超时（超时按 L2 计分） | 判定结果 |
| `sim_mismatch` | L1，仿真结果与参考实现不一致 | 失配数大于 0 |
| `sim_timeout` / `sim_no_samples` | L1，仿真超时 / 没有产生比对结果 | 判定结果 |
| `interface` | L0，模块名或端口与测试台不符 | 日志中有 `VRFC 10-3180` / `VRFC 10-2063` |
| `syntax` | L0，xvlog 语法分析失败 | 待测代码的 xvlog 返回码 |
| `elab` | L0，详细描述（xelab）失败，但不是接口问题 | xelab 失败且没有接口类错误 |
| `truncated` | L0，模型输出被截断，没有代码 | trace 中 `finish` 为 `length` |
| `empty_reply` / `llm_error` | L0，模型回复为空 / 请求失败 | trace |
| `solve_timeout` / `deadline` | L0，超时被结束 / agent 用完时间预算 | `solve.json` / trace |
| `agent_error` / `no_code` / `transport` | L0，agent 异常 / 没提取到代码 / 投题接口请求失败 | trace、`response.json` |
| `env` | 环境失败（授权、题目本身有问题等），不计分 | judge.py 的 `tool_error` |

只有在最终没有代码时才把截断记为原因；中途被截断、后来修好的样本，另外统计在
「被截断的样本」数里。

## 题目子集和分类

- `tasksets/exclude.txt`：默认不跑的题，每道写明原因。目前只有 `Prob099_m2014_q6c`
  （数据集自身的缺陷，见 `selftest/README.md`）
- `tasksets/smoke.txt`：冒烟测试，3 道示例题加 5 道 VerilogEval 题，只检查流程能否跑通
- `tasksets/quick.txt`：从 VerilogEval 155 道可用题中按题型等比例、等间隔抽取的 34 道，
  用于快速迭代。**同一阶段的对比要用同一份子集**
- `tasksets/categories.tsv`：题目分类，由 `categorize.py` 按题面关键词（状态机、卡诺图、
  波形表、有没有 `clk` 端口等）生成。分得比较粗，只用来看哪类题失败多，可以手工修正；
  重新运行 `categorize.py` 会覆盖手工修正

留出集（只用于检查、不用于调参的题目）还没有：VerilogEval 可能已在模型训练数据中，
需要另找其他来源的题目，见 `../notes/2026-09-23-plan-review.md`。
