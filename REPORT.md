# 队伍 43240 RTL 方案设计报告（草稿）

本文记录当前已实现的方案；默认模型与服务已按 2026-10-30 实例 31563 核对，尚无正式实测成绩。
所有“待填写”项须在最终提交前核实；本文不沿用示范方案的三轮流程、示例失败分布或占位测量值。
报告格式参考[上游报告模板](https://gitee.com/Vickyiii/rtlagent2026/blob/f7a8bd465c2a820e006c7a00ecc7df468974635b/REPORT_TEMPLATE.md)。

| 项目 | 内容 |
| --- | --- |
| 队伍 | 43240 |
| Track | RTL |
| 当前默认 Workflow | `single_generate`；`guided_verify` 与 RAG 为显式可选配置 |
| 当前默认模型与推理服务 | Qwen/Qwen3.8-27B，公开 GGUF Q4_K_M 权重，llama.cpp；核对范围见第 3 节 |

## 1. 设计目标

输入纯文本题面，生成 `solution.v`，记录每次模型与工具调用。正式评测不提供参考答案和
参考测试台，方案不读取开发题库中的判定材料；`interface` 可为空，接口信息由题面提供。

能力目标、归一化增益目标与墙钟预算的实测依据：待填写。

## 2. 总体架构

默认入口为 `run.sh` → `python3 -m agent.main` → 单进程 Burr 图。默认工作流为
`single_generate`，保持一次模型调用、baseline 提示与提取、不加载 Skill 或调用 Vivado。

`guided_verify` 是显式可选研究流程：规划 → 生成 → 接口/lint/综合 → 独立
key-case checker → 归因与有界修复 → 收尾。它只依据自身生成的检查和 Vivado 证据作有限修复；
检查不完整或环境失败不算功能通过。答案由宿主原子发布到 `solution.v`；未能得到答案时输出
空文件，停止与错误原因写入 trace。

RAG 是可选的显式路线：知识库提供 129 张卡片，支持 BM25 和 dense 检索；默认
`single_generate` 不启用它，`guided_verify` 默认关闭 RAG 卡片检索。它的运行预算和收益
仍需与正式期限、同模型环境分别验证。

HTTP 投题层独立于求解流程：立即返回任务编号，后台串行解题，通过查询接口取得结果。
nonce 用于重复投递去重，时限覆盖排队和执行；HTTP 服务与 Agent 共同管理任务进程清理。

## 3. 模型与推理服务

以下权重、服务和显存事实均取自 **2026-10-30 实例 31563**，公开来源核对也截至该日；
不代表其他同名部署、正式负载峰值或官方成绩。完整声明见 [MODEL.md](model/MODEL.md)。

| 项目 | 当前声明 |
| --- | --- |
| 基座模型 | `Qwen/Qwen3.8-27B` |
| 量化权重来源 | https://huggingface.co/Abiray/Qwen3.8-27B-Q4_K_M-GGUF |
| 固定 revision | `f7a1cda580fe828415151042bf9f3dc5bb8b0d76` |
| 文件 | `Qwen3.8-27B-Q4_K_M.gguf`，16,810,714,400 bytes |
| 权重 SHA256 | `6a96cc760fc65cc6b9ea7f1922e3ff8b2a48c09f209456f23bbae9ef7032c867` |
| 参数量与格式 | 27,320,697,856（约 27.32B），GGUF Q4_K_M |
| 许可证 | Apache-2.0，公开量化仓库声明 `apache-2.0` |
| 推理栈版本 | llama.cpp `0.4.0-dev (build 1, commit f114f91)`，Clang 23，Linux |
| 服务二进制 SHA256 | `290708d22f8b495d36b8aedd0afb0cdc081c415548f855e6a950a75dd742ad97` |
| 服务地址与别名 | `http://127.0.0.1:8010/v1`，`qwen38-27b-q4-k-m` |

固定版本的完整公开下载 URL：

https://huggingface.co/Abiray/Qwen3.8-27B-Q4_K_M-GGUF/resolve/f7a1cda580fe828415151042bf9f3dc5bb8b0d76/Qwen3.8-27B-Q4_K_M.gguf

实例实际加载 `/root/models/qwen38-27b/Qwen3.8-27B-Q4_K_M.gguf`，实读 SHA256
与固定 revision 的 Hugging Face LFS 哈希一致；只加载文本 GGUF，未加载 mmproj。
量化工具与版本未知，不由推理后端版本推断。权重须提前准备，正式断网运行时不下载。

实例实际启动命令如下；本次声明核对不更换权重或重启服务：

```bash
/opt/llamacpp/llama-server \
  -m /root/models/qwen38-27b/Qwen3.8-27B-Q4_K_M.gguf \
  --alias qwen38-27b-q4-k-m --host 127.0.0.1 --port 8010 \
  --ctx-size 65536 --parallel 1 --n-gpu-layers all \
  --threads 16 --threads-batch 16 --flash-attn on \
  --no-webui --metrics --reasoning-budget -1
```

未使用 MTP draft 或额外 RoPE 覆盖。正式默认 `single_generate` 与 baseline 共用该服务，
上下文 65536、temperature 0.0、top_p 1.0、单次输出上限 16384 token、
manifest `generation.chat_template_kwargs.enable_thinking=true`，请求超时 840 秒、单题时限 900 秒。
这声明的是默认配置一致，不表示已完成同批次正式对照。

实例 31563 的 W7900 环境仅可见 `/dev/dri/renderD131`、`/dev/dri/card4`，
PCI `0000:63:00.0`。2026-10-30 服务加载后，sysfs 瞬时采样的总显存为 47.984 GiB、
已用为 22.457 GiB；进程采样中主模型为 19.590 GiB，已有但未参与默认流程的
embedding 进程为 2.412 GiB。GiB 按 2^30 bytes 计，设备占用包含该 embedding
及其他开销，不能扣除未参与求解的进程或用进程和替代设备值。health 的 0 不作为测量证据。
这些不是稳态或峰值测量，不能证明正式负载全程满足单卡 32 GB 限制；峰值与正式成绩仍待测。

`serve/start.sh` 为通用入口，默认模型路径 `/models/Qwen3.8-27B-Q4_K_M.gguf` 可用
`MODEL` 覆盖；`LLAMA_SERVER` 默认从 PATH 查找 `llama-server`，也可显式指定二进制路径。
默认端口 8010、`MAX_LEN=65536`，不再将旧 vLLM 显存比例示例当作当前部署。

## 4. 智能体、技能与基线

默认 `single_generate` 单次生成，不重试。入口进程管理硬期限，并在本次运行内保留已选择答案；
未完成的模型调用保留开始事件，不伪造完成记录。客户端停止不等于证明推理后端已取消请求。

可选 Workflow、工具与技能触发方式以仓库设计文档和实际运行记录为准。当前正式默认流程为
`single_generate`，不使用 Skill、RAG、工具或辅助模型；研究配置的技能来源、适用边界与消融实验仍待填写。

`baseline.py` 和 `run_baseline.sh` 按本地受保护原文件保留；基线不运行技能、工具或 MCP。

显式研究配置可用工具为 `interface_check`、`vivado_lint`、`vivado_synth`；技能目录保持现状。
研究角色 profile 可选择 `small` 规划及 `large` 生成/构造/复核/归因；小模型候选
`Nellyw888/VeriReason-Qwen2.5-1.5b-RTLCoder-Verilog-GRPO-reasoning-tb` 未纳入正式 manifest，
许可证与 flat plan 格式待确认。不能把研究 profile 的启用配置描述为当前正式默认服务。
提交策略当前为 last-write-wins，证据选稿的 `selected_id` 另行记录。
本地 baseline 已原样同步到上游 `f7a8bd4`，包含 `strip_think()` 和 manifest 思考声明加载；
输出上限 16384，单次请求上限 840 秒。方案采用同一思考声明，默认单题预算 900 秒。

## 5. 预算与记录

单题从投题开始计时，包含排队、输入准备、执行与清理。无法求解时返回空答案，
临时请求目录在后台求解结束后清理；详细记录需要配置独立的 `AGENT_RECORD_ROOT`。

trace 记录模型请求、token 用量、候选来源、工具结果与监督状态；未知用量保持未知。
HTTP 层可追加服务超时与异常类别。正式模型调用不得由 mock 结果替代。

## 6. 实测结果（待填写）

| 项目 | 待填写内容 |
| --- | --- |
| 题集与分母 | 题目清单、版本、是否剔除上游所列 11 道缺陷题 |
| 采样 | 每题采样次数；pass@1 计分，pass@5 仅作稳定性诊断 |
| 环境 | GPU、实测峰值显存、推理栈与 Vivado 版本、授权状态 |
| 基线与方案 | 同一次运行、同一模型和上下文下的 L0/L1/L2/L3 分布与题集得分 |
| 效率 | 从投题到查询到 done 的客户端墙钟；区分环境错误和模型失败 |
| 消融 | 同起点、同预算对照及逐题变化 |

按上游当前规则，归一化增益为：

```text
g = (方案题集得分 − 基线题集得分) / (1 − 基线题集得分)
增益得分 = 40 × min(g / 0.6, 1)，g ≤ 0 时为 0
基线为 1.0 时增益项计满分；基线为 0 时 g 等于方案题集得分。
```

模型之间的历史筛选数字、mock 流程验证和工具替身检查不填作本报告的正式能力结论。

### 6.1 开发期结构验证（非正式）

2026-10-28 在远端 llama.cpp `Qwen3.8-27B-Q4_K_M` + MTP 上各跑一道公开题：

| 工作流 | 墙钟 | 结果 |
| --- | ---: | --- |
| `single_generate` | 9.6 秒 | 417 字节；本次输出 `xvlog` 报非 reg 赋值，未通过编译 |

当时 manifest 仍声明示例模型 Qwen3-8B，故当时该 27B 与声明不一致；该记录未跑 xsim
或官方判定，只证明入口在当时真实服务上可运行，不能作为正式能力或成绩。
该旧 A 机同名 27B 使用不同权重，不是 2026-10-30 实例 31563 的当前权重；
本节保留历史结果，不将旧 MTP 配置、耗时或失败归入当前部署。

## 7. 失败分析（待填写）

待补充真实样本、输入版本、失败发生阶段、模型及工具证据、已尝试修复与反例。
分别讨论接口、功能、综合、输出截断、预算耗尽和运行环境失败；不把环境错误计成 RTL 错误。

## 8. 复现与封存

以实际官方基础镜像、固定 revision 的本地权重与预先安装依赖构建方案。完整使用说明见[仓库设计文档](docs/index.md)与开发区开发手册。
以下命令工作目录为方案仓库 `43240_rtlagent/`，须先准备第 3 节权重和匹配的服务二进制；
命令是复现说明，不代表已在其他环境运行或完成正式验收。

```bash
export MODEL=/models/Qwen3.8-27B-Q4_K_M.gguf
export MODEL_NAME=qwen38-27b-q4-k-m LLM_MODEL=qwen38-27b-q4-k-m
export PORT=8010 MAX_LEN=65536
export LLM_BACKEND=openai LLM_BASE_URL=http://127.0.0.1:8010/v1
# LLAMA_SERVER 默认使用 PATH 中的 llama-server；需要时指定实际安装路径：
# export LLAMA_SERVER=/absolute/path/to/llama-server
./serve/start.sh
./run.sh <input_dir> <output_dir>
./run_baseline.sh <input_dir> <baseline_output_dir>
```

远程投题另用 `./serve/run_api.sh start` 后台守护投题服务，经 `rc-tunnel` 暴露 7860；三个端点均校验赛事令牌。
封存目录与 Gitee 或 GitHub 私有仓库名为 `43240_rtlagent`。北京时间 2026-10-31 10:00 前完成默认分支
准备、协作者邀请和服务就绪；2026-11-04 18:00 前在大赛系统提交报告及同一仓库链接。
此处仅列要求，不表示已完成建仓、邀请、服务报送或系统提交。

## 9. 辅助模型

正式 manifest 的 `auxiliary_models` 为空列表，默认 `single_generate` 不使用辅助模型、
Skill 或 RAG，正式 agent 的 `tools` 与 `skills` 也为空。基线不含辅助模型。

实例 31563 在 2026-10-30 采样时已有常驻 embedding 进程，但不参与当前流程；
其瞬时显存 2.412 GiB 已包含在设备总占用 22.457 GiB 中，不能作为未加载辅助进程的证据。
该进程不是正式默认模型依赖，也不以其存在推断 RAG 已启用。

仓库 `guided_verify` 的 `small` profile、8011 服务与 RAG 仅是显式研究配置。
既有小模型候选名称、基座、参数量、用途和未验证边界见 `model/MODEL.md` 第 6 节；
其许可证为空、flat plan 与运行显存未验证，未纳入正式默认部署。
若后续正式启用，须先补充 manifest、许可、权重及训练来源声明，并验证合计显存，
不能沿用当前无辅助模型的声明。

## 10. 演示视频（待完成）

须在 Radeon Cloud 界面演示服务启动、投题到产出与判级、工作流设计及创新点，
时长和格式按大赛要求，与设计报告一并提交。

## 11. 公开数据与训练来源（待填写）

公开数据和开发期在线 API 生成的数据可用于训练，正式运行必须本地断网。
实际采用的训练数据来源、生成方式、规模、最终权重与许可证待按封存方案填写。

## 12. 大模型协作记录（待填写）

开发辅助模型与工具的名称和版本、创新点来源、队伍自己的判断、正确与错误建议、
发现错误的过程，以及用于验证设计的工具、测试、对拍和真实测量证据，均待补录。
本次流程验证不作为 GPU 实测或正式能力结论。
