> 2026-10-14 整理补注：以下保留当时记录与测量值。旧得分、pass@5 和比较范围见[指标说明](../design/experiment-reading.md)。 原人工假设与结论未补录，本次保留空白，不从自动结果倒推假设；同批背景见[筛选汇总](../notes/2026-09-25-screening-results.md)。

# 20260928-073818-b-layer-ministral3-14b-awq4

| 项 | 值 |
| --- | --- |
| 类型 | run_eval |
| 时间 | 2026-09-28 07:38:18 |
| git commit | `4ef5aed` |
| 模型 | Ministral-3-14B-AWQ-4bit |
| 参数 | `--tag b-layer-ministral3-14b-awq4 --modes baseline --jobs 4 --judge-jobs 4 --metrics-url http://127.0.0.1:18000/v1` |
| 原始文件 | `dev/runs/20260928-073818-b-layer-ministral3-14b-awq4/` |

## 结果

| 模式 | 题数 | 题集得分 (pass@1) | pass@5 | 等级分布 | 环境失败 |
| --- | ---: | ---: | ---: | --- | ---: |
| baseline | 155/155 | 0.476 | 0.476 | {'L0': 42, 'L1': 49, 'L3': 64} | 0 |


## 失败原因分析（analyze.py 自动生成）

### baseline

样本 155 个，其中计分 155 个。

| 原因 | 样本数 | 例子 |
| --- | ---: | --- |
| L3 通过 | 64 | Prob001_zero, Prob002_m2014_q4i, Prob003_step_one, Prob005_notgate, Prob007_wire |
| L1：仿真结果与参考实现不一致 | 48 | Prob028_m2014_q4a, Prob034_dff8, Prob040_count10, Prob041_dff8r, Prob048_m2014_q4c |
| L0：语法分析（xvlog）失败 | 27 | Prob004_vector2, Prob006_vectorr, Prob009_popcount3, Prob016_m2014_q4j, Prob021_mux256to1v |
| L0：详细描述（xelab）失败，非接口问题 | 15 | Prob067_countslow, Prob089_ece241_2014_q5a, Prob095_review2015_fsmshift, Prob096_review2015_fsmseq, Prob124_rule110 |
| L1：仿真没有产生比对结果 | 1 | Prob139_2013_q2bfsm |

按题型（按题面关键词粗分（tasksets/categories.tsv），只用于看哪类题失败多）：

| 题型 | 题数 | pass@1 | 主要原因 |
| --- | ---: | ---: | --- |
| 状态机 | 39 | 0.231 | sim_mismatch 14, elab 13, pass 6 |
| 卡诺图、真值表 | 8 | 0.275 | sim_mismatch 6, syntax 1, pass 1 |
| 改错题 | 3 | 0.400 | sim_mismatch 1, syntax 1, pass 1 |
| 计数器、定时器 | 8 | 0.450 | pass 3, sim_mismatch 3, syntax 1 |
| 根据仿真波形推逻辑 | 12 | 0.450 | sim_mismatch 7, pass 4, syntax 1 |
| 其他时序电路（触发器、边沿检测等） | 18 | 0.478 | sim_mismatch 8, pass 7, syntax 2 |
| 移位寄存器、LFSR、元胞自动机 | 10 | 0.500 | sim_mismatch 5, pass 4, syntax 1 |
| 组合逻辑 | 57 | 0.681 | pass 38, syntax 15, sim_mismatch 4 |

模型调用：平均每个样本 1.0 次，输入 262 token，输出 212 token（最多 1904）；被截断的样本 0 个，请求失败的样本 0 个。
求解耗时：合计 718.0 s，平均 4.6 s，中位数 3.4 s，90% 分位 8.6 s，最长 32.8 s。并行运行时各样本互相影响，只作相对比较。
Vivado 报错编号（L0 和综合失败的样本）：`VRFC 10-8530` × 25, `VRFC 10-1280` × 18, `XSIM 43-3322` × 15, `VRFC 10-3818` × 9, `VRFC 10-4982` × 7, `VRFC 10-3823` × 3, `VRFC 10-8928` × 3, `VRFC 10-8549` × 2, `VRFC 10-1775` × 1, `VRFC 10-2951` × 1, `VRFC 10-1304` × 1, `VRFC 10-3279` × 1, `VRFC 10-3380` × 1, `VRFC 10-3149` × 1

## 资源与速度指标（metrics.py 自动生成）

求解并发：4。并发行测得的 tps 只作相对比较，单路速率用 `metrics.py probe`。

### baseline

| 指标 | 值 |
| --- | ---: |
| 样本数 | 155（155 题） |
| 单题耗时 均值 / 中位数 / p90 / 最长 | 4.6 / 3.4 / 8.6 / 32.8 s |
| 单题耗时合计 | 718 s |
| tps（每次调用）中位数 / 均值 / p10 | 48.68 / 47.10 / 36.36 |
| tps（按题取中位数再平均） | 47.10 |
| tps（聚合：总输出 token ÷ 总生成时间） | 51.31 |
| token 输入/输出 合计 | 40659 / 32840 |
| 每题模型调用次数 均值 | 1.00 |
| 每题轮数 均值 / 最多 | 0.00 / 0 |
| 输出被截断 | 0（0.0%） |
| 空回复 | 0 |
| 模型请求失败 | 0 |
| 求解超时 | 0 |

服务端 /metrics（跑分期间轮询）

- KV Cache 使用率峰值 0.0242、中位数 0.0
- 同时在跑的请求数峰值 4.0
- 服务端计数的生成 token 32840.0、输入 token 40659.0
- 共采样 120 次

## 改动与假设

TODO：这一轮相对上一轮改了什么、预期效果

## 结论

TODO：结果是否符合预期；失败原因分析写在 dev/docs/notes/
