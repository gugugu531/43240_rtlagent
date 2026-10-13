# 20261012-225403-autodl-qwen3-8b-a-fixed-quick34-460c1d2a

原始记录：`/home/cloudia/FPGACHINA/AMD_SocChina_2026/43240-agent/dev/runs/20261012-225403-autodl-qwen3-8b-a-fixed-quick34-460c1d2a`。

<!-- BEGIN:results -->
状态：cancelled。完成 68/68 个样本。

本文件由 dev/tools/run.py 生成，不要手改。逐样本证据见 samples/。

| 模式 | 样本 | 官方等级分布 |
| --- | ---: | --- |
| agent | 34 | {'L0': 9, 'L1': 3, 'L3': 17} |
| baseline | 34 | {'L0': 8, 'L1': 3, 'L3': 18} |
<!-- END:results -->

## 改动与假设

日期：2026-10-12 启动，2026-10-13 按用户要求暂停；时间均为东京时间。
本轮实现与验证见[可靠性改动记录](../notes/2026-10-12-scheme-a-reliability-changes.md)。

- 题集：VerilogEval quick-34，agent 与原始 baseline 各 1 次，求解与评分并发均为 1。
- 模型：自托管 Qwen3-8B，提交 `b968826d9c46dd6066d109eabc6255188de91218`。
  远端 NVIDIA vGPU-48GB，vLLM 0.11.0、PyTorch 2.8.0+cu128、Python 3.12.3；
  最大上下文 32768、显存比例 0.85、Qwen3 默认 thinking 设置未改。
- 双方采样参数：temperature 0、top_p 1、max_tokens 8192、单次请求上限 300 秒。
  Agent 每题总预算 360 秒、预留 20 秒、最多一次代码补救。
- 本地 Vivado 2026.1，器件 `xczu3eg-sbva484-1-e`。官方 testbench 仅用于开发评分，
  没有输入求解上下文。
- 提示模板、提取策略及模型调用次数仍不同，因此这是完整求解方式比较，不是单个 Node 消融。
- 工作区为 dirty；源码证据在运行目录 `source/manifest.json`，不得仅靠 git 提交号复现。

## 结论

**状态：用户主动暂停，尚未完成 quick-34，不发布全量增益。**

后续更新：2026-10-13 已完成剩余 5 题补跑，原始暂停记录保持不变。
完整 34 题的合并结果及逐题分析见
[补跑与完整报告](20261013-105000-autodl-qwen3-8b-a-fixed-quick34-resume-4e464cbc.md)。
以下数字仍仅描述本次暂停时保留的 29 题。

上方生成块中的“完成 68/68”表示调度器对所有计划项完成了收尾，不表示 68 个样本都
完成求解和评分：实际为 **58 个有效样本，即 29 题完整配对**；其余 10 项为 `cancelled`，
judge 为 `skipped`。`summary.json` 的 `full_comparison_valid=false`、`gain=null`。
不得将这 10 项按 L0 计入 34 题分母，也不得覆盖原始记录伪装为全量完成。

已完成的 29 题中，模型调用失败为 0，正式运行期间 gateway 未记录传输重试或 HTTP 错误。
以下数字仅描述已完成子集，不是 quick-34 正式成绩：

| 模式 | 有效样本 | L0 | L1 | L2 | L3 | 官方系数均值 | 求解总耗时 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| agent | 29 | 9 | 3 | 0 | 17 | 0.6069 | 4102.12 秒 |
| baseline | 29 | 8 | 3 | 0 | 18 | 0.6414 | 1792.61 秒 |

系数按仓库 SCORING.md：L0=0、L1=0.2、L2=0.7、L3=1。L3 表示官方功能测试及综合
均通过；agent 内部 `synth_passed` 不代表官方功能正确。双方均为每题一次采样，不据此
宣称多次重复的稳定性或 pass@5 收益。

目前 agent 的 44 次模型请求有 17 次长度截断，baseline 的 29 次请求有 5 次。
Agent 输出 tokens 合计 195268，baseline 95313。已完成 agent 样本的停止原因：
`synth_passed` 20 题、`extraction` 7 题、`code` 2 题。
例如 `Prob109_fsm1` 两次回复都截断在未闭合 `<think>` 中，没有完整 RTL；
该类失败不能误判为网络异常，也不能认为增加修复轮数必然改善。

## 暂停与资源核实

- 2026-10-13 00:32:45 收到本地服务停止信号，00:32:47 实验以 `cancelled` 收尾。
- `Prob123_bugs_addsubz` 双方已经完成评分；`Prob131_mt2015_q4` 的 agent 生成中断。
- 00:33:18 vLLM 停止；随后核实远端 GPU 显存 0 MiB、利用率 0%，没有 vLLM 服务或 worker。
- 本地 experiment、transport、gateway、阻止休眠服务和 warning/cutoff 定时器均已停止。
- 远端 watchdog 自动撤销时遇到非交互 SSH 的 `python3` 不在 PATH。
  本次已用 `/root/autodl-tmp/venvs/vllm011/bin/python` 手动核对 PID 标记、停止旧保护
  进程并移除其 pid 文件。下次启动前要处理该解释器路径问题，不能沿用旧计时器。
- 远端模型目录保留，本地原始结果未删除、未覆盖。**AutoDL 网页实例尚未关机**；
  用户仍需在平台选择关机以结束实例计算计费，不要释放或删除实例。

## 下次补跑清单

只补跑以下 5 题的 agent/baseline，共 10 个样本；这次中断中的结果不计入已完成集合。

1. `Prob131_mt2015_q4`
2. `Prob133_2014_q3fsm`
3. `Prob138_2012_q2fsm`
4. `Prob146_fsm_serialdata`
5. `Prob154_fsm_ps2data`

配置已保存为 [quick34-remaining-20261013.yaml](../../configs/quick34-remaining-20261013.yaml)。
它只是配置，不会自动开机或继续实验。下次须先启动实例，核对 SSH 地址、模型文件和环境，
对照本次源码快照确认正式求解代码未变化，重新安装截止保护、启动 vLLM 和 relay，
导出模型环境变量并加载本地 Vivado 环境，然后运行：

```bash
python3 dev/tools/run.py --config dev/configs/quick34-remaining-20261013.yaml
```

**不要直接重跑 `autodl_quick34.sh`：它会重新执行 smoke 和全部 34 题。**
若正式代码或生成设置改变，应另开变体实验，不能把新旧设置混合成一个成绩。
本次按 `(task_id, mode, sample_index)` 保留的 58 项与新运行有效的 10 项合并后，
再检查 34 题双方覆盖、工具和模型错误并生成完整报告；本次原始 `cancelled` 状态保持不变。
