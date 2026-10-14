> 2026-10-14 整理补注：以下保留当时记录与测量值。旧得分、pass@5 和比较范围见[指标说明](../design/experiment-reading.md)。

# 20260924-210547-full-qwen3-30b-a3b-gptq-nothink

| 项 | 值 |
| --- | --- |
| 类型 | run_eval |
| 时间 | 2026-09-24 21:05:47 |
| git commit | `1073fcc` |
| 模型 | Qwen3-30B-A3B-GPTQ-Int4 |
| 参数 | `--tag full-qwen3-30b-a3b-gptq-nothink --modes baseline --jobs 4 --judge-jobs 4 --solve-timeout 400` |
| 原始文件 | `dev/runs/20260924-210547-full-qwen3-30b-a3b-gptq-nothink/` |

## 结果

| 模式 | 题数 | 题集得分 (pass@1) | pass@5 | 等级分布 | 环境失败 |
| --- | ---: | ---: | ---: | --- | ---: |
| baseline | 155/155 | 0.489 | 0.489 | {'L0': 40, 'L1': 49, 'L3': 66} | 0 |


## 失败原因分析（analyze.py 自动生成）

### baseline

样本 155 个，其中计分 155 个。

| 原因 | 样本数 | 例子 |
| --- | ---: | --- |
| L3 通过 | 66 | Prob003_step_one, Prob004_vector2, Prob005_notgate, Prob006_vectorr, Prob007_wire |
| L1：仿真结果与参考实现不一致 | 49 | Prob001_zero, Prob002_m2014_q4i, Prob031_dff, Prob034_dff8, Prob045_edgedetect2 |
| L0：语法分析（xvlog）失败 | 35 | Prob009_popcount3, Prob015_vector1, Prob017_mux2to1v, Prob018_mux256to1, Prob019_m2014_q4f |
| L0：详细描述（xelab）失败，非接口问题 | 3 | Prob096_review2015_fsmseq, Prob136_m2014_q6, Prob140_fsm_hdlc |
| L0：模块名或端口与测试台不符 | 2 | Prob016_m2014_q4j, Prob131_mt2015_q4 |

按题型（按题面关键词粗分（tasksets/categories.tsv），只用于看哪类题失败多）：

| 题型 | 题数 | pass@1 | 主要原因 |
| --- | ---: | ---: | --- |
| 卡诺图、真值表 | 8 | 0.200 | sim_mismatch 8 |
| 根据仿真波形推逻辑 | 12 | 0.283 | sim_mismatch 7, syntax 2, pass 2 |
| 状态机 | 39 | 0.292 | sim_mismatch 17, syntax 11, pass 8 |
| 其他时序电路（触发器、边沿检测等） | 18 | 0.522 | pass 8, sim_mismatch 7, syntax 3 |
| 组合逻辑 | 57 | 0.600 | pass 33, syntax 17, sim_mismatch 6 |
| 移位寄存器、LFSR、元胞自动机 | 10 | 0.720 | pass 7, syntax 2, sim_mismatch 1 |
| 改错题 | 3 | 0.733 | pass 2, sim_mismatch 1 |
| 计数器、定时器 | 8 | 0.800 | pass 6, sim_mismatch 2 |

模型调用：平均每个样本 1.0 次，输入 268 token，输出 230 token（最多 8192）；被截断的样本 1 个，请求失败的样本 0 个。
求解耗时：合计 1204.5 s，平均 7.8 s，中位数 4.7 s，90% 分位 13.3 s，最长 191.9 s。并行运行时各样本互相影响，只作相对比较。
Vivado 报错编号（L0 和综合失败的样本）：`VRFC 10-8530` × 34, `VRFC 10-1280` × 25, `XSIM 43-3322` × 5, `VRFC 10-4982` × 3, `VRFC 10-2063` × 2, `VRFC 10-9195` × 2, `VRFC 10-3818` × 2, `VRFC 10-2989` × 2, `VRFC 10-8549` × 1, `VRFC 10-9336` × 1, `VRFC 10-3186` × 1, `VRFC 10-5010` × 1, `VRFC 10-1491` × 1, `VRFC 10-3279` × 1, `VRFC 10-8928` × 1

## 改动与假设

多模型 baseline 初筛：Qwen3-30B-A3B-GPTQ-Int4（MoE），关思考，全题集。统一条件见 `../notes/archive/2026-09-24-baseline-sweep.md`。

## 结论

全题集 0.489；单路约 79 token/秒（Qwen3-8B BF16 约 26）。各模型的对比和选型判断见 `../notes/archive/2026-09-24-baseline-sweep.md`。
