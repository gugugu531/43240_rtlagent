# 20261012-180247-autodl-qwen3-8b-a-quick34-paired-2c614f88

原始记录：`/home/cloudia/FPGACHINA/AMD_SocChina_2026/43240-agent/dev/runs/20261012-180247-autodl-qwen3-8b-a-quick34-paired-2c614f88`。

<!-- BEGIN:results -->
状态：completed。完成 68/68 个样本。

本文件由 dev/tools/run.py 生成，不要手改。逐样本证据见 samples/。

| 模式 | 样本 | 官方等级分布 |
| --- | ---: | --- |
| agent | 34 | {'L0': 22, 'L1': 2, 'L3': 10} |
| baseline | 34 | {'L0': 17, 'L1': 3, 'L3': 14} |
<!-- END:results -->

> **有效性结论：本次 34 题全量结果无效，不可用于方案优劣对比。** 本机网络切换导致
> `Prob105` 的 baseline 以及此后 11 道题的双方模型请求失败。断连前 22 个有效配对
> 只能作为 workflow 诊断子集：agent 0.4636，baseline 0.6636。

## 改动与假设

- 日期：2026-10-12。
- 题集：仓库内 VerilogEval `quick`，34 题，每题 1 个样本。
- 对比：方案 A `evidence_repair` 与仓库 baseline，串行求解和串行评分。
- 模型：本地部署的 `Qwen3-8B`，模型提交
  `b968826d9c46dd6066d109eabc6255188de91218`；两组通过同一个 vLLM 服务调用。
- 远端环境：NVIDIA vGPU-48GB（49140 MiB）、Python 3.12.3、
  PyTorch 2.8.0+cu128、vLLM 0.11.0；vLLM 最大上下文 32768，GPU
  利用率上限 0.85。
- 本地工具：Vivado 2026.1，器件 `xczu3eg-sbva484-1-e`。
- agent 参数：temperature 0.2、max tokens 4096、单次模型超时 180 秒，
  最多重试请求 1 次；baseline 参数：temperature 0、max tokens 8192、
  超时 300 秒。
- 运行时没有把 testbench 提供给模型；最终等级由仓库评测器统一判定。
- 运行记录对应 git 提交 `d03f0fd`，但工作区为 dirty，且
  `source_complete=false`。因此本次记录可用于诊断，不应视作已经封存的可复现实验。

## 执行情况

正式运行从东京时间 19:02:46 开始，19:47:02 收尾。调度器完成了 68/68
个样本并完成 68/68 次 judge，但“样本完成”只表示执行流程已经收尾，不代表模型请求成功。

正式运行前做了两层检查：

1. 10 次短请求全部获得 HTTP 成功响应，平均 2.314 秒、最大 2.952 秒。
   其中 6/10 因 128 token 上限截断在思考内容中，因此它只能证明服务连通，不能证明
   生成质量稳定。
2. 1 道题的 agent/baseline smoke test 均为 L3，证明模型调用、RTL 提取、Vivado
   检查与 judge 的整条链路可以跑通。

## 基础设施异常

东京时间 19:46:49，本机活动网卡 `ens33` 丢失 carrier，网络到 19:47:05
才恢复。此时正在执行 `Prob105_rotate100` 的 baseline 请求，得到
`RemoteDisconnected`；从下一题开始，本地 18000 端口得到 `Connection refused`。

这不是远端模型崩溃：远端 vLLM 日志没有 OOM、异常退出或服务错误，并继续处理已收到的
请求；它直到五小时保护器触发时才在北京时间 21:10:00（东京时间 22:10:00）正常关闭。
故障点是本机到 AutoDL 的 SSH relay 在网络切换后消失，而当前 relay 没有自动重启。

受影响的样本如下：

- `Prob105_rotate100`：agent 请求成功并得到 L1；baseline 请求在传输中断开，L0 无效。
- 从 `Prob106_always_nolatches` 到 `Prob154_fsm_ps2data` 的最后 11 题：两组都没有
  一次成功模型响应，全部 L0 无效。

所以开头自动生成的 34 题分布必须保留作原始记录，但不能用来判断方案 A 的最终效果。

## 原始 34 题统计（包含断连样本，不可作为正式结论）

| 模式 | L0 | L1 | L3 | 系数均值 | 求解耗时总和 |
| --- | ---: | ---: | ---: | ---: | ---: |
| agent | 22 | 2 | 10 | 0.3059 | 1502.59 s |
| baseline | 17 | 3 | 14 | 0.4294 | 1152.02 s |

自动摘要中的 agent/baseline gain 为 0.7124，但该值混入了 23 个无模型响应样本
（agent 11 个、baseline 12 个），不能用于论文、汇报或后续消融对比。

## 传输有效的 22 个配对样本（仅作诊断）

只有前 22 题满足“agent 与 baseline 都至少有一次成功模型响应”。这一子集是按故障发生
时间截取的，并非随机抽样，因此仍不是正式 quick-34 成绩。

| 模式 | L0 | L1 | L3 | 系数均值 | 平均求解耗时 |
| --- | ---: | ---: | ---: | ---: | ---: |
| agent | 11 | 1 | 10 | 0.4636 | 65.23 s |
| baseline | 5 | 3 | 14 | 0.6636 | 50.56 s |

这个诊断子集上，agent/baseline 为 0.6986；agent 平均耗时高约 29%。配对结果为：

- agent 更好：1 题，`Prob075_counter_2bc`（L3 对 L1）。
- agent 更差：6 题，`Prob017_mux2to1v`、`Prob041_dff8r`、
  `Prob043_vector5`、`Prob062_bugs_mux2`、`Prob087_gates`、
  `Prob101_circuit4`。
- 同为非零等级：10 题。
- 同为 L0：5 题。

这说明当前方案 A 暂时没有表现出优于单次生成 baseline 的趋势，但由于只运行 1 个样本、
后 12 题缺失、两组生成参数也未完全对齐，这一结论只能用于决定下一轮改进方向。

## Workflow 诊断

方案 A 的本地检查确实工作了，但“发现错误之后如何继续”存在明显缺口：

- 20 份候选通过接口检查，12 份通过 lint 和综合并以 `synth_passed` 结束。
- 共有 8 次 lint 失败；只有 1 次被归类为可修复的 `code`，其余 7 次被标为
  `unknown` 并立即停止。比如 `Prob017_mux2to1v` 已得到 Vivado 的明确错误
  “procedural assignment to a non-register”，但分类器没有把它送入修复节点；该题
  agent 为 L0，baseline 为 L3。
- Workflow 共 5 次进入代码修复：1 次最终综合通过（`Prob003_step_one`），另 4 次
  在第二轮回复中没有提取到完整 RTL，最终停止。
- 28 次成功模型响应中有 8 次以 `finish_reason=length` 结束；4 个样本最终因 RTL
  提取失败停止。Qwen3 默认思考会消耗输出预算，agent 的 4096 token 上限是一个重要
  混杂因素。
- agent 与 baseline 使用了不同 temperature、输出 token 上限和提示模板。本次比较是
  “完整 workflow 对当前 baseline”的系统比较，不是某一个 Node 的纯消融实验。

## 下一轮实验要求

在继续 E1/E2 或完整消融前，应先完成以下 P0 修改：

1. 把 SSH relay 交给带 `Restart=always` 的用户服务管理，并在每道题前或请求失败后做
   健康检查与自动重连；连接失败样本必须标记为 excluded/infra error，不能计成 L0。
2. 扩充 Vivado 错误分类，至少识别 `VRFC 10-1280`（过程赋值目标类型错误）和
   `VRFC 10-9336`（ANSI 端口重复声明），让明确的编译错误进入修复循环。
3. 修复轮提取失败时保留上一份可用候选，不要用空结果覆盖已有代码；同时限制思考或提高
   输出预算，避免修复内容被截断。
4. 做两组实验：先将两边 temperature、max tokens 对齐，得到“工具/修复循环”的公平
   消融；再保留各自最佳参数做系统上限比较。
5. 修改完成后重新跑完整 quick-34，而不是把这次 22 题子集与未来结果直接拼接。正式对比
   至少使用多个随机种子，并在运行前提交或完整快照当前源码。

## 结论

本轮达成了“自托管 Qwen3-8B + 方案 A + Vivado + VerilogEval judge”的端到端验证，
并暴露出两个比继续堆叠 RAG、ToT 或 Reflexion 更优先的问题：基础设施断线没有自愈，
以及编译错误分类/修复闭环覆盖不足。

当前不能发布一个有效的 quick-34 对比成绩。断连前 22 个有效配对中，方案 A 为 0.4636，
baseline 为 0.6636，提示应先修复基础 workflow，再开展 E1/E2 和高级方法消融。
五小时保护已于东京时间 22:10:22 执行，vLLM 已关闭，GPU 显存占用为 0 MiB；AutoDL
实例是否停止计费仍需在网页控制台确认。
