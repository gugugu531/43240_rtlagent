# 五题 thinking / 采样诊断结果

由 `dev/tools/generation_sweep.py run <会话目录>` 生成，不要手改。
状态：incomplete。原始会话：`/home/cloudia/FPGACHINA/AMD_SocChina_2026/43240-agent/dev/runs/20261013-generation-diagnostic-five`。

每组 5 题、双方各 1 样本；固定各自提示、8192 输出 tokens、300 秒单次上限、360 秒总预算。
采样组覆盖了官方 baseline 的参数，属于开发对照，不是官方固定采样成绩。

| 设置 | 模式 | L0/L1/L2/L3 | 系数均值 | 截断/调用 | 输出 tokens | 求解秒 |
| --- | --- | --- | ---: | ---: | ---: | ---: |

生成设置的实际值与逐调用完整 RTL/思考截断分类见各组 audit-summary.json。
思考开关比较前两组；采样配方比较第一与第三组。不是 temperature 单因素实验。
选题基于先前失败，且每组仅 1 个样本，不支持整体提升或稳定性结论；不替换旧 quick-34 结果。
