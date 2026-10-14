> 2026-10-14 整理补注：以下保留当时记录与测量值。旧得分、pass@5 和比较范围见[指标说明](../design/experiment-reading.md)。

# 20260924-120512-baseline-qwen3-8b-parser-merged

| 项 | 值 |
| --- | --- |
| 类型 | run_eval |
| 时间 | 2026-09-24 12:05:12 |
| git commit | `abde3b1` |
| 模型 | Qwen3-8B |
| 参数 | `--tag baseline-qwen3-8b-think-parser --modes baseline --jobs 4 --judge-jobs 4 --solve-timeout 400 （合并：主评测 105 题 + 睡眠受影响的 4 题补跑 + 暂停后续跑 50 题）` |
| 原始文件 | `dev/runs/20260924-120512-baseline-qwen3-8b-parser-merged/` |

## 结果

| 模式 | 题数 | 题集得分 (pass@1) | pass@5 | 等级分布 | 环境失败 |
| --- | ---: | ---: | ---: | --- | ---: |
| baseline | 155/155 | 0.484 | 0.484 | {'L0': 68, 'L1': 15, 'L3': 72} | 0 |


## 失败原因分析（analyze.py 自动生成）

### baseline

样本 155 个，其中计分 155 个。

| 原因 | 样本数 | 例子 |
| --- | ---: | --- |
| L3 通过 | 72 | Prob001_zero, Prob002_m2014_q4i, Prob003_step_one, Prob005_notgate, Prob006_vectorr |
| L0：模型请求失败 | 48 | Prob016_m2014_q4j, Prob033_ece241_2014_q1c, Prob043_vector5, Prob045_edgedetect2, Prob053_m2014_q4d |
| L0：语法分析（xvlog）失败 | 19 | Prob011_norgate, Prob013_m2014_q4e, Prob021_mux256to1v, Prob026_alwaysblock1, Prob039_always_if |
| L1：仿真结果与参考实现不一致 | 15 | Prob004_vector2, Prob028_m2014_q4a, Prob034_dff8, Prob062_bugs_mux2, Prob063_review2015_shiftcount |
| L0：模块名或端口与测试台不符 | 1 | Prob104_mt2015_muxdff |

按题型（按题面关键词粗分（tasksets/categories.tsv），只用于看哪类题失败多）：

| 题型 | 题数 | pass@1 | 主要原因 |
| --- | ---: | ---: | --- |
| 移位寄存器、LFSR、元胞自动机 | 10 | 0.220 | llm_error 4, syntax 3, pass 2 |
| 状态机 | 39 | 0.231 | llm_error 21, pass 8, sim_mismatch 5 |
| 卡诺图、真值表 | 8 | 0.250 | llm_error 6, pass 2 |
| 改错题 | 3 | 0.400 | sim_mismatch 1, pass 1, llm_error 1 |
| 其他时序电路（触发器、边沿检测等） | 18 | 0.400 | pass 7, llm_error 6, syntax 3 |
| 根据仿真波形推逻辑 | 12 | 0.500 | pass 6, llm_error 4, syntax 2 |
| 组合逻辑 | 57 | 0.709 | pass 39, sim_mismatch 7, syntax 6 |
| 计数器、定时器 | 8 | 0.875 | pass 7, llm_error 1 |

模型调用：平均每个样本 1.0 次，输入 149 token，输出 1470 token（最多 6717）；被截断的样本 0 个，请求失败的样本 48 个。
求解耗时：合计 24729.5 s，平均 159.5 s，中位数 118.1 s，90% 分位 300.7 s，最长 301.1 s。并行运行时各样本互相影响，只作相对比较。
Vivado 报错编号（L0 和综合失败的样本）：`VRFC 10-8530` × 18, `VRFC 10-1280` × 7, `VRFC 10-4982` × 4, `VRFC 10-8549` × 3, `VRFC 10-9336` × 3, `VRFC 10-1775` × 1, `VRFC 10-2951` × 1, `VRFC 10-395` × 1, `VRFC 10-3180` × 1, `XSIM 43-3322` × 1, `VRFC 10-5011` × 1, `VRFC 10-1491` × 1, `VRFC 10-2989` × 1

## 改动与假设

与 `20260924-113712-baseline-qwen3-8b-think.md` 相同，只是 vLLM 加了
`--reasoning-parser qwen3`（通过 `VLLM_EXTRA_ARGS`），思考内容进入 `reasoning` 字段，
`content` 只有最终回答。仍然默认开启思考。

**本结果由三段合并而成**，合并规则：同一题以最后一次运行为准。
1. 主评测 `20260924-120512-...-parser`：完成 105 题。12:09 到 12:39 本机自动休眠，
   当时在跑的 4 题（Prob016、Prob026、Prob027、Prob028）连接中断，结果作废
2. 补跑 `...-parser-rerun`：重跑上述 4 题中的 2 题
3. 暂停十分钟后续跑 `...-parser-resume`：剩余 50 题加另外 2 道补跑题

原始文件分别在 `dev/runs/` 下的对应目录。

## 结论

**Qwen3-8B 的 baseline 题集得分：0.484**（155 题，L3 72、L1 15、L0 68）。

1. **reasoning parser 效果显著**：在两种配置共同的 63 题上，0.486 → 0.695（+0.210，变好 16 题、
   变差 2 题）。这是服务配置，同时作用于方案和基线，最终采用的话要写进 `model/MODEL.md`
2. **超时是最大的失分来源**：68 个 L0 中 48 个是 300 秒请求超时（`baseline.py` 固定，不可改）。
   单路约 25 token/秒，300 秒最多约 7,500 token，思考长的题（状态机、移位寄存器、卡诺图）
   大量超时。决赛的 R9700 显存带宽更低，超时只会更多
3. **剩下 19 个语法错误是模型真实的 Verilog 错误**，典型的有：`output` 未声明为 `reg`
   却在 `always` 里赋值、重复声明端口、把 `nor` 当运算符。这类错误编译器能报出来，
   agent 靠 lint 反馈修复的空间很大
4. 按题型：组合逻辑 0.709、计数器 0.875；状态机 0.231、移位寄存器类 0.220、卡诺图 0.250

对选型的含义：对 Qwen3-8B 这类混合思考模型，是否关闭思考、思考长度与速度，比模型本身的
能力更影响 baseline。下一步应测「关闭思考」的配置，以及速度更快的量化或 MoE 模型。
