# 11 题 thinking / 采样诊断结果

由 `dev/tools/generation_sweep.py run <会话目录>` 生成，不要手改。
状态：incomplete。原始会话：`/home/cloudia/FPGACHINA/AMD_SocChina_2026/43240-agent/dev/runs/20261013-generation-diagnostic-eleven`。

已完整汇总 22/44 次求解；当前设置：think-on-sampled。在途组的部分成绩尚未计入本表。
每组 11 题、双方各 1 样本；固定各自提示、8192 输出 tokens、300 秒单次上限、360 秒总预算。
采样组覆盖了官方 baseline 的参数，属于开发对照，不是官方固定采样成绩。

| 设置 | 模式 | L0/L1/L2/L3 | 系数均值 | 截断/调用 | 输出 tokens | 求解秒 |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| think-on-greedy | agent | 6/1/0/4 | 0.3818 | 7/19 | 75748 | 1594.99 |
| think-on-greedy | baseline | 5/1/0/5 | 0.4727 | 2/11 | 38157 | 700.18 |

| 模式/题目 | think-on-greedy |
| --- | --- |
| agent/Prob017_mux2to1v | L3 |
| agent/Prob026_alwaysblock1 | L3 |
| agent/Prob041_dff8r | L3 |
| agent/Prob043_vector5 | L0 |
| agent/Prob048_m2014_q4c | L0 |
| agent/Prob058_alwaysblock2 | L0 |
| agent/Prob101_circuit4 | L3 |
| agent/Prob105_rotate100 | L1 |
| agent/Prob109_fsm1 | L0 |
| agent/Prob115_shift18 | L0 |
| agent/Prob138_2012_q2fsm | L0 |
| baseline/Prob017_mux2to1v | L3 |
| baseline/Prob026_alwaysblock1 | L0 |
| baseline/Prob041_dff8r | L3 |
| baseline/Prob043_vector5 | L1 |
| baseline/Prob048_m2014_q4c | L0 |
| baseline/Prob058_alwaysblock2 | L0 |
| baseline/Prob101_circuit4 | L3 |
| baseline/Prob105_rotate100 | L0 |
| baseline/Prob109_fsm1 | L3 |
| baseline/Prob115_shift18 | L0 |
| baseline/Prob138_2012_q2fsm | L3 |

生成设置的实际值与逐调用完整 RTL/思考截断分类见各组 audit-summary.json。
开/关 thinking 应比较同一采样下的 on/off 组；采样配方比较 think-on-greedy 与 think-on-sampled，不是 temperature 单因素实验。
选题基于先前失败，且每组仅 1 个样本，不支持整体提升或稳定性结论；不替换旧 quick-34 结果。
