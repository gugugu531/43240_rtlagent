# RTL 生成与独立行为检查

本方案根据公开题面生成 Verilog/SystemVerilog，在本地模型服务与 Vivado 工具链上完成生成、检查和有限修复，输出 `solution.v`。适用于 FPGA 创新设计大赛 AMD RTL/HLS 本地智能体设计赛道的 RTL（寄存器传输级）方向。

默认工作流 `guided_verify` 让同一 Qwen3.8-27B 模型承担三个角色。策略角色先读题，决定是否做行为检查，并为解题角色选技能。解题角色读取原题、接口与所选技能，生成 RTL。独立检查角色根据公开题面编写带简短说明的测试点，程序生成测试台并用 Vivado xsim 采样。解题角色可以采纳或拒绝检查建议，提交当前稿、修改 RTL，或请检查角色复核一个测试点。三个角色分别构造请求上下文。参考答案和官方测试台只用于求解结束后的独立判定。

主办方使用说明按 2026-10-31 核对的固定版本编写。本文与 Markdown 报告描述当前三角色工作树。实验数据注明其运行版本，排版报告保留 11 月 3 日的历史版本。[主办方版本 fc8e26a](https://gitee.com/Vickyiii/rtlagent2026/tree/fc8e26a/) · [设计与实验报告](REPORT.md) · [机器可读配置](manifest.json) · [历史排版报告](report/report.pdf) · [排版源码](report/readme.md)

## 默认配置

| 项目 | 配置 |
| --- | --- |
| 主模型 | Qwen3.8-27B，GGUF（llama.cpp 模型文件格式），Q4_K_M 量化，未自行微调 |
| 推理后端 | llama.cpp HIP（AMD GPU 计算后端），固定源码 `f114f91` |
| 推测解码 | 同进程加载 Q4_0 的 MTP（多 token 预测）头，最多预测 3 token |
| 上下文 | 65536 token；FP16（16 位浮点）键值缓存；单并发 |
| 思考设置 | `enable_thinking=true`、`reasoning_effort=medium`；方案与基线共用 |
| 单题预算 | 900 秒，其中预留 60 秒收尾；最多 8 次模型生成调用、65536 输出 token |
| 技能 | 每题都经过策略选择，最多选 2 项求解技能。即使题目超出行为表支持范围，也能选技能。检查角色使用固定的检查方法 |
| 知识检索 | RAG（检索增强生成）默认关闭，不启动独立规划模型或文本向量服务 |
| 工具 | 接口检查、Vivado 编译与展开、综合、xsim 行为采样 |

策略、解题和检查角色每次请求的输出上限分别为 4096、16384 和 8192 token。初稿、修改、复核和格式纠正共用同一份时间、调用及输出预算。在共享预算内可多轮修复、复核和复检。

两份权重的下载地址、固定版本、SHA256 和实测显存见 [model/MODEL.md](model/MODEL.md)。2026-10-30 的设备显存快照为 23.67 GiB，包含主模型、MTP 和设备其他开销；这不是峰值测量。实测硬件为 Radeon Pro W7900D 环境，赛事要求仍按单卡 32 GB 总占用执行。

## 目录

```text
.
├── agent/          # Burr 工作流、模型调用、RTL 检查与运行记录
├── config/         # 默认及显式研究配置
├── skill/          # 通用 RTL 方法与固定行为检查方法
├── knowledge/      # 可选知识检索资源，默认不使用
├── serve/          # 本地推理服务与 HTTP 投题服务
├── model/MODEL.md  # 权重、推理配置及资源声明
├── docs/           # 架构、接口与扩展说明
├── tests/          # 单元测试与契约测试
├── run.sh          # 单题求解入口
├── run_baseline.sh # 主办方原样基线入口
├── baseline.py     # 主办方原样单次生成脚本
├── Dockerfile
├── manifest.json
└── REPORT.md
```

题库、参考实现和实验原始日志由开发工作区单独保存，不是运行依赖，不随方案提交。

## 准备环境

以下命令在方案仓库根目录执行。正式运行前需要准备：

1. 主办方基础镜像中的 AMD GPU 运行环境、HIP 版 llama-server 与配套 rocBLAS 库。
2. `requirements.txt` 中的 Python 依赖。
3. [MODEL.md](model/MODEL.md) 指定的主权重与 MTP 权重，提前下载并核对 SHA256。
4. Vivado 2026.1 的 `vivado`、`xvlog`、`xelab`、`xsim` 命令和有效授权。

依赖安装在断网评测之前完成：

```bash
python3 -m pip install -r requirements.txt
```

`Dockerfile` 固定主办方基础镜像，构建入口为：

```bash
docker build -t rtlagent:local .
```

基础镜像只在赛事平台可用；已有本地构建记录停在基础镜像拉取阶段，尚不能宣称完成干净容器复现。权重不进入 Git 或构建上下文，运行时挂载到 `/models`。容器准备、Radeon Cloud 环境及隧道配置见 [服务说明](serve/README.md)。

## 启动与单题运行

先加载实例的 Vivado 环境及授权，再启动推理服务。下列 `/models` 路径应指向已准备的权重：

```bash
export MODEL=/models/Qwen3.8-27B-Q4_K_M.gguf
export MTP_MODEL=/models/mtp-Qwen3.8-27B-Q4_0.gguf
export LLM_BACKEND=openai LLM_BASE_URL=http://127.0.0.1:8000/v1
export LLM_API_KEY=dummy
export MODEL_NAME=qwen38-27b-q4-k-m LLM_MODEL=qwen38-27b-q4-k-m
export AGENT_TMP=/var/tmp EDA_TMP=/var/tmp/eda SELFTEST_TMP=/var/tmp
./serve/start.sh
```

默认二进制为 `/opt/llamacpp/llama-server`，其他安装位置通过 `LLAMA_SERVER` 指定。`start.sh` 复用健康且模型别名匹配的服务；使用已有服务时还要核对实际权重、版本与 MTP 参数，健康响应不能完成这些核验。脚本不下载权重。

输入目录必须包含 `prompt.txt`，其中写明题目、模块名称与端口接口。赛事 RTL 题目的接口包含在题面中。输出目录每次使用新路径：

```bash
./run.sh /absolute/path/to/task /var/tmp/rtl-agent-output
./run_baseline.sh /absolute/path/to/task /var/tmp/rtl-baseline-output
```

两条入口使用同一推理服务与 `manifest.json` 的思考设置。基线只做一次直接生成，绕过智能体和技能包；`baseline.py`、`run_baseline.sh` 保持主办方原样。

输出包含 `solution.v` 与逐行 JSON 记录 `trace.jsonl`。只做结构检查时，Vivado 编译展开（lint）和综合（synth）都通过即可自动提交。选择行为检查时，解题角色看到逐点结果与历轮决定，显式决定交付哪一轮的当前稿。预算耗尽或运行中断时，优先交付最近一份 lint 和 synth 均通过的稿件，若没有则交付最近的完整 RTL。正常收尾时可用 `run/end` 的 `published_id` 和 `published_sha256` 核对磁盘文件，再按候选编号追溯检查结果。退出码 0 表示已有非空答案。没有可交付的稿件时，入口保留空 `solution.v` 并返回非零退出码。

在本地可用内置假模型（mock）运行默认工作流。它选择纯结构路线并生成占位 RTL。

```bash
LLM_BACKEND=mock ./run.sh /absolute/path/to/task /var/tmp/rtl-mock-output
```

即使未安装 Vivado，也能在记录中查看工具不可用及解题角色随后提交的决定。单次生成入口可另设 `AGENT_CONFIG=config/single_generate.yaml`。占位输出仅用于核对入口、路由和记录。

## HTTP 投题

在受保护的运行环境中提供 `FPGACHINA_TOKEN`，不要把令牌写入仓库。推理服务就绪后运行：

```bash
./serve/run_api.sh start
curl --noproxy '*' -H "Authorization: Bearer $FPGACHINA_TOKEN" \
  http://127.0.0.1:7860/v1/health
```

| 接口 | 用途 |
| --- | --- |
| `GET /v1/health` | 检查模型、配置与服务就绪状态；核对 `track=rtl` |
| `POST /v1/solve` | 接收题面，`mode` 为 `agent` 或 `baseline`，返回任务编号 |
| `GET /v1/jobs/{job_id}` | 查询状态、最终 RTL 与 trace |

模型端口 8000 与投题端口 7860 均绑定 `127.0.0.1`；Radeon Cloud 仅通过隧道发布 7860。任务串行执行，排队时间计入时限；同一进程内用相同的非空 `nonce`（请求去重标识）重试会返回已有任务。服务重启不会恢复内存中的任务，`done` 也不代表正确性通过。完整报文与运行维护说明见 [serve/README.md](serve/README.md)。

### 实时展示

如需现场展示，运行中的投题服务可用 `./serve/run_api.sh ui on` 开启免登录的只读工作台。打开同一端口的 `/ui` 即可观看题面、实际执行图、各版 RTL、检查结果和决策说明。具体的演示者选题、题源切换和页面关闭命令见[工作台使用说明](serve/README.md#实时工作台)。新工作流的接入方式见[实时事件接口](docs/live-events.md)。

## 验证记录与限制

| 记录 | 结果 | 适用范围 |
| --- | --- | --- |
| 2026-10-30，`45caf971`，公开 VerilogEval 145 题 | L3 120、L1 14、L0 11；L3 比例 82.76% | 排除官方已知缺陷 11 题；旧阶段预算，无同批基线，不是当前提交成绩 |
| 2026-10-31，恢复修复候选，3 题 | L3 2、L1 1 | 当时使用检查器 150 秒的配置 |
| 2026-10-31，`1615689`，自编 AND/OR 各 1 题 | 两题均 L3；分别完成回环和本机公网 POST | 简单题服务及检查流程验证，不外推完整题集 |

L0 表示未达到编译通过；L1、L2、L3 分别表示主办方自测中的编译通过、仿真通过、综合通过。上述结果来自开发期保存答案后的独立判定，均不是正式赛事成绩。当前版本尚无同配置全题集基线对照，不能据此给出正式归一化增益。

2026-11-18 的三角色验收在两道自编题上用固定模型回复走通 7 个入口场景，覆盖自动提交、带失配提交、改稿复检和预算或信号中断后的交付。Vivado 2026.1 实际执行 7 次 xsim，累计比较 14 个已知位。这批记录验证了流程机制，真实模型调用和官方重评次数均为 0。

行为检查支持接口可解析的组合逻辑和明确的单正沿时钟设计，默认最多 4 个测试点、每点 8 行。同一模型在不同角色下可能共同误解题意，有限输入的比较也会漏掉边界条件。三角色在同配置题集上的收益、自由编写测试台与行式表格的相对效果均待实测。[检查表语法、判定和示例](docs/guided-verify.md)

## 进一步阅读

- [设计报告](REPORT.md)：相关工作、实现、实验与失败分析。
- [模型声明](model/MODEL.md)：版本、哈希、显存和推理参数。
- [架构与接口文档](docs/index.md)：工作流与模块扩展。
- [技能包](skill/README.md)：技能用途、状态及开源来源。
- [主办方自测说明](https://gitee.com/Vickyiii/rtlagent2026/blob/fc8e26a/selftest/README.md)：独立判定与公开题集说明。
