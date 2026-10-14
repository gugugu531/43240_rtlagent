> 2026-10-14 整理补注：以下保留当时记录与测量值。旧得分、pass@5 和比较范围见[指标说明](../design/experiment-reading.md)。 原人工假设与结论未补录，本次保留空白，不从自动结果倒推假设；同批背景见[筛选汇总](../notes/2026-09-25-screening-results.md)。

# 20260927-152225-screen-gpt-oss-20b-default

| 项 | 值 |
| --- | --- |
| 类型 | run_eval |
| 时间 | 2026-09-27 15:22:25 |
| git commit | `bf99e29` |
| 模型 | gpt-oss-20b |
| 参数 | `--tag screen-gpt-oss-20b-default --modes baseline --jobs 4 --judge-jobs 4 --metrics-url http://127.0.0.1:18000/v1` |
| 原始文件 | `dev/runs/20260927-152225-screen-gpt-oss-20b-default/` |

## 结果

| 模式 | 题数 | 题集得分 (pass@1) | pass@5 | 等级分布 | 环境失败 |
| --- | ---: | ---: | ---: | --- | ---: |
| baseline | 155/155 | 0.689 | 0.689 | {'L0': 33, 'L1': 19, 'L3': 103} | 0 |


## 失败原因分析（analyze.py 自动生成）

### baseline

样本 155 个，其中计分 155 个。

| 原因 | 样本数 | 例子 |
| --- | ---: | --- |
| L3 通过 | 103 | Prob001_zero, Prob003_step_one, Prob004_vector2, Prob005_notgate, Prob006_vectorr |
| L0：模型请求失败 | 22 | Prob002_m2014_q4i, Prob057_kmap2, Prob070_ece241_2013_q2, Prob078_dualedge, Prob086_lfsr5 |
| L1：仿真结果与参考实现不一致 | 19 | Prob034_dff8, Prob045_edgedetect2, Prob053_m2014_q4d, Prob054_edgedetect, Prob062_bugs_mux2 |
| L0：详细描述（xelab）失败，非接口问题 | 4 | Prob074_ece241_2014_q4, Prob117_circuit9, Prob137_fsm_serial, Prob142_lemmings2 |
| L0：模型回复内容为空 | 4 | Prob147_circuit10, Prob149_ece241_2013_q4, Prob150_review2015_fsmonehot, Prob151_review2015_fsm |
| L0：语法分析（xvlog）失败 | 2 | Prob042_vector4, Prob115_shift18 |
| L0：模块名或端口与测试台不符 | 1 | Prob131_mt2015_q4 |

按题型（按题面关键词粗分（tasksets/categories.tsv），只用于看哪类题失败多）：

| 题型 | 题数 | pass@1 | 主要原因 |
| --- | ---: | ---: | --- |
| 卡诺图、真值表 | 8 | 0.400 | llm_error 4, pass 3, sim_mismatch 1 |
| 根据仿真波形推逻辑 | 12 | 0.450 | pass 5, llm_error 2, sim_mismatch 2 |
| 状态机 | 39 | 0.477 | pass 17, llm_error 9, sim_mismatch 8 |
| 其他时序电路（触发器、边沿检测等） | 18 | 0.567 | pass 9, sim_mismatch 6, llm_error 2 |
| 移位寄存器、LFSR、元胞自动机 | 10 | 0.700 | pass 7, llm_error 2, syntax 1 |
| 改错题 | 3 | 0.733 | pass 2, sim_mismatch 1 |
| 组合逻辑 | 57 | 0.916 | pass 52, llm_error 3, syntax 1 |
| 计数器、定时器 | 8 | 1.000 | pass 8 |

模型调用：平均每个样本 1.0 次，输入 255 token，输出 678 token（最多 3987）；被截断的样本 0 个，请求失败的样本 22 个。
求解耗时：合计 12480.7 s，平均 80.5 s，中位数 42.5 s，90% 分位 237.2 s，最长 300.8 s。并行运行时各样本互相影响，只作相对比较。
Vivado 报错编号（L0 和综合失败的样本）：`XSIM 43-3322` × 5, `VRFC 10-3818` × 4, `VRFC 10-4982` × 2, `VRFC 10-8530` × 2, `VRFC 10-2063` × 1

## 资源与速度指标（metrics.py 自动生成）

求解并发：4。并发行测得的 tps 只作相对比较，单路速率用 `metrics.py probe`。

### baseline

| 指标 | 值 |
| --- | ---: |
| 样本数 | 155（155 题） |
| 单题耗时 均值 / 中位数 / p90 / 最长 | 80.5 / 42.5 / 237.2 / 300.8 s |
| 单题耗时合计 | 12481 s |
| tps（每次调用）中位数 / 均值 / p10 | 11.48 / 12.91 / 7.95 |
| tps（按题取中位数再平均） | 12.91 |
| tps（聚合：总输出 token ÷ 总生成时间） | 13.32 |
| token 输入/输出 合计 | 39554 / 105087 |
| 每题模型调用次数 均值 | 1.00 |
| 每题轮数 均值 / 最多 | 0.00 / 0 |
| 输出被截断 | 0（0.0%） |
| 空回复 | 4 |
| 模型请求失败 | 22 |
| 求解超时 | 0 |

服务端 /metrics（跑分期间轮询）

- KV Cache 使用率峰值 0.0827、中位数 0.0245
- 同时在跑的请求数峰值 7.0
- 服务端计数的生成 token 201520.0、输入 token 45173.0
- 共采样 560 次

## 改动与假设

TODO：这一轮相对上一轮改了什么、预期效果

## 结论

TODO：结果是否符合预期；失败原因分析写在 dev/docs/notes/
