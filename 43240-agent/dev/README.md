# 团队开发区

本目录不随方案提交；原始产物和参考答案只能留在开发区。完整规范、设计、决策、失败分析和
实验记录统一从 [docs/readme.md](docs/readme.md) 查阅。

当前框架已具备 Python Workflow/Node、完整模型证据、候选保护、预算与进程监督、YAML 配置和
统一单题/批量实验入口。默认 single_generate 近似 baseline；可选 repair_loop 的全量收益仍待验证。
[第五阶段](docs/notes/2026-10-05-stage5-progress.md)已完成目录整理和独立打包验证，历史重放与新的实验比较暂缓。

| 目录 | 职责 |
| --- | --- |
| tools/ | 统一实验、可选判定、远端管理、历史分析和打包检查 |
| configs/ | 实验配置、任务与排除清单 |
| tests/ | 回归和组件测试 |
| runs/ | 原始产物，不提交 Git |
| docs/ | 统一团队文档，包括开发规范 |

统一实验：

```bash
# 在 43240-agent/ 中运行
python3 dev/tools/run.py --config dev/configs/smoke.yaml --task ex03_lfsr8
python3 dev/tools/run.py --config dev/configs/remote-smoke.yaml
python3 dev/tools/submission.py
```

远程配置位于 tools/remote/remote.env；原有文件迁移时保留内容，不提交 Git。
参考答案链路验证使用主办方脚本，明确把输出放在开发区：

```bash
../selftest/run_selftest.sh --reference --out dev/runs/reference-check
```

历史模型选型结果及原始格式的分析工具继续保留；新的实验不再使用旧 run_eval.py。
用户已有的一份未提交笔记仍在原 experiments/ 位置，未修改、未纳入本阶段提交。
