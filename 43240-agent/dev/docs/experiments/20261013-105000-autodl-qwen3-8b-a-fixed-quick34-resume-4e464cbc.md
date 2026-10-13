# 20261013-105000-autodl-qwen3-8b-a-fixed-quick34-resume-4e464cbc

原始记录：`/home/cloudia/FPGACHINA/AMD_SocChina_2026/43240-agent/dev/runs/20261013-105000-autodl-qwen3-8b-a-fixed-quick34-resume-4e464cbc`。

<!-- BEGIN:results -->
状态：completed。完成 10/10 个样本。

本文件由 dev/tools/run.py 生成，不要手改。逐样本证据见 samples/。

| 模式 | 样本 | 官方等级分布 |
| --- | ---: | --- |
| agent | 5 | {'L0': 3, 'L1': 2} |
| baseline | 5 | {'L0': 2, 'L1': 3} |
<!-- END:results -->

## 改动与假设

本文件既记录本次 5 题补跑，也给出与昨晚 29 题合并后的完整 quick-34 结果。
上方自动生成块只描述本次 10 个样本，不代表完整 34 题的分布。

- 原运行：[20261012-225403](20261012-225403-autodl-qwen3-8b-a-fixed-quick34-460c1d2a.md)，
  按用户要求暂停，保留 29 题双方共 58 个有效样本。
- 本次运行：2026-10-13 10:50:00—11:19:53（东京时间），只补跑剩余 5 题双方共 10 项。
  原运行目录及其 `cancelled` 状态均保留，没有覆盖、伪装成一次连续运行。
- 运行前逐一核对原源码快照的 88 个文件，全部一致；本轮只修正开发侧 watchdog 撤销时
  非交互 SSH 的 Python 路径，新增补跑与合并工具，**正式求解代码和提示未变**。
- 远端仍为 NVIDIA vGPU-48GB（49140 MiB），Qwen3-8B 模型提交
  `b968826d9c46dd6066d109eabc6255188de91218`。5 个权重分片及配置、tokenizer 文件
  SHA256 全部核验通过。Python 3.12.3、PyTorch 2.8.0+cu128、vLLM 0.11.0 保持不变。
- vLLM 最大上下文 32768、显存比例 0.85、`--reasoning-parser qwen3`，默认 thinking
  设置不变。双方均为 temperature 0、top_p 1、max_tokens 8192、单次请求上限 300 秒。
- Agent 仍为 `evidence_repair`，总预算 360 秒、预留 20 秒、最多一次代码补救；baseline
  脚本未改且与主办方 example 字节一致。求解、评分并发均为 1，每题每组一个样本。
- 本地 Vivado 2026.1，器件 `xczu3eg-sbva484-1-e`。官方 testbench 仅在开发评分中使用，
  不进入求解上下文。没有因 L0 或 L1 而选择性补采样。

两次运行的工作区均为 dirty，`source_complete=false` 来自开发 `_common.sh` 和
`serve/README.md` 的占位 key 脱敏；正式求解代码的快照未被脱敏。本次有逐文件哈希证据，
但不能仅凭 git 提交号将它宣称为已经封存的完整可复现实验。

## 结论

**quick-34 的 34 题、68 个有效样本已经齐全。当前方案 A 尚未优于 baseline，且成本更高。**

本轮可以作为后续固定题集的对照起点，但不是单个 Node 的消融，也不是多次重复的稳定性结论。
不能与前一轮断连实验中含基础设施错误的原始“34 题分数”直接比较。

## 完整 quick-34 成绩

数字来自本次补跑目录 `combined/summary.json`，由仓库原始 `selftest/score.py` 的聚合函数
计算；未修改官方评分规则。官方系数：L0=0、L1=0.2、L2=0.7、L3=1。

| 模式 | 有效样本 | L0 | L1 | L2 | L3 | 官方系数均值 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| agent | 34 | 12 | 5 | 0 | 17 | 0.5294 |
| baseline | 34 | 10 | 6 | 0 | 18 | 0.5647 |

Agent/baseline gain 约 **0.9375**，系数均值低约 **3.53 个百分点**，相对低约 **6.25%**。
gain 由官方四位小数得分相除，原始值为 `0.9374889321763769`。
这里的系数均值不是简单的 L3 比例；L3 题数分别为 17/34、18/34。
每题只有一个样本，不解读自动摘要中的 pass@5 为五次采样实测。

有效性检查：

- 两组均覆盖同一 34 题，`full_comparison_valid=true`、`paired_coverage=true`。
- 所有选入样本的 runtime、model、judge 指标状态均为 `ok`。
- 模型调用失败、未结束调用、官方判定工具错误和有效样本排除数均为 0。
- 昨晚的 10 个取消项未计分；补跑只替换这些未完成项，58 个已完成项不变。
- 原运行及补跑的正式源码哈希、有效配置、题目 prompt/interface 哈希一致。
- 正式补跑期间 gateway 没有传输重试或 HTTP 错误；昨晚已完成子集也未记录这些异常。

合并命令（只读两个原运行，派生输出写入补跑目录 `combined/`）：

```bash
python3 dev/tools/combine_runs.py \
  dev/runs/20261012-225403-autodl-qwen3-8b-a-fixed-quick34-460c1d2a \
  dev/runs/20261013-105000-autodl-qwen3-8b-a-fixed-quick34-resume-4e464cbc
```

派生文件为 `combined/summary.json`、`combined/metrics.json`、`combined/provenance.json`。
逐样本来源和未选入的取消项均可追溯，合并工具 SHA256 也记录在摘要中。
该目录已存在，工具为防止覆盖不会重复写入；复核可只读调用 `combine()`。

## 成本与效率

求解时间包含模型和 Agent 自身检查，不含后续官方评分，也不含隔夜暂停。
输出 tokens 包含模型 thinking，不能理解为 RTL 代码长度。

| 指标 | agent | baseline |
| --- | ---: | ---: |
| 成功模型调用数 | 53 | 34 |
| 长度截断调用数 | 24 | 6 |
| 至少一次截断的题数 | 15 | 6 |
| 输入 tokens 合计 | 53904 | 8500 |
| 输出 tokens 合计 | 258698 | 124628 |
| 求解时间合计 | 5348.15 秒 | 2329.95 秒 |
| 平均每题求解时间 | 157.30 秒 | 68.53 秒 |
| 中位求解时间 | 129.02 秒 | 58.40 秒 |
| p90 求解时间（最近秩法） | 308.28 秒 | 153.67 秒 |

Agent 求解时间约为 baseline 的 2.30 倍，输出 tokens 约为 2.08 倍。
这些差异同时受到提示、额外生成、工具检查及服务缓存状态影响，不能全部归因于反馈日志。

## Workflow 观察

1. **修复链路有效，但整体收益不足以抵消损失。** 5 题实际发出 `purpose=repair` 的请求。
   `Prob017`、`Prob026`、`Prob048`、`Prob087` 首版 lint 失败，修复后均获官方 L3；
   `Prob058` 修复后仍失败，保留第一版候选并记录失败证据。与 baseline 相比，最终只有
   `Prob026`、`Prob048` 两题更好。
2. **额外调用多用于重新生成。** 19 题发生第二次调用，其中 5 题是已有候选的代码修复，
   14 题是在没有可用父候选时再次生成。长度截断的思考回复不能简单当作可修复 RTL。
3. **L0 主要集中在提取和代码错误。** Agent 的停止原因为 `extraction` 8 题、`code`
   4 题、`synth_passed` 22 题。若两轮都停在 `<think>` 内，没有完整模块，继续增加修复
   轮数会增加成本，但未必获得答案。仍需区分无 RTL、目标模块不符以及实际编译错误。
4. **可综合不代表功能正确。** 22 题内部综合通过，但官方仅 17 题 L3；另 5 题是 L1：
   `Prob062`、`Prob063`、`Prob105`、`Prob146`、`Prob154`。不能使用隐藏 testbench/judge
   结果指导正式求解；功能改进需来自题面检查或独立、合规的验证策略。
5. **候选保留按预期工作。** `Prob058`、`Prob121`、`Prob138` 最终以
   `failed_check_fallback` 选择完整候选，均保留了失败证据；它们仍是 L0，不能宣称
   “保留代码”本身带来分数提升。不能把任意不完整或接口不合格的片段当作可提交候选。

## 逐题对比

Agent 更好 2 题、更差 5 题、相同 27 题。这里比较的是最终官方等级，不是只比较综合检查。

| 题目 | agent | baseline | 相对结果 |
| --- | --- | --- | --- |
| Prob003_step_one | L3 | L3 | 相同 |
| Prob008_m2014_q4h | L3 | L3 | 相同 |
| Prob012_xnorgate | L3 | L3 | 相同 |
| Prob017_mux2to1v | L3 | L3 | 相同 |
| Prob022_mux2to1 | L3 | L3 | 相同 |
| Prob026_alwaysblock1 | L3 | L0 | 提高 |
| Prob032_vector0 | L3 | L3 | 相同 |
| Prob038_count15 | L3 | L3 | 相同 |
| Prob041_dff8r | L3 | L3 | 相同 |
| Prob043_vector5 | L0 | L0 | 相同 |
| Prob048_m2014_q4c | L3 | L0 | 提高 |
| Prob055_conditional | L3 | L3 | 相同 |
| Prob058_alwaysblock2 | L0 | L0 | 相同 |
| Prob062_bugs_mux2 | L1 | L1 | 相同 |
| Prob063_review2015_shiftcount | L1 | L1 | 相同 |
| Prob069_truthtable1 | L3 | L3 | 相同 |
| Prob071_always_casez | L3 | L3 | 相同 |
| Prob075_counter_2bc | L3 | L3 | 相同 |
| Prob087_gates | L3 | L3 | 相同 |
| Prob095_review2015_fsmshift | L0 | L0 | 相同 |
| Prob101_circuit4 | L0 | L3 | 降低 |
| Prob104_mt2015_muxdff | L0 | L0 | 相同 |
| Prob105_rotate100 | L1 | L3 | 降低 |
| Prob106_always_nolatches | L3 | L3 | 相同 |
| Prob109_fsm1 | L0 | L3 | 降低 |
| Prob115_shift18 | L0 | L1 | 降低 |
| Prob121_2014_q3bfsm | L0 | L0 | 相同 |
| Prob122_kmap4 | L3 | L3 | 相同 |
| Prob123_bugs_addsubz | L0 | L0 | 相同 |
| Prob131_mt2015_q4 | L0 | L0 | 相同 |
| Prob133_2014_q3fsm | L0 | L0 | 相同 |
| Prob138_2012_q2fsm | L0 | L1 | 降低 |
| Prob146_fsm_serialdata | L1 | L1 | 相同 |
| Prob154_fsm_ps2data | L1 | L1 | 相同 |

## 资源收尾与下一步

本次补跑会话于 10:49:24 启动，安装 90 分钟保护、80 分钟提醒，未触及限额。
11:19:55 vLLM 已自动停止，随后核实 GPU 显存 0 MiB、利用率 0%，远端 watchdog 已撤销；
本地 experiment、transport、gateway、阻止休眠服务及两项定时器全部 inactive。
**AutoDL 平台实例没有由脚本关机，用户仍需在网页选择关机；不要释放已有模型和环境。**

本轮新增合并工具的 7 项测试均通过，覆盖不改原记录、取消项替换、重复样本、缺失样本、
模型失败、配置变化、源码变化和题目变化；shell 语法及 `git diff --check` 通过。
原正式代码的 145 项测试结果见[可靠性验证](../notes/2026-10-12-scheme-a-reliability-changes.md)。

建议先冻结本次 34 题对照，然后按以下顺序开展新实验，**本轮没有继续自动启动这些实验**：

1. 先做小范围生成策略诊断：固定双方设置，分别验证 thinking 开关和精简提示，重点看完整
   RTL 产出率、截断、L0 与输出成本。不要同时更换模型、提示和反馈格式后混算增益。
2. 再做 E1：共享首次生成条件、固定总时间/token，比较简短错误分类、结构化摘要、完整日志，
   看编译错误的修复收益和功能错误的局限。当前结果不是 E1 的反馈格式消融。
3. 生成与反馈基线稳定后再做 E2 的“两候选 vs 单路径修复”，不直接扩大 ToT/多 Agent 搜索。

每题 1 个样本只足以建立初步对照。采用新策略前，应在同一冻结题集上重复测量；不能仅凭
2 道改善题或 1 次整体得分差异就断言某方法稳定有效。
