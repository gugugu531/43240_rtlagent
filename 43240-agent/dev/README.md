# 团队开发区

本目录不随方案提交；原始产物和参考答案只能留在开发区。先读[Quickstart](docs/quickstart.md)，接口与架构查[User Manual](docs/user-manual.md)。完整规范与保留的历史证据统一从[文档索引](docs/readme.md)进入。

当前框架支持单次生成、检查修复及有限候选对照，默认 `single_generate` 复用官方 baseline 的
请求和提取规则。流程选择、初始检查点重放及验证边界见[运行接口](docs/design/agent-runtime.md)。
实现可用与完整题集收益分别判断；模型和服务尚未最终确定。

| 目录 | 职责 |
| --- | --- |
| tools/ | 统一实验、可选判定、远端管理、历史分析和打包检查 |
| configs/ | 实验配置、任务与排除清单 |
| tests/ | 回归和组件测试 |
| runs/ | 原始产物，不提交 Git |
| docs/ | 统一团队文档，包括开发规范 |

可视化检查日志：直接用浏览器打开 [日志查看器](tools/log_viewer.html)，选择包含 `trace.jsonl`
和 `records/` 的单题输出目录，或整个实验目录。可查看 Workflow、Node、模型与工具调用的
状态、请求、回复和原始事件；文件只在本机读取，不需要服务器。用法见[日志查看器说明](docs/design/log-viewer.md)。

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
../selftest/run_selftest.sh --reference --tasks ../tasks/verilogeval --out dev/runs/reference-check
```

历史模型选型结果及原始格式的分析工具继续保留；新的实验不再使用旧 run_eval.py。
历史实验记录统一从[实验索引](docs/experiments/index.md)查找；10 月 4 日的旧记录已纳入 Git，保留原路径。
