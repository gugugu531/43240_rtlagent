> 2026-10-14 整理补注：本文保留当时验证结论；历史聊天附件或其他机器路径的当前可访问范围见[证据位置核对](2026-10-14-evidence-locations.md)。

# AutoDL Qwen3 baseline 测试与思考输出额度补测

类型：实验汇总。状态：测试结束，实例已释放。日期：2026-10-11。

来源：用户要求用现有 single_generate 尽量覆盖 Qwen3 及量化模型，显存不超过 32 GB，保存完整日志；随后要求提高思考模式输出额度并补测。

## 本轮结论

在完成相同 155 题的四款非思考模型中，Qwen/Qwen3-32B-AWQ 的加权得分最高（0.5871），全阶段通过 81/155 题，观测显存峰值 24.847 GB。可优先作为本轮预算内的后续验证候选；这一结论只覆盖实测四款与本次配置。

Qwen/Qwen3-8B-FP8 的峰值最低（12.931 GB），通过 49/155 题、得分 0.4013，适合用于比较更紧显存预算下的取舍，不能据此认为其质量与最高分模型相当。

思考额度从 8192 提高到 32768 后，32 个原截断样本中 19 个恢复最终代码，只有 4 个全阶段通过，且均来自 8B-AWQ。按用户要求，仍截断的 13 个模型与题目组合停止继续加码或重试。优先处理接口、变量类型、模块依赖与功能错误；不建议将全面增加额度作为默认优化。

## 方法与边界

- 使用 RTX 5090 × 1；vLLM 0.31.0、Torch 2.13.0+cu130。NVIDIA 上的结果仍需在目标 AMD 环境复核。
- 原始测试使用 single_generate、baseline 提示与代码提取、temperature=0、top_p=1、max_tokens=8192、单题单次请求。思考开关在模型服务配置中记录。
- 34 题用于模型筛选。155 题仅从已完成筛选且判定环境无错误的非思考模型中选择：最高加权得分、观测峰值不超过 14 GB 的最高得分、A3B MoE（混合专家模型）中的最高得分；重合时补入下一款不同模型。在任何完整题集结果产生前，追加与最佳 MoE 分差不超过 0.02 的 Coder 对照，最多四款。规则和追加时间见 experiment-plan.json。均沿用原排除清单，单题一次生成，不是 pass@5。
- 得分为官方等级系数平均值（L0=0、L1=0.2、L2=0.7、L3=1）；L3 数是全部判定阶段通过数，与加权得分不同。
- 补测只选择思考模式中 finish_reason=length 的题目，使用独立 single_generate_long_output；上限 32768、上下文 36864、请求超时 900 秒、整题 960 秒。其余请求字段和提取行为保持不变。
- 补测是有条件重试，子集成绩不能作为完整题集的一次生成成绩。既有 baseline、single_generate 默认行为和 repair_loop 未改。
- PyTorch 分配预算 24,000,000,000 字节，整卡监控每 0.1 秒采样，28,000,000,000 字节提前停止。表中峰值来自 NVML，GB 为十进制。采样峰值不能证明采样间隔内的瞬时值，分配预算也不是硬件分区。
- 求解并发始终为 1；本地判定并发由 2 提高为 4，实际配置逐次冻结。后台下载、冷启动和 eager 执行使耗时不适合作为独立硬件性能结论。

不同完整模型的排名不等于量化方法排名。例如 Coder-AWQ 与基础 MoE 的 GPTQ 版本同时改变了模型和量化方式，不能把差异单独归因于 AWQ 或 GPTQ。

## 实测结果

<!-- BEGIN:measured-results -->
本块自动生成，不要手改。生成命令（本次聊天工作区）：先运行 `python3 work/autodl-qwen3/analyze.py` 和 `python3 work/autodl-qwen3/summarize.py`，再运行 `python3 work/autodl-qwen3/report.py`。证据包 tools/ 保存脚本快照；脚本使用本次工作区路径，移到其他位置执行需调整路径。

### 34 题筛选

| 模型 | 模式 | L3/题数 | 加权得分 | 截断数 | 峰值 GB | 输出 token | 请求耗时合计秒 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Qwen/Qwen3-0.6B | 非思考 | 0/34 | 0.0176 | 2 | 4.695 | 19519 | 198.6 |
| Qwen/Qwen3-1.7B | 非思考 | 5/34 | 0.2000 | 1 | 6.956 | 15097 | 137.3 |
| Qwen/Qwen3-4B-AWQ | 非思考 | 10/34 | 0.3353 | 1 | 6.247 | 13679 | 314.7 |
| Qwen/Qwen3-8B-AWQ | 非思考 | 12/34 | 0.4294 | 0 | 11.226 | 5650 | 85.9 |
| Qwen/Qwen3-4B-AWQ | 思考 | 11/34 | 0.3294 | 15 | 6.247 | 161026 | 2384.7 |
| Qwen/Qwen3-8B-AWQ | 思考 | 18/34 | 0.5471 | 10 | 11.226 | 146444 | 2127.5 |
| Qwen/Qwen3-14B-AWQ | 非思考 | 15/34 | 0.4941 | 0 | 14.122 | 5913 | 99.4 |
| Qwen/Qwen3-4B | 非思考 | 11/34 | 0.3824 | 2 | 11.587 | 21257 | 232.8 |
| Qwen/Qwen3-32B-AWQ | 非思考 | 19/34 | 0.6176 | 0 | 24.847 | 5224 | 134.2 |
| Qwen/Qwen3-0.6B-FP8 | 非思考 | 0/34 | 0.0412 | 0 | 4.209 | 3631 | 51.4 |
| Qwen/Qwen3-1.7B-FP8 | 非思考 | 3/34 | 0.1176 | 0 | 5.490 | 6250 | 84.6 |
| Qwen/Qwen3-8B-FP8 | 非思考 | 15/34 | 0.5000 | 0 | 12.931 | 5633 | 100.2 |
| Qwen/Qwen3-30B-A3B-GPTQ-Int4 | 非思考 | 19/34 | 0.5941 | 1 | 20.428 | 13083 | 424.6 |
| Qwen/Qwen3-8B | 非思考 | 14/34 | 0.4824 | 0 | 19.875 | 5372 | 63.2 |
| Qwen/Qwen3-4B-Instruct-2507 | 非思考 | 12/34 | 0.4176 | 1 | 11.677 | 18832 | 211.3 |
| QuantTrio/Qwen3-Coder-30B-A3B-Instruct-AWQ | 非思考 | 18/34 | 0.5882 | 0 | 22.521 | 6917 | 221.0 |
| Qwen/Qwen3-4B-Thinking-2507 | 思考 | 14/34 | 0.4294 | 7 | 11.677 | 173308 | 1897.6 |
| Qwen/Qwen3-4B-FP8 | 非思考 | 10/34 | 0.3588 | 1 | 7.965 | 13514 | 232.3 |
| Qwen/Qwen3-14B-FP8 | 非思考 | 16/34 | 0.5118 | 0 | 20.032 | 5673 | 110.0 |

### 155 题扩展

| 模型 | 模式 | L3/题数 | 加权得分 | 截断数 | 峰值 GB | 输出 token | 请求耗时合计秒 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Qwen/Qwen3-32B-AWQ | 非思考 | 81/155 | 0.5871 | 0 | 24.847 | 27259 | 710.7 |
| Qwen/Qwen3-8B-FP8 | 非思考 | 49/155 | 0.4013 | 3 | 12.931 | 56345 | 942.5 |
| Qwen/Qwen3-30B-A3B-GPTQ-Int4 | 非思考 | 70/155 | 0.5123 | 0 | 20.428 | 28164 | 907.6 |
| QuantTrio/Qwen3-Coder-30B-A3B-Instruct-AWQ | 非思考 | 74/155 | 0.5523 | 1 | 22.521 | 43233 | 1348.3 |

### 32768 token 截断题补测

| 模型 | 模式 | L3/题数 | 加权得分 | 截断数 | 峰值 GB | 输出 token | 请求耗时合计秒 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Qwen/Qwen3-4B-AWQ | 思考 | 0/15 | 0.0267 | 10 | 10.100 | 359427 | 5248.2 |
| Qwen/Qwen3-8B-AWQ | 思考 | 4/10 | 0.4600 | 3 | 13.493 | 152827 | 2241.4 |
| Qwen/Qwen3-4B-Thinking-2507 | 思考 | 0/7 | 0.1143 | 0 | 15.529 | 93279 | 999.2 |

### 扩展题集与筛选题的关系

- Qwen/Qwen3-32B-AWQ：在本次 155 题运行中，原筛选题通过 19/34；其余题通过 62/121。原筛选运行 `20261011-155029-qwen3-32b-awq-nothink-full34-3b83cdee`。
- Qwen/Qwen3-8B-FP8：在本次 155 题运行中，原筛选题通过 15/34；其余题通过 34/121。原筛选运行 `20261011-155728-qwen3-8b-fp8-nothink-full34-ac839aaa`。
- Qwen/Qwen3-30B-A3B-GPTQ-Int4：在本次 155 题运行中，原筛选题通过 18/34；其余题通过 52/121。原筛选运行 `20261011-160033-qwen3-30b-a3b-gptq-int4-nothink-full34-3bd85161`。
- QuantTrio/Qwen3-Coder-30B-A3B-Instruct-AWQ：在本次 155 题运行中，原筛选题通过 17/34；其余题通过 57/121。原筛选运行 `20261011-161532-qwen3-coder-30b-a3b-instruct-awq-nothink-full34-98a8eb93`。
- 相同请求配置复测 `20261011-192507-qwen3-32b-awq-nothink-r192435-full155-f0548440`：与筛选运行重叠 34 题，代码逐字节相同 33 题，判定等级提高 0 题、下降 0 题、不变 34 题。
- 相同请求配置复测 `20261011-193839-qwen3-8b-fp8-nothink-r193812-full155-706f2796`：与筛选运行重叠 34 题，代码逐字节相同 34 题，判定等级提高 0 题、下降 0 题、不变 34 题。
- 相同请求配置复测 `20261011-195619-qwen3-30b-a3b-gptq-int4-nothink-r195537-full155-c55acbe3`：与筛选运行重叠 34 题，代码逐字节相同 17 题，判定等级提高 0 题、下降 1 题、不变 33 题。
- 相同请求配置复测 `20261011-201323-qwen3-coder-30b-a3b-instruct-awq-nothink-r201246-full155-60c897f6`：与筛选运行重叠 34 题，代码逐字节相同 19 题，判定等级提高 2 题、下降 4 题、不变 28 题。

### 输出额度逐题对照

- Qwen/Qwen3-4B-AWQ：补测 15 题；恢复最终内容 5 题，其中 4 题本次实际输出仍在原始 token 上限内；L3 0 题，仍截断 10 题；2/15 题的新思考文本以原思考文本为完整前缀。
  原始运行 `20261011-142353-qwen3-4b-awq-think-full34-4f3ab9b5`；补测 `20261011-165850-qwen3-4b-awq-think-32k-truncated-9909d824`。
- Qwen/Qwen3-8B-AWQ：补测 10 题；恢复最终内容 7 题，其中 3 题本次实际输出仍在原始 token 上限内；L3 4 题，仍截断 3 题；0/10 题的新思考文本以原思考文本为完整前缀。
  原始运行 `20261011-150418-qwen3-8b-awq-think-full34-6e6f79af`；补测 `20261011-182653-qwen3-8b-awq-think-32k-truncated-06fa26d5`。
- Qwen/Qwen3-4B-Thinking-2507：补测 7 题；恢复最终内容 7 题，其中 0 题本次实际输出仍在原始 token 上限内；L3 0 题，仍截断 0 题；0/7 题的新思考文本以原思考文本为完整前缀。
  原始运行 `20261011-162201-qwen3-4b-thinking-2507-think-full34-168e9695`；补测 `20261011-190449-qwen3-4b-thinking-2507-think-32k-truncated-f917d002`。

### 放弃继续补测的题目

按用户后续要求，原始 8192 token 和本轮 32768 token 均截断的模型与题目组合，到此停止；不再增加额度或反复重试。保留原始失败结果和全部日志，不删除失败样本，也不把它们改记为通过。本轮已选补测均已结束。

| 模型 | 题目 | 停止原因 |
| --- | --- | --- |
| Qwen/Qwen3-4B-AWQ | Prob075_counter_2bc | 32768 token 仍截断；无最终代码；放弃继续补测 |
| Qwen/Qwen3-4B-AWQ | Prob095_review2015_fsmshift | 32768 token 仍截断；无最终代码；放弃继续补测 |
| Qwen/Qwen3-4B-AWQ | Prob101_circuit4 | 32768 token 仍截断；无最终代码；放弃继续补测 |
| Qwen/Qwen3-4B-AWQ | Prob104_mt2015_muxdff | 32768 token 仍截断；无最终代码；放弃继续补测 |
| Qwen/Qwen3-4B-AWQ | Prob105_rotate100 | 32768 token 仍截断；无最终代码；放弃继续补测 |
| Qwen/Qwen3-4B-AWQ | Prob109_fsm1 | 32768 token 仍截断；无最终代码；放弃继续补测 |
| Qwen/Qwen3-4B-AWQ | Prob123_bugs_addsubz | 32768 token 仍截断；无最终代码；放弃继续补测 |
| Qwen/Qwen3-4B-AWQ | Prob133_2014_q3fsm | 32768 token 仍截断；无最终代码；放弃继续补测 |
| Qwen/Qwen3-4B-AWQ | Prob146_fsm_serialdata | 32768 token 仍截断；无最终代码；放弃继续补测 |
| Qwen/Qwen3-4B-AWQ | Prob154_fsm_ps2data | 32768 token 仍截断；无最终代码；放弃继续补测 |
| Qwen/Qwen3-8B-AWQ | Prob095_review2015_fsmshift | 32768 token 仍截断；无最终代码；放弃继续补测 |
| Qwen/Qwen3-8B-AWQ | Prob104_mt2015_muxdff | 32768 token 仍截断；无最终代码；放弃继续补测 |
| Qwen/Qwen3-8B-AWQ | Prob133_2014_q3fsm | 32768 token 仍截断；无最终代码；放弃继续补测 |

逐项来源运行、最后一次用量和判定见 `abandoned-tests.json`。

完整 155 题测试另记录 4 次原始 8192 token 截断，按各自实际判定保留，也不追加长输出或重复尝试。它们与上表经过两档额度的组合分别记录。

### 证据完整性

已完成样本 1299；完整调用记录 1299；trace 1299；请求符合对应实验配置 1299；提取逐字节符合 baseline 1299。
判定环境错误 0；未记录 token 用量 0。

本轮完成统一 34 题的模型版本数为 17。候选目录另有 10 个版本未进入执行队列，这不代表经过实测的显存或兼容性失败；具体范围见 `coverage-audit.json`。

### 运行编号索引

- [20261011-140418-qwen3-0p6b-nothink-smoke-96a7f52a](../experiments/20261011-140418-qwen3-0p6b-nothink-smoke-96a7f52a.md)：Qwen/Qwen3-0.6B，非思考，8192 token。
- [20261011-140545-qwen3-0p6b-nothink-full34-d85dbf85](../experiments/20261011-140545-qwen3-0p6b-nothink-full34-d85dbf85.md)：Qwen/Qwen3-0.6B，非思考，8192 token。
- [20261011-141021-qwen3-1p7b-nothink-full34-b48a6ffb](../experiments/20261011-141021-qwen3-1p7b-nothink-full34-b48a6ffb.md)：Qwen/Qwen3-1.7B，非思考，8192 token。
- [20261011-141315-qwen3-4b-awq-nothink-full34-8422a6e7](../experiments/20261011-141315-qwen3-4b-awq-nothink-full34-8422a6e7.md)：Qwen/Qwen3-4B-AWQ，非思考，8192 token。
- [20261011-141910-qwen3-8b-awq-nothink-full34-9be62c55](../experiments/20261011-141910-qwen3-8b-awq-nothink-full34-9be62c55.md)：Qwen/Qwen3-8B-AWQ，非思考，8192 token。
- [20261011-142353-qwen3-4b-awq-think-full34-4f3ab9b5](../experiments/20261011-142353-qwen3-4b-awq-think-full34-4f3ab9b5.md)：Qwen/Qwen3-4B-AWQ，思考，8192 token。
- [20261011-150418-qwen3-8b-awq-think-full34-6e6f79af](../experiments/20261011-150418-qwen3-8b-awq-think-full34-6e6f79af.md)：Qwen/Qwen3-8B-AWQ，思考，8192 token。
- [20261011-154029-qwen3-14b-awq-nothink-full34-ad93ffc3](../experiments/20261011-154029-qwen3-14b-awq-nothink-full34-ad93ffc3.md)：Qwen/Qwen3-14B-AWQ，非思考，8192 token。
- [20261011-154546-qwen3-4b-nothink-full34-07c53ac0](../experiments/20261011-154546-qwen3-4b-nothink-full34-07c53ac0.md)：Qwen/Qwen3-4B，非思考，8192 token。
- [20261011-155029-qwen3-32b-awq-nothink-full34-3b83cdee](../experiments/20261011-155029-qwen3-32b-awq-nothink-full34-3b83cdee.md)：Qwen/Qwen3-32B-AWQ，非思考，8192 token。
- [20261011-155349-qwen3-0p6b-fp8-nothink-full34-a233f01c](../experiments/20261011-155349-qwen3-0p6b-fp8-nothink-full34-a233f01c.md)：Qwen/Qwen3-0.6B-FP8，非思考，8192 token。
- [20261011-155521-qwen3-1p7b-fp8-nothink-full34-9ebfce50](../experiments/20261011-155521-qwen3-1p7b-fp8-nothink-full34-9ebfce50.md)：Qwen/Qwen3-1.7B-FP8，非思考，8192 token。
- [20261011-155728-qwen3-8b-fp8-nothink-full34-ac839aaa](../experiments/20261011-155728-qwen3-8b-fp8-nothink-full34-ac839aaa.md)：Qwen/Qwen3-8B-FP8，非思考，8192 token。
- [20261011-160033-qwen3-30b-a3b-gptq-int4-nothink-full34-3bd85161](../experiments/20261011-160033-qwen3-30b-a3b-gptq-int4-nothink-full34-3bd85161.md)：Qwen/Qwen3-30B-A3B-GPTQ-Int4，非思考，8192 token。
- [20261011-160821-qwen3-8b-nothink-full34-ccef6ff7](../experiments/20261011-160821-qwen3-8b-nothink-full34-ccef6ff7.md)：Qwen/Qwen3-8B，非思考，8192 token。
- [20261011-161100-qwen3-4b-instruct-2507-nothink-full34-9ad508d8](../experiments/20261011-161100-qwen3-4b-instruct-2507-nothink-full34-9ad508d8.md)：Qwen/Qwen3-4B-Instruct-2507，非思考，8192 token。
- [20261011-161532-qwen3-coder-30b-a3b-instruct-awq-nothink-full34-98a8eb93](../experiments/20261011-161532-qwen3-coder-30b-a3b-instruct-awq-nothink-full34-98a8eb93.md)：QuantTrio/Qwen3-Coder-30B-A3B-Instruct-AWQ，非思考，8192 token。
- [20261011-162201-qwen3-4b-thinking-2507-think-full34-168e9695](../experiments/20261011-162201-qwen3-4b-thinking-2507-think-full34-168e9695.md)：Qwen/Qwen3-4B-Thinking-2507，思考，8192 token。
- [20261011-165418-qwen3-4b-fp8-nothink-r165351-full34-7e39ace2](../experiments/20261011-165418-qwen3-4b-fp8-nothink-r165351-full34-7e39ace2.md)：Qwen/Qwen3-4B-FP8，非思考，8192 token。
- [20261011-165850-qwen3-4b-awq-think-32k-truncated-9909d824](../experiments/20261011-165850-qwen3-4b-awq-think-32k-truncated-9909d824.md)：Qwen/Qwen3-4B-AWQ，思考，32768 token。
- [20261011-182653-qwen3-8b-awq-think-32k-truncated-06fa26d5](../experiments/20261011-182653-qwen3-8b-awq-think-32k-truncated-06fa26d5.md)：Qwen/Qwen3-8B-AWQ，思考，32768 token。
- [20261011-190449-qwen3-4b-thinking-2507-think-32k-truncated-f917d002](../experiments/20261011-190449-qwen3-4b-thinking-2507-think-32k-truncated-f917d002.md)：Qwen/Qwen3-4B-Thinking-2507，思考，32768 token。
- [20261011-192206-qwen3-14b-fp8-nothink-full34-b6d4a848](../experiments/20261011-192206-qwen3-14b-fp8-nothink-full34-b6d4a848.md)：Qwen/Qwen3-14B-FP8，非思考，8192 token。
- [20261011-192507-qwen3-32b-awq-nothink-r192435-full155-f0548440](../experiments/20261011-192507-qwen3-32b-awq-nothink-r192435-full155-f0548440.md)：Qwen/Qwen3-32B-AWQ，非思考，8192 token。
- [20261011-193839-qwen3-8b-fp8-nothink-r193812-full155-706f2796](../experiments/20261011-193839-qwen3-8b-fp8-nothink-r193812-full155-706f2796.md)：Qwen/Qwen3-8B-FP8，非思考，8192 token。
- [20261011-195619-qwen3-30b-a3b-gptq-int4-nothink-r195537-full155-c55acbe3](../experiments/20261011-195619-qwen3-30b-a3b-gptq-int4-nothink-r195537-full155-c55acbe3.md)：Qwen/Qwen3-30B-A3B-GPTQ-Int4，非思考，8192 token。
- [20261011-201323-qwen3-coder-30b-a3b-instruct-awq-nothink-r201246-full155-60c897f6](../experiments/20261011-201323-qwen3-coder-30b-a3b-instruct-awq-nothink-r201246-full155-60c897f6.md)：QuantTrio/Qwen3-Coder-30B-A3B-Instruct-AWQ，非思考，8192 token。

<!-- END:measured-results -->

补测为容纳更长输出同时扩大了服务上下文和 KV cache。即使温度固定为 0，新旧推理也可能出现不同轨迹；对于恢复代码但本次总输出仍低于 8192 的样本，不能将恢复直接归因于额度增大。若要进一步测量纯额度效应，需要在相同服务上下文与缓存条件下对照请求额度，并做重复运行。

## 环境失败与分析注意事项

Qwen3-4B-FP8 首次服务启动失败：镜像 nvcc 为 12.8，而所选 DeepGEMM 内核要求至少 12.9。这发生在题目请求前，不是代码质量或显存超限。后续 FP8 服务记录 VLLM_USE_DEEP_GEMM=0，使用可用的 Cutlass 内核；首次失败日志保留。

部分模型下载遇到 HTTP 503。通过分块下载、校验与相同公开文件的哈希匹配复用完成重试；旧失败日志和最终下载清单同时保存。为腾出数据盘空间，只删除本次已测完且不再需要的临时权重和 pip 缓存，保留配置、来源、哈希、删除清单和所有实验日志。

代码失败已观察到模块端口缺失、wire 在过程块赋值、位宽不符合接口、缺少子模块、状态或移位语义不正确。思考模式另有只生成推理、反复自问直到额度耗尽的情况。不能把这些问题笼统归因于代码提取。

还确认了 baseline 共有提取规则的限制：部分回复包含辅助模块，但固定提取只留下 TopModule，导致依赖缺失。对筛选及已完成 4B-AWQ 补测中的五例做独立离线诊断，只恢复原回复已有的模块、不改模块体：Coder-AWQ 和 4B-AWQ 长输出各一例达到 L3；32B-AWQ 和 4B-Instruct-2507 各一例达到 L1；14B-AWQ 一例仍为 L0。该诊断没有新的模型调用，结果不计入任何 baseline 或长输出成绩。全部派生代码、原始响应与判定日志见 module-restoration-diagnostic；正式提取实现与原始答案均未改动。

另外用 Transformers 在 CPU 上直接加载同一 Qwen3-8B BF16 权重，复核 Prob026_alwaysblock1 与 Prob048_m2014_q4c。两题的提示 token 数、生成 token 数、提取后代码均与对应 vLLM 原始运行一致，输出类型错误也相同。这个两题诊断支持将这些错误归为模型生成问题，不能据此证明所有模型或内核都等价。诊断只用两条 CPU 线程、禁用 CUDA，输出上限单独设为 256，不计入 baseline 成绩；原始输出和比较结果见 backend-check-8b-cpu。

分析脚本曾因文本读取自动转换 CRLF 把三个结果误报为提取不一致；改用字节比较后确认完全一致，生成代码未改。初次上下文预检也修正了 tokenizer 返回值计数方法，错误预检记录保留。

## 后续优化方向

1. 根据补测逐题证据区分正常长推理与重复循环：能恢复代码的题目适合较大额度；持续循环的题目应另做采样参数对照，不能只无限增大额度。
2. 将接口一致性、变量类型、模块依赖和功能错误分开处理。独立策略可以保留回复中已有的辅助模块并做编译检查，再检查状态机终止状态、保持条件与位宽；应另建实验流程，不改变本轮 baseline，也不覆盖现有 repair_loop。
3. 依据完整 155 题成绩、显存和耗时选择候选。34 题中某个量化版分数略高，不足以证明量化本身提高质量。
4. 优先在目标 AMD 硬件复核选中权重的量化内核、显存、上下文和速度，再决定正式服务方案。

Qwen 官方说明提醒思考模式的贪心解码可能重复；本轮保持 temperature=0 是为了单独比较输出额度，未同时更改采样。[Qwen3-4B-AWQ 模型卡](https://huggingface.co/Qwen/Qwen3-4B-AWQ)。

## 代码验证与原始日志

长输出扩展的差分与回归共 134 项测试，2 项因本地测试解释器缺少 FastAPI 按原条件跳过，其余通过；Supervisor mock smoke、提交检查、无 dev 的默认与扩展运行包 smoke 均通过。首次扩展放在 dev 被运行边界拒绝的记录也保留。

代码位于独立分支 codex/qwen3-autodl-evaluation；长输出扩展提交 de19c24；实验归档时尚未推送，后续交付状态以分支与 PR 为准。用户原有未提交文件按字节哈希核对保留。

原始 Agent 记录位于 43240-agent/dev/runs/20261011-autodl-qwen3。聊天输出目录 outputs/autodl-qwen3 保存配置、服务/资源证据、分析结果、验证日志和最终备份。凭据、模型权重与原始运行日志不进入 Git。

实例释放状态：已通过控制台确认；详情见 release-verification.json。
