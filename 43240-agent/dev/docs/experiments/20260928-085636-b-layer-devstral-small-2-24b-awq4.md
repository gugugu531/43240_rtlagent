> 2026-10-14 整理补注：以下保留当时记录与测量值。旧得分、pass@5 和比较范围见[指标说明](../design/experiment-reading.md)。 原人工假设与结论未补录，本次保留空白，不从自动结果倒推假设；同批背景见[筛选汇总](../notes/2026-09-25-screening-results.md)。

# 20260928-085636-b-layer-devstral-small-2-24b-awq4

| 项 | 值 |
| --- | --- |
| 类型 | run_eval |
| 时间 | 2026-09-28 08:56:36 |
| git commit | `6fcd628` |
| 模型 | Devstral-Small-2-AWQ-4bit |
| 参数 | `--tag b-layer-devstral-small-2-24b-awq4 --modes baseline --jobs 4 --judge-jobs 4 --metrics-url http://127.0.0.1:18000/v1` |
| 原始文件 | `dev/runs/20260928-085636-b-layer-devstral-small-2-24b-awq4/` |

## 结果

| 模式 | 题数 | 题集得分 (pass@1) | pass@5 | 等级分布 | 环境失败 |
| --- | ---: | ---: | ---: | --- | ---: |
| baseline | 155/155 | 0.433 | 0.433 | {'L0': 47, 'L1': 51, 'L3': 57} | 0 |


## 失败原因分析（analyze.py 自动生成）

### baseline

样本 155 个，其中计分 155 个。

| 原因 | 样本数 | 例子 |
| --- | ---: | --- |
| L3 通过 | 57 | Prob001_zero, Prob002_m2014_q4i, Prob003_step_one, Prob005_notgate, Prob007_wire |
| L1：仿真结果与参考实现不一致 | 51 | Prob028_m2014_q4a, Prob034_dff8, Prob037_review2015_count1k, Prob041_dff8r, Prob046_dff8p |
| L0：语法分析（xvlog）失败 | 47 | Prob004_vector2, Prob006_vectorr, Prob009_popcount3, Prob021_mux256to1v, Prob023_vector100r |

按题型（按题面关键词粗分（tasksets/categories.tsv），只用于看哪类题失败多）：

| 题型 | 题数 | pass@1 | 主要原因 |
| --- | ---: | ---: | --- |
| 状态机 | 39 | 0.154 | sim_mismatch 20, syntax 17, pass 2 |
| 卡诺图、真值表 | 8 | 0.250 | sim_mismatch 5, syntax 2, pass 1 |
| 其他时序电路（触发器、边沿检测等） | 18 | 0.322 | sim_mismatch 9, syntax 5, pass 4 |
| 改错题 | 3 | 0.400 | sim_mismatch 1, syntax 1, pass 1 |
| 根据仿真波形推逻辑 | 12 | 0.400 | pass 4, sim_mismatch 4, syntax 4 |
| 移位寄存器、LFSR、元胞自动机 | 10 | 0.420 | sim_mismatch 6, pass 3, syntax 1 |
| 组合逻辑 | 57 | 0.660 | pass 37, syntax 17, sim_mismatch 3 |
| 计数器、定时器 | 8 | 0.700 | pass 5, sim_mismatch 3 |

模型调用：平均每个样本 1.0 次，输入 262 token，输出 343 token（最多 8192）；被截断的样本 2 个，请求失败的样本 0 个。
求解耗时：合计 1568.7 s，平均 10.1 s，中位数 4.6 s，90% 分位 13.7 s，最长 222.8 s。并行运行时各样本互相影响，只作相对比较。
Vivado 报错编号（L0 和综合失败的样本）：`VRFC 10-8530` × 41, `VRFC 10-1280` × 38, `VRFC 10-4982` × 6, `VRFC 10-1491` × 3, `VRFC 10-2989` × 2, `VRFC 10-1263` × 1, `VRFC 10-2649` × 1, `VRFC 10-2934` × 1

## 资源与速度指标（metrics.py 自动生成）

求解并发：4。并发行测得的 tps 只作相对比较，单路速率用 `metrics.py probe`。

### baseline

| 指标 | 值 |
| --- | ---: |
| 样本数 | 155（155 题） |
| 单题耗时 均值 / 中位数 / p90 / 最长 | 10.1 / 4.6 / 13.7 / 222.8 s |
| 单题耗时合计 | 1569 s |
| tps（每次调用）中位数 / 均值 / p10 | 33.60 / 32.29 / 26.86 |
| tps（按题取中位数再平均） | 32.29 |
| tps（聚合：总输出 token ÷ 总生成时间） | 35.69 |
| token 输入/输出 合计 | 40659 / 53157 |
| 每题模型调用次数 均值 | 1.00 |
| 每题轮数 均值 / 最多 | 0.00 / 0 |
| 输出被截断 | 2（1.3%） |
| 空回复 | 0 |
| 模型请求失败 | 0 |
| 求解超时 | 0 |

服务端 /metrics（跑分期间轮询）

- KV Cache 使用率峰值 0.0809、中位数 0.0275
- 同时在跑的请求数峰值 4.0
- 服务端计数的生成 token 53157.0、输入 token 40659.0
- 共采样 109 次

## 改动与假设

TODO：这一轮相对上一轮改了什么、预期效果

## 结论

TODO：结果是否符合预期；失败原因分析写在 dev/docs/notes/
