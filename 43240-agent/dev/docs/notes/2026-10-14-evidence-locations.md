# 本地证据位置核对

类型：文档维护核对。日期：2026-10-14。范围：当前工作区的路径存在性，不是重跑实验或逐样本完整性审计。

## 可访问的记录

[实验索引](../experiments/index.md)收录的 75 份历史实验记录，其正文给出的主运行目录在本工作区均存在。
其中 74 份位于 docs/experiments，另 1 份旧格式记录保留在 dev/experiments。
检查按旧表的“原始文件”和新记录的“原始记录”字段解析；相对 dev/runs 路径从 43240-agent 解析。

`43240-agent/dev/runs/20261011-autodl-qwen3/` 和 `43240-agent/dev/runs/dataset-validation/audit.json` 可访问。
运行目录不随 Git 提交；复现仍需核对样本、配置、模型权重、工具环境与原始日志。

## 当前工作区未找到的路径

| 历史位置 | 对应记录 | 本次处理 |
| --- | --- | --- |
| 聊天 outputs/autodl-qwen3、work/autodl-qwen3 | [AutoDL 汇总](2026-10-11-autodl-qwen3-results.md)、[输出额度补测](2026-10-11-qwen3-output-budget.md) | 保留历史位置；不将其表述为当前仓库内附件 |
| dev/runs/pr33-review-20261014 | [PR #33 验收](2026-10-14-pr33-review-validation.md) | 当前本地未找到；保留当时验证陈述和来源，不声称本次复核了该目录 |
| /home/cloudia/FPGACHINA/worktrees/amd-agent-upload | 历史远端工作区路径 | 属于原机器位置，不能直接用于本机复现 |

这里只记录本机未找到，不能据此判断原证据已丢失。迁移证据时应保留来源和原运行编号，不用新跑的数据替换旧测量值。
