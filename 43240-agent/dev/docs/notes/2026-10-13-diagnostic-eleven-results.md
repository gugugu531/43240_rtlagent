# 11 题生成参数诊断：补跑完成与结论

类型：实验结论。日期：2026-10-13。状态：44/44 次有效评分完成，模型已停止。

完整机器生成数据与逐题等级见[合并后的报告](../experiments/20261013-generation-diagnostic-eleven-resume1.md)。
旧会话仍为 incomplete，未覆盖；第一组完整 22 项、第二组 19 项有效结果保留，
仅补 `Prob043_vector5/baseline` 与 `Prob058_alwaysblock2/agent,baseline` 三项取消样本。
第二组摘要是跨中断的 19+3 项派生汇总，不是重新连续执行全部 22 项。

原始记录：

- 原会话：`dev/runs/20261013-generation-diagnostic-eleven`。
- 第一组：`dev/runs/20261013-130343-gen11-think-on-greedy-cf560ace`。
- 第二组原记录：`dev/runs/20261013-140530-gen11-think-on-sampled-f2835de9`。
- 补跑：`dev/runs/20261013-144415-gen11-think-on-sampled-resume-eff670fa`。
- 恢复会话、合并与逐样本来源：`dev/runs/20261013-generation-diagnostic-eleven-resume1/` 下
  `state.json`、`combined-sampled/summary.json`、`metrics.json`、`provenance.json`。

## 测量结果

| 设置 | Agent L0/L1/L2/L3 | Agent 系数均值 | baseline 系数均值 | Agent 截断/调用 | Agent 输出 tokens | Agent 求解秒合计 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| thinking 开，greedy | 6/1/0/4 | 0.3818 | 0.4727 | 7/19 | 75748 | 1594.99 |
| thinking 开，推荐采样 | 1/2/0/8 | 0.7636 | 0.4364 | 0/15 | 43766 | 1037.94 |

两组相同模型、各自首次提示、seed=20261013、单次 8192 输出上限、300 秒单次上限、
360 秒单题预算及 20 秒预留；推荐采样为 temperature=0.6、top_p=0.95、top_k=20、min_p=0。
此轮是整套采样配方对照，不是 temperature 单因素，也没有新增 thinking-off 对照。

推荐采样相对本轮 greedy 的 Agent：6 题等级改善、1 题下降、4 题不变；
L3 从 4/11 到 8/11，输出 tokens 下降约 42.2%，求解秒合计下降约 34.9%。
这些是本次记录的求解成本，不是云端开机总时长或含中断等待的端到端耗时。

推荐采样内 Agent 相对 baseline 为 5 胜、1 负、5 平；系数均值分别 0.7636 / 0.4364。
baseline 自身从 greedy 的 0.4727 降到 0.4364，说明收益不应泛化为“所有提示都更好”。
实际 baseline 采样同样由开发网关覆盖，不是官方固定采样成绩。

## 剩余问题与实验优先级

1. `Prob026_alwaysblock1`：Agent 从本轮 greedy 的 L3 降为 L0。首份报 VRFC 10-1280，
   修复后报 ANSI 端口重复声明 VRFC 10-9336；这是工具可见的 RTL 错误，适合 E1 的反馈/修复对照。
   已有 procedural-variable 卡覆盖前一错误，后一错误目前未覆盖，不伪装成准确命中。
2. `Prob105_rotate100`、`Prob138_2012_q2fsm`：Agent 均为 L1，而自身编译和综合检查通过。
   只检索编译错误指南不会触发这两类功能缺陷。题面规格检查卡片应另开实验，不能使用隐藏 TB
   或 judge 来触发正式修复。
3. 参数层面已值得优先保留推荐采样作为下一阶段的开发基准候选，但每题只有一次，不能声称稳定。
   后续 seed 重复要事先声明、逐请求审计；不能看到结果后挑选最好 seed。

推荐[下一阶段顺序](2026-10-13-after-generation-experiment-order.md)：先冻结生成设置、
离线验收卡片，再做 E1 的“无修复 / 结构化修复 / 结构化修复+短卡片”三组；之后做 E2 两候选。
当前不自动启动这些新矩阵，不改正式默认配置或正在冻结的既有 workflow。

## 有效性、失败记录与收尾

两组 `full_comparison_valid=true`；正式源码、题面指纹一致，远端 9 个权重/配置/tokenizer
文件哈希及 vLLM/PyTorch 版本匹配，22 个首次 messages 哈希跨组一致。
原始 evidence_repair、baseline 和接口未改，只新增开发区取消样本恢复、审计与限时政策。

第一组 30 次已完成模型请求，网关额外传输重试 1 次；推荐采样组 26 次已完成请求，额外重试 0 次。
旧 timer 中断了另一条 baseline 请求，没有响应；保留在恢复会话的
`think-on-sampled/discarded-requests.json`，不伪造完成，也不混进已完成请求/输出统计。
这条被中断请求仍可能消耗远端推理时间，合并求解成本不含其废弃耗时。

14:48:44 JST 补跑与合并验证完成；14:48:45 vLLM 停止，14:48:49 隧道关闭。
14:49:29 JST 再次 SSH 确认显存 0 MiB、利用率 0%、无 vLLM 进程或远端 watchdog；
本地实验、inhibit、gateway、transport 均 inactive，无截止定时器。
本轮恢复/审计/合并 24 项离线测试通过，baseline/example 字节一致，shell 语法和 diff 空白检查通过。

今后整轮固定时长截止默认关闭；单题和单次请求预算、结束清理仍保留。
平台实例未由脚本关机，AutoDL 网页仍需确认计费状态。
11 题是按历史结果有意选择的开发集；不能替代 quick-34 回归，更不能冒充未见任务上的泛化提升。
