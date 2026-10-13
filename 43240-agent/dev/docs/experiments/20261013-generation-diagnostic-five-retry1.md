# 五题 thinking / 采样诊断结果

由 `dev/tools/generation_sweep.py run <会话目录>` 生成，不要手改。
状态：completed。原始会话：`/home/cloudia/FPGACHINA/AMD_SocChina_2026/43240-agent/dev/runs/20261013-generation-diagnostic-five-retry1`。

每组 5 题、双方各 1 样本；固定各自提示、8192 输出 tokens、300 秒单次上限、360 秒总预算。
采样组覆盖了官方 baseline 的参数，属于开发对照，不是官方固定采样成绩。

| 设置 | 模式 | L0/L1/L2/L3 | 系数均值 | 截断/调用 | 输出 tokens | 求解秒 |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| think-on-greedy | agent | 3/1/0/1 | 0.2400 | 5/8 | 48826 | 956.57 |
| think-on-greedy | baseline | 2/0/0/3 | 0.6000 | 2/5 | 25783 | 474.19 |
| think-off-greedy | agent | 0/5/0/0 | 0.2000 | 0/6 | 1929 | 146.13 |
| think-off-greedy | baseline | 2/3/0/0 | 0.1200 | 0/5 | 1168 | 28.21 |
| think-on-sampled | agent | 0/2/0/3 | 0.6800 | 0/5 | 26258 | 594.78 |
| think-on-sampled | baseline | 0/3/0/2 | 0.5200 | 1/5 | 27715 | 513.88 |

| 模式/题目 | think-on-greedy | think-off-greedy | think-on-sampled |
| --- | --- | --- | --- |
| agent/Prob101_circuit4 | L3 | L1 | L3 |
| agent/Prob105_rotate100 | L1 | L1 | L1 |
| agent/Prob109_fsm1 | L0 | L1 | L3 |
| agent/Prob115_shift18 | L0 | L1 | L3 |
| agent/Prob138_2012_q2fsm | L0 | L1 | L1 |
| baseline/Prob101_circuit4 | L3 | L1 | L1 |
| baseline/Prob105_rotate100 | L0 | L1 | L3 |
| baseline/Prob109_fsm1 | L3 | L0 | L3 |
| baseline/Prob115_shift18 | L0 | L1 | L1 |
| baseline/Prob138_2012_q2fsm | L3 | L0 | L1 |

生成设置的实际值与逐调用完整 RTL/思考截断分类见各组 audit-summary.json。
思考开关比较前两组；采样配方比较第一与第三组。不是 temperature 单因素实验。
选题基于先前失败，且每组仅 1 个样本，不支持整体提升或稳定性结论；不替换旧 quick-34 结果。
