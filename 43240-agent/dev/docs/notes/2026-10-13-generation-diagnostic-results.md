# 五题生成设置诊断：完成记录与下一步

类型：实验结论。日期：2026-10-13。状态：三组全部完成，未启动 11 题实验。

机器生成的完整数字与逐题表见[三组结果](../experiments/20261013-generation-diagnostic-five-retry1.md)。
原始会话：`dev/runs/20261013-generation-diagnostic-five-retry1/`；三个独立运行：

- `20261013-115236-gen5-think-on-greedy-24d4216d`
- `20261013-121713-gen5-think-off-greedy-44fc31c5`
- `20261013-122011-gen5-think-on-sampled-f8fa80f3`

## 结果与解释

三组共 30/30 个有效配对样本，全部 `full_comparison_valid=true`；
同一题同一模式的首次 messages 哈希跨组三次一致，正式求解源码和题面哈希核对通过。
实际参数与原始/实际请求、响应原文均已留档；网关传输重试额外次数为 0。
本次总共 34 次模型请求，全部取得响应；追加生成/修复仍按原 workflow 规则决定。

| 设置 | Agent L0/L1/L3 | Agent 系数均值 | baseline 系数均值 | Agent 截断/调用 | Agent 求解秒 |
| --- | --- | ---: | ---: | ---: | ---: |
| thinking 开、temperature 0 / top_p 1 | 3/1/1 | 0.24 | 0.60 | 5/8 | 956.57 |
| thinking 关、temperature 0 / top_p 1 | 0/5/0 | 0.20 | 0.12 | 0/6 | 146.13 |
| thinking 开、temperature 0.6 / top_p 0.95 / top_k 20 / min_p 0 | 0/2/3 | 0.68 | 0.52 | 0/5 | 594.78 |

各组均为 seed=20261013，输出上限每次 8192 tokens，模型、提示、请求上限和单题预算保持固定。
采样组比较的是整套采样配方，并非 temperature 单独消融；基线文件不变，但实际采样被开发网关覆盖，
因此不能声称为官方固定 baseline 参数下的成绩。

初步判断：

1. 推荐采样是下一轮优先验证的候选设置。Agent 的 Prob109_fsm1、Prob115_shift18 从本轮 greedy 的 L0
   到 L3；Prob138 从 L0 到 L1；Prob101 保持 L3，Prob105 保持 L1。
   相比本轮 greedy，Agent 没有截断、少了追加调用，求解时间与输出 tokens 都下降。
2. 关闭 thinking 很快且消除了 Agent 的 L0，但五题均停在 L1，说明完整代码不等于功能正确。
   baseline 成绩也大幅下降，不能只因 Agent/baseline 比值上升就采用该设置。
3. 新 greedy 的 Prob101 已是 L3，而旧 quick-34 中是 L0，说明旧失败不一定复现。
   必须比较本轮同时对照，并做重复测量，不能把历史差异全归因于新设置。
4. 采样组 Agent 仍有两道 L1：Prob105_rotate100、Prob138_2012_q2fsm。
   编译/综合反馈无法直接指出这些功能错误；不能用官方 TB/judge 指导正式求解。
5. 五题按历史退步结果选出，每组仅一次测量。0.68 不是 quick-34 或完整 VerilogEval 的成绩，
   也不是已经证明的稳定提升；baseline 在新采样下也不是逐题都更好。

## 收尾与后续

整轮于 2026-10-13 12:38:48 JST 完成，12:38:51 模型停止、12:38:52 隧道关闭。
再次 SSH 核实 GPU 显存 0 MiB、利用率 0%，无 vLLM 服务进程；远端保护已撤销，
本地实验、网关、transport、阻止休眠服务及两项保护定时器均已停止。
这只释放推理资源，AutoDL 平台实例并未由脚本关机，仍需用户在网页确认计费状态。

已准备[11 题固定开发诊断集](2026-10-13-diagnostic-eleven-plan.md)，只完成离线选题与配置验证。
建议先在这 11 题上验证 thinking/推荐采样是否保住历史优势题和稳定题，再做预先指定 seed 的重复。
共享网关目前 seed 固定；需补齐显式 seed 配置才能进行不同 seed 的重复，不能把 samples=3 当作三个独立 seed。
本轮不继续自动启动 GPU、E1、E2 或 Ross 示例。
