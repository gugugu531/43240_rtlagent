# dev/ — 团队开发区（不提交）

`43240-agent/` 是要提交给赛事方的方案目录，本目录是其中唯一**不随方案一起提交**的
部分（`.dockerignore` 已经排除了 `dev/`，整理提交文件时也要把它去掉）。

这里可能摘录 VerilogEval（本赛道用于自测的公开题库）的参考答案。这类内容一旦进入
提交的方案，会被认定为预置答案，整个赛道的成绩作废（`SCORING.md` 第 2.9 条），
所以**只能放在 `dev/`**。

开始开发前，请先读 [`CONVENTIONS.md`](CONVENTIONS.md)（开发规范）。方案的整体结构见
[`../README.md`](../README.md)。

## 现状速览（5 分钟）

| 项 | 现状 | 去哪看 |
| --- | --- | --- |
| **现在在做什么** | 模型选型（初赛阶段）。按团队口径**本阶段只测 baseline**，不做 agent 联合测试 | [`decisions/0002`](decisions/0002-model-choice.md) |
| **测到什么程度** | 19 个模型有全题集（155 题）baseline；4 个候选有联合跑分（`quick` 34 题） | [对照总表](notes/generated/2026-09-25-candidate-tables.md) |
| **当前建议** | 首选 `Qwen3-4B-Instruct-2507`（BF16）；挑战者按「反超所需 `S_a`」排序，最低的是 `Devstral-Small-2-24B`（0.580）、`Qwen2.5-Coder-7B`（0.597） | [`decisions/0002`](decisions/0002-model-choice.md) 的「结论（最新）」 |
| **最终由谁定** | 团队评判——决策文档只给建议与依据 | 同上 |
| **有哪些已知问题** | 5 个问题：2 个已解决、1 个部分解决、2 个未解决（含 2 条「已确认受限」） | [`failures/README.md`](failures/README.md) 的状态索引 |
| **接下来做什么** | 联合阶段测门槛最低的两个候选；提交前必须处理 `serve/vllm.sh` 的参数与 gpt-oss 词表 | [`notes/2026-09-25-screening-progress.md`](notes/2026-09-25-screening-progress.md) |
| **Agent 框架讨论** | 审查已完成；Python Workflow、Node 注册、精简目录与统一指标方向已记录；已实现模型证据记录、Python Workflow、候选策略、失败分类、检查复用与独立进程监督；默认单次生成，统一实验入口待实现 | [审查记录](notes/2026-10-05-agent-review.md)、[设计方案](notes/2026-10-05-agent-redesign-plan.md)、[第一阶段进展](docs/notes/2026-10-05-stage1-progress.md)、[第二阶段进展](docs/notes/2026-10-05-stage2-progress.md)、[第三阶段进展](docs/notes/2026-10-05-stage3-progress.md) |
| **风险** | `M`（满分线倍数）未知；决赛硬件 R9700（gfx1201）当前拿不到、未验证 | [`decisions/0002`](decisions/0002-model-choice.md) 的「未决问题」 |

**三层阅读路径**：① 本节的速览 → ② [`decisions/`](decisions/README.md)（结论与横向对比）+
[`failures/README.md`](failures/README.md)（问题状态）→ ③ [`notes/`](notes/README.md)
（设计与进展）、[`experiments/`](experiments/README.md)（逐次跑分）与 `runs/`（原始数据）。

## 目录

| 路径 | 放什么 | 是否提交到 git |
| --- | --- | --- |
| [`docs/`](docs/readme.md) | 新增框架文档的统一入口；设计与阶段记录分开存放 | 是 |
| [`CONVENTIONS.md`](CONVENTIONS.md) | 开发规范：目录、文档、提交与分支、代码约定 | 是 |
| [`decisions/`](decisions/README.md) | 重要决策记录：结论、横向对比表、依据、未决问题 | 是 |
| [`notes/`](notes/README.md) | 设计与进展笔记；`notes/generated/` 是脚本生成的对照表（不要手改），`notes/archive/` 是旧笔记 | 是 |
| [`experiments/`](experiments/README.md) | 每次跑分一份记录，脚本自动生成（需补写「改动与假设」「结论」） | 是 |
| [`failures/`](failures/README.md) | 失败原因分析：问题状态索引 + 每类问题一篇（问题 → 已解决 / 未解决） | 是 |
| [`eval/`](eval/README.md) | 跑分和分析工具：并行跑分、失败原因分类、两次运行对比、汇总对照表 | 是 |
| [`remote/`](remote/README.md) | 用远端 GPU 测试的脚本和说明，包括自动启动和销毁 AMD Radeon Cloud 实例 | 是（`remote.env`、`cloud.state` 除外） |
| `runs/` | 跑分生成的原始文件（`score.json`、`metrics.json`、`samples.csv`、日志） | 否 |

## 官方文档索引

仓库根目录的文件和 `example/` 都是主办方提供的原始文件，**只读，不要修改**。
下表路径相对于仓库根目录。

| 想查什么 | 看哪里 |
| --- | --- |
| 赛题、提交结构、提交检查清单 | `README.md` |
| 评分公式、提交条件、作弊判定 | `SCORING.md` |
| 投题接口 `/v1/health`、`/v1/solve`，trace 格式，运行环境 | `docs/API_CONTRACT.md` |
| 常见问题 | `docs/FAQ.md` |
| 本地判定工具的用法、VerilogEval 题目转换 | `selftest/README.md` |
| 设计报告模板 | `REPORT_TEMPLATE.md` |
| 示例方案原版（用来对照自己改了什么） | `example/` |

## 跑分之后要做的事

1. `experiments/<运行编号>.md` 已经自动生成，补写「改动与假设」「结论」两节
2. 结果稳定后更新总表：`python3 dev/eval/overview.py --out dev/notes/generated/2026-09-25-candidate-tables.md`
3. 值得分析的失败题目，把原因写进 `failures/` 对应文件，**并同步更新 `failures/README.md` 的状态索引**
4. 影响方案设计的结论，记入 `decisions/`（先给对比表，再写结论）；阶段性结果之后整理进 `../REPORT.md`
