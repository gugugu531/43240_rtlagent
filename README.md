# RTL 生成与独立行为检查

本方案根据公开题面生成 Verilog/SystemVerilog，在本地模型服务与 Vivado 工具链上完成生成、检查和有限修复，输出 `solution.v`。适用于 FPGA 创新设计大赛 AMD RTL/HLS 本地智能体设计赛道的 RTL（寄存器传输级）方向。

默认工作流为 `guided_verify`：同一 Qwen3.8-27B 模型分别负责规划、生成、检查表构造和错误归因；各阶段使用独立请求上下文。模型从公开题面提出输入与期望输出，程序生成测试台并执行比较。参考答案、官方测试台和官方判定反馈不进入求解过程。

使用说明与声明依据 [主办方仓库固定版本 fc8e26a](https://gitee.com/Vickyiii/rtlagent2026/tree/fc8e26a/)，核对日期为 2026-10-31；本文对应方案实现 `1615689`。设计依据、实验条件和失败分析见 [REPORT.md](REPORT.md)，机器可读配置见 [manifest.json](manifest.json)。完整排版报告见 [设计报告 PDF](report/report.pdf)，源码与编译说明见 [report/readme.md](report/readme.md)。

## 默认配置

| 项目 | 配置 |
| --- | --- |
| 主模型 | Qwen3.8-27B，GGUF（llama.cpp 模型文件格式），Q4_K_M 量化，未自行微调 |
| 推理后端 | llama.cpp HIP（AMD GPU 计算后端），固定源码 `f114f91` |
| 推测解码 | 同进程加载 Q4_0 的 MTP（多 token 预测）头，最多预测 3 token |
| 上下文 | 65536 token；FP16（16 位浮点）键值缓存；单并发 |
| 思考设置 | `enable_thinking=true`、`reasoning_effort=medium`；方案与基线共用 |
| 单题预算 | 900 秒，其中预留 60 秒收尾；最多 8 次模型生成调用、65536 输出 token |
| 技能 | 规划器从 9 项可用求解技能中最多选择 2 项；检查器另用固定检查方法 |
| 知识检索 | RAG（检索增强生成）默认关闭，不启动独立规划模型或文本向量服务 |
| 工具 | 接口检查、Vivado 编译与展开、综合、xsim 行为采样 |

生成及 RTL 修复单次上限为 16384 token；规划、检查器、归因的额度分别为 4096、8192、8192 token。它们共用单题预算，各阶段不保证都能用满上限。

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

输出包含 `solution.v` 与逐行 JSON 运行记录 `trace.jsonl`。详细记录位置由配置决定，可从 trace 的运行配置中查看。默认交付策略为 `last_written`：保存每次提取到的完整候选，结束时交付最后保存的一份。内部选稿与实际交付候选分别记录，不能假定交付稿已经通过全部检查。没有答案时保留空 `solution.v` 并返回非零退出码；退出码 0 只表示有非空答案。

不具备 GPU 或 Vivado 时，可显式检查单次生成入口：

```bash
AGENT_CONFIG=config/single_generate.yaml LLM_BACKEND=mock \
  ./run.sh /absolute/path/to/task /var/tmp/rtl-mock-output
```

此命令只验证入口和记录，不运行真实模型，也不验证默认工作流的行为检查或 RTL 正确性。

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

模型端口 8000 与投题端口 7860 均绑定 `127.0.0.1`；Radeon Cloud 仅通过隧道发布 7860。任务串行执行，排队时间计入时限；同一进程内重复的 `nonce`（请求去重标识）不重复求解。服务重启不会恢复内存中的任务，`done` 也不代表正确性通过。完整报文与运行维护说明见 [serve/README.md](serve/README.md)。

## 验证记录与限制

| 记录 | 结果 | 适用范围 |
| --- | --- | --- |
| 2026-10-30，`45caf971`，公开 VerilogEval 145 题 | L3 120、L1 14、L0 11；L3 比例 82.76% | 排除官方已知缺陷 11 题；旧阶段预算，无同批基线，不是当前提交成绩 |
| 2026-10-31，恢复修复候选，3 题 | L3 2、L1 1 | 检查器 150 秒的局部验证；当前发布配置为 180 秒 |
| 2026-10-31，`1615689`，自编 AND/OR 各 1 题 | 两题均 L3；分别完成回环和本机公网 POST | 简单题服务及检查流程验证，不外推完整题集 |

L0 表示未达到编译通过；L1、L2、L3 分别表示主办方自测中的编译通过、仿真通过、综合通过。上述结果来自开发期保存答案后的独立判定，均不是正式赛事成绩。当前版本尚无同配置全题集基线对照，不能据此给出正式归一化增益。

行为检查仅支持接口可解析的组合逻辑或明确的单正沿时钟设计，默认最多 4 组案例、每组 8 行。复杂时序、多时钟和覆盖不足仍是主要限制；独立请求也可能与生成阶段共同误解题意。RAG 开启对照尚未执行，技能和检索的单项收益尚未确认。

## 进一步阅读

- [设计报告](REPORT.md)：相关工作、实现、实验与失败分析。
- [模型声明](model/MODEL.md)：版本、哈希、显存和推理参数。
- [架构与接口文档](docs/index.md)：工作流与模块扩展。
- [技能包](skill/README.md)：技能用途、状态及开源来源。
- [主办方自测说明](https://gitee.com/Vickyiii/rtlagent2026/blob/fc8e26a/selftest/README.md)：独立判定与公开题集说明。
