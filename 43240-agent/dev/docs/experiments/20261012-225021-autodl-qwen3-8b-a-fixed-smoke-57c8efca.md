# 20261012-225021-autodl-qwen3-8b-a-fixed-smoke-57c8efca

原始记录：`/home/cloudia/FPGACHINA/AMD_SocChina_2026/43240-agent/dev/runs/20261012-225021-autodl-qwen3-8b-a-fixed-smoke-57c8efca`。

<!-- BEGIN:results -->
状态：completed。完成 2/2 个样本。

本文件由 dev/tools/run.py 生成，不要手改。逐样本证据见 samples/。

| 模式 | 样本 | 官方等级分布 |
| --- | ---: | --- |
| agent | 1 | {'L3': 1} |
| baseline | 1 | {'L3': 1} |
<!-- END:results -->

## 改动与假设

验证连接恢复、Vivado 错误分类、候选保留与参数对齐后的端到端链路。
同一个自托管 Qwen3-8B 服务，`evidence_repair` 与原始 baseline 均使用
temperature 0、top_p 1、max_tokens 8192、模型请求上限 300 秒；串行求解与评分。
题目为 `ex03_lfsr8`，未向求解流程提供官方 testbench 或参考答案。

## 结论

两个样本均为 L3，模型调用失败和判定工具错误均为 0；
`summary.json` 中 `full_comparison_valid=true`。这只说明链路通过 smoke，
不能由一道题推断方案效果。随后启动完整 quick-34：
[正式实验](20261012-225403-autodl-qwen3-8b-a-fixed-quick34-460c1d2a.md)。

运行时段为 2026-10-12 22:50:21—22:54:03（东京时间）。Agent 求解用时
121.59 秒，baseline 53.01 秒；该时间不包含后续官方评分。
