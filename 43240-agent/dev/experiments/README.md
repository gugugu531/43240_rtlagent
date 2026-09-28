# experiments/

每次跑分一份记录。`eval/run_eval.py`、`remote/remote_selftest.sh` 和
`remote/submit_client.py` 运行结束时会自动生成，文件名就是运行编号
（`YYYYMMDD-HHMMSS-<标签>.md`）。

自动填写的内容：git commit 编号（以及当时是否有未提交的改动）、模型、运行参数、各模式
的得分与等级分布、增益，以及 `eval/analyze.py` 生成的失败原因分析（见
[`../eval/README.md`](../eval/README.md)）。**需要手动填写**的是「改动与假设」「结论」两节，没有结论的
记录用处不大。

原始文件在 `../runs/<运行编号>/`，不提交到 git。

## 记录中的术语

| 术语 | 含义 |
| --- | --- |
| agent / baseline | 两种运行模式：agent 是完整方案；baseline 是赛事方的基线脚本，不经过智能体和技能包，直接让模型生成一次 |
| L0 / L1 / L2 / L3 | 判定等级：L0 未通过，L1 可编译，L2 仿真结果与参考实现一致，L3 可综合。对应得分系数 0 / 0.2 / 0.7 / 1.0 |
| 题集得分 (pass@1) | 每道题所有采样的平均系数，再对所有题取平均。这是计分用的数字 |
| pass@5 | 每道题取 5 次采样中最好的一次，再取平均。只用来看结果是否稳定，不计分 |
| 增益 | 方案题集得分 ÷ 基线题集得分，占 40 分 |
| 环境失败 | Vivado 授权（license）问题、题目自带的测试文件有问题等，与方案无关，不计入平均分 |
| 请求耗时 | 模拟投题时客户端测得的从发请求到收到响应的时间，不包含本地判定的时间 |

## 运行索引

每条记录的详细数据和分析见对应文件。所有云端运行都在 AMD Radeon Cloud 的 W7900（gfx1100）
上完成，`gpu_memory_utilization` 0.62 模拟 32 GB。汇总和对比见
`../notes/archive/2026-09-24-baseline-sweep.md`，选型讨论见 `../decisions/0002-model-choice.md`。

| 运行编号 | 内容 | 主要结论 |
| --- | --- | --- |
| [20260923-203605-ref-full](20260923-203605-ref-full.md) | 参考答案跑全部题目，检查本机 Vivado 判定链路 | 155 题 L3；3 道题的测试台自带超时过短，参考实现也只能到 L1，已加入排除清单 |
| [20260924-110334-cloud-qwen3-8b-smoke](20260924-110334-cloud-qwen3-8b-smoke.md) | 云端第一次端到端跑通（smoke，agent 与 baseline） | 链路可用；失分主要是超时 |
| [20260924-113712-baseline-qwen3-8b-think](20260924-113712-baseline-qwen3-8b-think.md) | Qwen3-8B 开思考，无 reasoning parser，baseline（中途停止，63 题） | 0.486；思考内容混进回复，提取到草稿 |
| [20260924-120512-baseline-qwen3-8b-parser-merged](20260924-120512-baseline-qwen3-8b-parser-merged.md) | Qwen3-8B 开思考，加 reasoning parser，baseline 全题集 | **0.484**；同样 63 题上 0.486 → 0.695；300 秒超时是最大失分来源 |
| [20260924-200443-q-qwen3-8b-nothink](20260924-200443-q-qwen3-8b-nothink.md) | Qwen3-8B 关思考，quick 子集 | 0.476，没有超时 |
| [20260924-201123-q-qwen25-coder-32b-awq](20260924-201123-q-qwen25-coder-32b-awq.md) | Qwen2.5-Coder-32B-AWQ，quick 子集 | 0.541；慢，显存超 32 GB |
| [20260924-202620-q-qwen3-32b-awq-nothink](20260924-202620-q-qwen3-32b-awq-nothink.md) | Qwen3-32B-AWQ 关思考，quick 子集 | 0.618；慢，显存超 32 GB |
| [20260924-203451-q-qwen25-coder-7b](20260924-203451-q-qwen25-coder-7b.md) | Qwen2.5-Coder-7B，quick 子集 | 0.512，快 |
| [20260924-204635-full-qwen3-8b-nothink](20260924-204635-full-qwen3-8b-nothink.md) | Qwen3-8B 关思考，全题集 | **0.415** |
| [20260924-210230-q-qwen3-30b-a3b-gptq-nothink](20260924-210230-q-qwen3-30b-a3b-gptq-nothink.md) | Qwen3-30B-A3B-GPTQ-Int4（MoE）关思考，quick 子集 | 0.571，最快 |
| [20260924-210547-full-qwen3-30b-a3b-gptq-nothink](20260924-210547-full-qwen3-30b-a3b-gptq-nothink.md) | 同上，全题集 | **0.489**；单路约 79 token/秒 |

新增记录时在这里加一行。
