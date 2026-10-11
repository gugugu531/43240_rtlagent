# 20261011-155521-qwen3-1p7b-fp8-nothink-full34-9ebfce50

原始记录：`/home/alan/Learning/fpgachina2026/43240-agent/dev/runs/20261011-autodl-qwen3/20261011-155521-qwen3-1p7b-fp8-nothink-full34-9ebfce50`。

<!-- BEGIN:results -->
状态：completed。完成 34/34 个样本。

本文件由 dev/tools/run.py 生成，不要手改。逐样本证据见 samples/。

| 模式 | 样本 | 官方等级分布 |
| --- | ---: | --- |
| agent | 34 | {'L0': 26, 'L1': 5, 'L3': 3} |
<!-- END:results -->

## 改动与假设

使用 `Qwen/Qwen3-1.7B-FP8`（revision `1641e6c1b620b7ed7e8711b443990429a23b1b99`）的非思考模式，保留完整模型调用、提取、运行和判定记录。在统一 34 题上比较单次生成结果，保持原始 baseline 的 8192 token 请求配置和代码提取。采用单 GPU、求解并发 1；24 GB PyTorch 分配预算、28 GB 整卡提前停止阈值，用户上限为十进制 32 GB。

## 结论

完成 34 题，L3 全阶段通过 3 题；官方等级系数平均值 0.1176。该平均值不是通过率，也不是 pass@5。观测显存峰值 5.490 GB，请求耗时合计 84.6 秒。判定环境错误 0 个。

请求符合对应实验配置 34/34；生成代码与 baseline 提取结果逐字节一致 34/34。失败分类：`{"compile_or_elaboration_failed": 26, "passed_all_stages": 3, "simulation_failed": 5}`。

横向比较、服务启动失败、量化内核处理与后续方向见[本轮汇总](../notes/2026-10-11-autodl-qwen3-results.md)。原始日志保留在本页顶部运行目录，额外服务、资源、下载日志与完整备份在本次聊天 outputs/autodl-qwen3。
