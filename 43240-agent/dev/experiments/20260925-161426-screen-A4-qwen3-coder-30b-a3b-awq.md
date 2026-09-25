# 20260925-161426-screen-A4-qwen3-coder-30b-a3b-awq

| 项 | 值 |
| --- | --- |
| 类型 | run_eval |
| 时间 | 2026-09-25 16:14:26 |
| git commit | `1171f53` |
| 模型 | Qwen3-Coder-30B-A3B-AWQ |
| 参数 | `--tag screen-A4-qwen3-coder-30b-a3b-awq --modes baseline --jobs 4 --judge-jobs 4 --metrics-url http://127.0.0.1:18000/v1` |
| 原始文件 | `dev/runs/20260925-161426-screen-A4-qwen3-coder-30b-a3b-awq/` |

## 结果

| 模式 | 题数 | 题集得分 (pass@1) | pass@5 | 等级分布 | 环境失败 |
| --- | ---: | ---: | ---: | --- | ---: |
| baseline | 155/155 | 0.564 | 0.564 | {'L0': 18, 'L1': 62, 'L3': 75} | 0 |


## 失败原因分析（analyze.py 自动生成）

### baseline

样本 155 个，其中计分 155 个。

| 原因 | 样本数 | 例子 |
| --- | ---: | --- |
| L3 通过 | 75 | Prob001_zero, Prob002_m2014_q4i, Prob003_step_one, Prob004_vector2, Prob005_notgate |
| L1：仿真结果与参考实现不一致 | 62 | Prob016_m2014_q4j, Prob021_mux256to1v, Prob034_dff8, Prob045_edgedetect2, Prob050_kmap1 |
| L0：语法分析（xvlog）失败 | 13 | Prob023_vector100r, Prob026_alwaysblock1, Prob031_dff, Prob039_always_if, Prob042_vector4 |
| L0：详细描述（xelab）失败，非接口问题 | 4 | Prob030_popcount255, Prob078_dualedge, Prob092_gatesv100, ex01_popcount8 |
| L0：模型请求失败 | 1 | Prob057_kmap2 |

按题型（按题面关键词粗分（tasksets/categories.tsv），只用于看哪类题失败多）：

| 题型 | 题数 | pass@1 | 主要原因 |
| --- | ---: | ---: | --- |
| 卡诺图、真值表 | 8 | 0.275 | sim_mismatch 6, llm_error 1, pass 1 |
| 根据仿真波形推逻辑 | 12 | 0.300 | sim_mismatch 8, pass 2, syntax 2 |
| 状态机 | 39 | 0.349 | sim_mismatch 28, pass 8, syntax 3 |
| 其他时序电路（触发器、边沿检测等） | 18 | 0.456 | pass 7, sim_mismatch 6, syntax 4 |
| 改错题 | 3 | 0.733 | pass 2, sim_mismatch 1 |
| 移位寄存器、LFSR、元胞自动机 | 10 | 0.760 | pass 7, sim_mismatch 3 |
| 组合逻辑 | 57 | 0.765 | pass 42, sim_mismatch 8, syntax 4 |
| 计数器、定时器 | 8 | 0.800 | pass 6, sim_mismatch 2 |

模型调用：平均每个样本 1.0 次，输入 262 token，输出 246 token（最多 3951）；被截断的样本 0 个，请求失败的样本 1 个。
求解耗时：合计 1903.8 s，平均 12.3 s，中位数 6.5 s，90% 分位 21.5 s，最长 300.6 s。并行运行时各样本互相影响，只作相对比较。
Vivado 报错编号（L0 和综合失败的样本）：`VRFC 10-8530` × 12, `VRFC 10-1280` × 7, `VRFC 10-4982` × 4, `XSIM 43-4286` × 2, `XSIM 43-3322` × 2, `VRFC 10-8549` × 2, `VRFC 10-2989` × 2, `VRFC 10-3823` × 1, `VRFC 10-1219` × 1, `VRFC 10-792` × 1, `VRFC 10-1093` × 1, `VRFC 10-9195` × 1, `VRFC 10-395` × 1, `VRFC 10-845` × 1

## 资源与速度指标（metrics.py 自动生成）

求解并发：4。并发行测得的 tps 只作相对比较，单路速率用 `metrics.py probe`。

### baseline

| 指标 | 值 |
| --- | ---: |
| 样本数 | 155（155 题） |
| 单题耗时 均值 / 中位数 / p90 / 最长 | 12.3 / 6.5 / 21.5 / 300.6 s |
| 单题耗时合计 | 1904 s |
| tps（每次调用）中位数 / 均值 / p10 | 24.10 / 24.25 / 20.95 |
| tps（按题取中位数再平均） | 24.25 |
| tps（聚合：总输出 token ÷ 总生成时间） | 25.25 |
| token 输入/输出 合计 | 40666 / 38150 |
| 每题模型调用次数 均值 | 1.00 |
| 每题轮数 均值 / 最多 | 0.00 / 0 |
| 输出被截断 | 0（0.0%） |
| 空回复 | 0 |
| 模型请求失败 | 1 |
| 求解超时 | 0 |

服务端 /metrics（跑分期间轮询）

- KV Cache 使用率峰值 0.0991、中位数 0.0153
- 同时在跑的请求数峰值 5.0
- 服务端计数的生成 token 46342.0、输入 token 40872.0
- 共采样 136 次

## 改动与假设

A4-qwen3-coder-30b-a3b-awq 的全题集（155 题）baseline 筛选，**只跑 baseline**。量化方式与服务参数（`max_model_len`、`gpu_memory_utilization`、思考开关）见 [`../notes/2026-09-25-screening-results.md`](../notes/2026-09-25-screening-results.md) 里对应批次表。预期：得到该模型一次性裸跑（temperature 0、单次、不重试）的题集得分 `S_b`，用于和同批候选比较。

## 结论

`S_b` = **0.564**，等级分布 L0/L1/L2/L3 = 18/62/0/75（可综合率 0.484）。单题耗时中位 6.47 s、p90 21.5 s；模型请求失败 1 次、输出截断 0 次。
失败原因分布见本记录下一节；横向对比与选型影响见 [`../notes/2026-09-25-screening-results.md`](../notes/2026-09-25-screening-results.md)。
