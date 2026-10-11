# 20261011-161532-qwen3-coder-30b-a3b-instruct-awq-nothink-full34-98a8eb93

原始记录：`/home/alan/Learning/fpgachina2026/43240-agent/dev/runs/20261011-autodl-qwen3/20261011-161532-qwen3-coder-30b-a3b-instruct-awq-nothink-full34-98a8eb93`。

<!-- BEGIN:results -->
状态：completed。完成 34/34 个样本。

本文件由 dev/tools/run.py 生成，不要手改。逐样本证据见 samples/。

| 模式 | 样本 | 官方等级分布 |
| --- | ---: | --- |
| agent | 34 | {'L0': 6, 'L1': 10, 'L3': 18} |
<!-- END:results -->

## 改动与假设

使用 `QuantTrio/Qwen3-Coder-30B-A3B-Instruct-AWQ`（revision `c58857a7f41c0920f73d1b56678640f9c02017d7`）的非思考模式，保留完整模型调用、提取、运行和判定记录。在统一 34 题上比较单次生成结果，保持原始 baseline 的 8192 token 请求配置和代码提取。采用单 GPU、求解并发 1；24 GB PyTorch 分配预算、28 GB 整卡提前停止阈值，用户上限为十进制 32 GB。

## 结论

完成 34 题，L3 全阶段通过 18 题；官方等级系数平均值 0.5882。该平均值不是通过率，也不是 pass@5。观测显存峰值 22.521 GB，请求耗时合计 221.0 秒。判定环境错误 0 个。

请求符合对应实验配置 34/34；生成代码与 baseline 提取结果逐字节一致 34/34。失败分类：`{"passed_all_stages": 18, "compile_or_elaboration_failed": 6, "simulation_failed": 10}`。

横向比较、服务启动失败、量化内核处理与后续方向见[本轮汇总](../notes/2026-10-11-autodl-qwen3-results.md)。原始日志保留在本页顶部运行目录，额外服务、资源、下载日志与完整备份在本次聊天 outputs/autodl-qwen3。
