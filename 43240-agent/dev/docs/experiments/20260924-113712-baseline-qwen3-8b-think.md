> 2026-10-14 整理补注：以下保留当时记录与测量值。旧得分、pass@5 和比较范围见[指标说明](../design/experiment-reading.md)。

# 20260924-113712-baseline-qwen3-8b-think

| 项 | 值 |
| --- | --- |
| 类型 | run_eval |
| 时间 | 2026-09-24 11:37:12 |
| git commit | `d3b5104` |
| 模型 | Qwen3-8B |
| 参数 | `--tag baseline-qwen3-8b-think --modes baseline --jobs 4 --judge-jobs 4 --solve-timeout 400` |
| 原始文件 | `dev/runs/20260924-113712-baseline-qwen3-8b-think/` |

## 结果

| 模式 | 题数 | 题集得分 (pass@1) | pass@5 | 等级分布 | 环境失败 |
| --- | ---: | ---: | ---: | --- | ---: |
| baseline | 63/63 | 0.486 | 0.486 | {'L0': 30, 'L1': 3, 'L3': 30} | 0 |


## 失败原因分析（analyze.py 自动生成）

### baseline

样本 63 个，其中计分 63 个。

| 原因 | 样本数 | 例子 |
| --- | ---: | --- |
| L3 通过 | 30 | Prob002_m2014_q4i, Prob003_step_one, Prob006_vectorr, Prob007_wire, Prob008_m2014_q4h |
| L0：语法分析（xvlog）失败 | 23 | Prob001_zero, Prob005_notgate, Prob011_norgate, Prob013_m2014_q4e, Prob014_andgate |
| L0：模型请求失败 | 7 | Prob016_m2014_q4j, Prob030_popcount255, Prob033_ece241_2014_q1c, Prob035_count1to10, Prob045_edgedetect2 |
| L1：仿真结果与参考实现不一致 | 3 | Prob004_vector2, Prob034_dff8, Prob062_bugs_mux2 |

按题型（按题面关键词粗分（tasksets/categories.tsv），只用于看哪类题失败多）：

| 题型 | 题数 | pass@1 | 主要原因 |
| --- | ---: | ---: | --- |
| 移位寄存器、LFSR、元胞自动机 | 2 | 0.000 | syntax 2 |
| 改错题 | 1 | 0.200 | sim_mismatch 1 |
| 其他时序电路（触发器、边沿检测等） | 12 | 0.267 | syntax 6, pass 3, llm_error 2 |
| 计数器、定时器 | 4 | 0.500 | pass 2, llm_error 1, syntax 1 |
| 卡诺图、真值表 | 2 | 0.500 | pass 1, llm_error 1 |
| 组合逻辑 | 42 | 0.576 | pass 24, syntax 14, llm_error 3 |

模型调用：平均每个样本 1.0 次，输入 127 token，输出 1155 token（最多 4164）；被截断的样本 0 个，请求失败的样本 7 个。
求解耗时：合计 5322.9 s，平均 84.5 s，中位数 52.4 s，90% 分位 300.6 s，最长 300.9 s。并行运行时各样本互相影响，只作相对比较。
Vivado 报错编号（L0 和综合失败的样本）：`VRFC 10-8530` × 19, `VRFC 10-4982` × 18, `VRFC 10-8549` × 12, `VRFC 10-1280` × 7, `VRFC 10-9336` × 5, `VRFC 10-569` × 2, `VRFC 10-2951` × 1, `VRFC 10-3365` × 1, `VRFC 10-8412` × 1

## 改动与假设

Qwen3-8B（BF16）的第一次 baseline 测量。实例 W7900（gfx1100），vLLM 0.16.1，使用提交方案的
`serve/vllm.sh` 原样启动（`MAX_LEN=32768`，`GPU_UTIL=0.62` 以模拟 32 GB，**没有 reasoning parser**，
Qwen3 默认开启思考）。baseline 并发 4。

**中途停止**：只完成 63 题（按题目编号顺序，偏简单的题），用于和加了 reasoning parser 的配置对比，
不代表全题集得分。

## 结论

63 题上的题集得分 0.486，L0 有 30 个：

- 23 个语法错误：几乎都是**思考内容被当成了代码**。没有 reasoning parser 时，思考过程
  （`<think>` 中的文字）留在回复的 `content` 里，`baseline.py` 取第一段 `module TopModule`
  到 `endmodule`，落在思考里的草稿或文字上
- 7 个是 `baseline.py` 固定的 300 秒请求超时

吞吐：单路约 25.7 token/秒，4 路并发合计约 95 token/秒（每路约 24），显存带宽受限，
并发几乎不拖慢单路。显存占用 32.15 GB（约 29.9 GiB）。

结论：服务端必须加 `--reasoning-parser qwen3`，见 `20260924-120512-baseline-qwen3-8b-parser-merged.md`。
