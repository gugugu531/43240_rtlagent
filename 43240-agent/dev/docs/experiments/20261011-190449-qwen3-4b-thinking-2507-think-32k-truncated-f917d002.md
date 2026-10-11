# 20261011-190449-qwen3-4b-thinking-2507-think-32k-truncated-f917d002

原始记录：`/home/alan/Learning/fpgachina2026/43240-agent/dev/runs/20261011-autodl-qwen3/20261011-190449-qwen3-4b-thinking-2507-think-32k-truncated-f917d002`。

<!-- BEGIN:results -->
状态：completed。完成 7/7 个样本。

本文件由 dev/tools/run.py 生成，不要手改。逐样本证据见 samples/。

| 模式 | 样本 | 官方等级分布 |
| --- | ---: | --- |
| agent | 7 | {'L0': 3, 'L1': 4} |
<!-- END:results -->

## 改动与假设

使用 `Qwen/Qwen3-4B-Thinking-2507`（revision `768f209d9ea81521153ed38c47d515654e938aea`）的思考模式，保留完整模型调用、提取、运行和判定记录。只补测 `20261011-162201-qwen3-4b-thinking-2507-think-full34-168e9695` 实际达到长度上限的题目，使用独立长输出 Workflow，将 max_tokens 从 8192 提高到 32768；题面、系统提示、temperature=0、top_p=1 和提取规则不变。请求超时 900 秒、整题 960 秒；服务上下文 36864，KV cache 6,000,000,000 字节。采用单 GPU、求解并发 1；24 GB PyTorch 分配预算、28 GB 整卡提前停止阈值，用户上限为十进制 32 GB。

## 结论

完成 7 题，L3 全阶段通过 0 题；官方等级系数平均值 0.1143。该平均值不是通过率，也不是 pass@5。观测显存峰值 15.529 GB，请求耗时合计 999.2 秒。判定环境错误 0 个。

请求符合对应实验配置 7/7；生成代码与 baseline 提取结果逐字节一致 7/7。失败分类：`{"simulation_failed": 4, "compile_or_elaboration_failed": 3}`。

本次仅测原先截断的子集，不能直接与完整 34 题得分比较，也不能拼接成完整题集的一次生成成绩。前后逐题结果、推理前缀一致性、token 与时间开销见汇总证据。

横向比较、服务启动失败、量化内核处理与后续方向见[本轮汇总](../notes/2026-10-11-autodl-qwen3-results.md)。原始日志保留在本页顶部运行目录，额外服务、资源、下载日志与完整备份在本次聊天 outputs/autodl-qwen3。
