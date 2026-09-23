# dev/ — 团队开发区（不提交）

`43240-agent/` 是要提交给赛事方的方案目录，本目录是其中唯一**不随方案一起提交**的
部分（`.dockerignore` 已经排除了 `dev/`，整理提交文件时也要把它去掉）。

这里可能摘录 VerilogEval（本赛道用于自测的公开题库）的参考答案。这类内容一旦进入
提交的方案，会被认定为预置答案，整个赛道的成绩作废（`SCORING.md` 第 2.9 条），
所以**只能放在 `dev/`**。

开始开发前，请先读 [`CONVENTIONS.md`](CONVENTIONS.md)（开发规范）。方案的整体结构见
[`../README.md`](../README.md)。

## 目录

| 路径 | 放什么 | 是否提交到 git |
| --- | --- | --- |
| [`CONVENTIONS.md`](CONVENTIONS.md) | 开发规范：目录、文档、提交与分支、代码约定 | 是 |
| [`decisions/`](decisions/README.md) | 重要决策记录，如模型、推理后端、重试策略的选择 | 是 |
| [`notes/`](notes/README.md) | 开发日志 | 是 |
| [`experiments/`](experiments/README.md) | 每次跑分一份记录，脚本自动生成 | 是 |
| [`failures/`](failures/README.md) | 失败原因分析 | 是 |
| [`remote/`](remote/README.md) | 用远端服务器测试的脚本和说明 | 是（`remote.env` 除外） |
| `runs/` | 跑分生成的原始文件 | 否 |

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
2. 值得分析的失败题目，把原因写进 `failures/`，并附上 `runs/` 中对应 trace 的路径
3. 影响方案设计的结论，记入 `decisions/`；阶段性结果之后整理进 `../REPORT.md`
