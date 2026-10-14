> 2026-10-14 整理补注：以下保留当时记录与测量值。旧得分、pass@5 和比较范围见[指标说明](../design/experiment-reading.md)。

# 20260924-210230-q-qwen3-30b-a3b-gptq-nothink

| 项 | 值 |
| --- | --- |
| 类型 | run_eval |
| 时间 | 2026-09-24 21:02:30 |
| git commit | `1073fcc` |
| 模型 | Qwen3-30B-A3B-GPTQ-Int4 |
| 参数 | `--tag q-qwen3-30b-a3b-gptq-nothink --taskset quick --modes baseline --jobs 4 --judge-jobs 4 --solve-timeout 400` |
| 原始文件 | `dev/runs/20260924-210230-q-qwen3-30b-a3b-gptq-nothink/` |

## 结果

| 模式 | 题数 | 题集得分 (pass@1) | pass@5 | 等级分布 | 环境失败 |
| --- | ---: | ---: | ---: | --- | ---: |
| baseline | 34/34 | 0.571 | 0.571 | {'L0': 9, 'L1': 7, 'L3': 18} | 0 |


## 失败原因分析（analyze.py 自动生成）

### baseline

样本 34 个，其中计分 34 个。

| 原因 | 样本数 | 例子 |
| --- | ---: | --- |
| L3 通过 | 18 | Prob003_step_one, Prob008_m2014_q4h, Prob012_xnorgate, Prob022_mux2to1, Prob032_vector0 |
| L0：语法分析（xvlog）失败 | 8 | Prob017_mux2to1v, Prob026_alwaysblock1, Prob058_alwaysblock2, Prob095_review2015_fsmshift, Prob104_mt2015_muxdff |
| L1：仿真结果与参考实现不一致 | 7 | Prob062_bugs_mux2, Prob069_truthtable1, Prob101_circuit4, Prob121_2014_q3bfsm, Prob122_kmap4 |
| L0：详细描述（xelab）失败，非接口问题 | 1 | Prob133_2014_q3fsm |

按题型（按题面关键词粗分（tasksets/categories.tsv），只用于看哪类题失败多）：

| 题型 | 题数 | pass@1 | 主要原因 |
| --- | ---: | ---: | --- |
| 根据仿真波形推逻辑 | 2 | 0.100 | sim_mismatch 1, syntax 1 |
| 卡诺图、真值表 | 2 | 0.200 | sim_mismatch 2 |
| 状态机 | 7 | 0.229 | sim_mismatch 3, syntax 2, elab 1 |
| 其他时序电路（触发器、边沿检测等） | 4 | 0.500 | pass 2, syntax 2 |
| 改错题 | 2 | 0.600 | sim_mismatch 1, pass 1 |
| 组合逻辑 | 12 | 0.750 | pass 9, syntax 3 |
| 计数器、定时器 | 2 | 1.000 | pass 2 |
| 移位寄存器、LFSR、元胞自动机 | 3 | 1.000 | pass 3 |

模型调用：平均每个样本 1.0 次，输入 254 token，输出 158 token（最多 563）；被截断的样本 0 个，请求失败的样本 0 个。
求解耗时：合计 198.0 s，平均 5.8 s，中位数 4.5 s，90% 分位 12.8 s，最长 16.5 s。并行运行时各样本互相影响，只作相对比较。
Vivado 报错编号（L0 和综合失败的样本）：`VRFC 10-8530` × 8, `VRFC 10-1280` × 6, `VRFC 10-3186` × 1, `VRFC 10-4982` × 1, `VRFC 10-8928` × 1, `XSIM 43-3322` × 1

## 改动与假设

多模型 baseline 初筛：Qwen3-30B-A3B-GPTQ-Int4（MoE），关思考。统一条件见 `../notes/archive/2026-09-24-baseline-sweep.md`。

## 结论

quick 子集 0.571，速度最快（每题约 6 秒）；4 位 MoE 在 gfx1100 上可用。各模型的对比和选型判断见 `../notes/archive/2026-09-24-baseline-sweep.md`。
