# 43240-agent — RTL 赛道参赛方案

本目录是队伍 43240 的参赛方案，也是最终提交给赛事方的目录。方案读入一道题的题面，
调用本地部署的大模型生成 Verilog / SystemVerilog 代码，再用 Vivado 检查并反复修改，
最后输出 `solution.v`。

> **当前状态：** 已建立 Registry、Python Workflow、Node、逐题运行上下文和运行器。
> 默认 Workflow 为 `single_generate`，采用近似 baseline 的单次生成策略，不加载技能或执行工具。
> `repair_loop` 提供可选的多轮检查与修复。模型、动作、候选和检查都有来源记录。
> 模型与推理服务仍未最终确定，真实模型测评和统一实验入口尚未完成。
> 设计与进展见 [框架文档](dev/docs/readme.md)。

---

## 1. 目录结构

| 路径 | 作用 |
| --- | --- |
| `run.sh` | 单题入口：从任意当前目录读取一道题，输出代码和工具调用记录 |
| `run_baseline.sh`、`baseline.py` | 基线入口，赛事方提供，**不得修改** |
| `agent/main.py` | 单题参数解析与已注册 Workflow 选择 |
| `agent/runner.py` | 单次求解初始化、异常处理、最终结果与记录关闭 |
| `agent/context.py` | 本题状态、Node 执行与显式选择答案的公开接口 |
| `agent/workflows/` | 默认单次生成、可选修复循环及用户实验 Workflow |
| `agent/nodes/` | 生成、提取、接口、lint 与综合动作 |
| `agent/prompting.py` | 组装直接生成或修复提示，以及可选技能注入 |
| `agent/core/` | 模型、任务、组件、检查与结果契约，以及注册表、预算和运行元数据 |
| `agent/services/` | 模型与工具服务；模型不自动重试，工具按需初始化 |
| `agent/extraction.py` | 结构化提取代码，识别目标模块、多草稿与截断回复 |
| `agent/interface.py` | 结构化解析 ANSI、非 ANSI 接口并输出逐字段差异 |
| `agent/candidate.py` | 定义候选 ID、来源、父子关系和代码哈希 |
| `agent/artifacts.py` | 原子更新最终答案，并在开发模式保存每轮候选 |
| `agent/tools.py` | 接口检查，以及带进程组清理和结构化结果的 lint、综合工具 |
| `agent/recording/` | 保存完整模型证据、关联提取结果、写入 trace 并统一脱敏 |
| `agent/skills.py` | 加载技能包，按工具报错挑选相关技能 |
| `agent/prompts/` | 提示词：`system.md`（写代码的要求）、`repair.md`（出错后如何修改） |
| `skill/` | 技能包，每条技能一个目录，格式见 `skill/README.md` |
| `serve/serve_api.py` | 评测当天赛事方投题用的 HTTP 接口 |
| `serve/vllm.sh` | 启动本地推理服务的脚本（示例使用 vLLM，见第 5 节） |
| `model/MODEL.md`、`manifest.json` | 模型与方案的声明，须如实填写 |
| `REPORT.md` | 设计报告（尚未编写，目前是示例原文） |
| `Dockerfile`、`requirements.txt` | 基于官方基础镜像构建运行环境 |
| `dev/` | 团队开发文档与测试脚本，**不随方案提交**（已被 `.dockerignore` 排除） |

---

## 2. 运行方式

### 单题入口

```bash
./run.sh <题目目录> <输出目录>
./run_baseline.sh <题目目录> <输出目录>     # 基线，参数相同
```

| 文件 | 说明 |
| --- | --- |
| `<题目目录>/prompt.txt` | 题面。模块名和端口清单写在题面里 |
| `<题目目录>/interface.txt` | 模块声明。**评测题集不提供**，读不到时按空处理 |
| `<输出目录>/solution.v` | 生成的代码。做不出来时是空文件 |
| `<输出目录>/trace.jsonl` | 工具调用记录，每行一个 JSON 对象，见第 4 节 |
| `<输出目录>/records/<run_id>/` | 默认完整模型记录；也可以配置到独立根目录 |
| `<输出目录>/candidates/` | 开发模式下每个候选的代码和元数据 |
| `<输出目录>/selection.json` | 开发模式下当前选择的候选、哈希和选择原因 |

`run.sh` 无论成功失败都以退出码 0 结束，并保证两个输出文件存在。这样「没做出来」
（空文件）和已有答案能够区分开，错误类别另记入 trace。`solution.v` 在运行开始时即创建为空文件，之后通过
同目录临时文件和原子替换更新，进程在模型或 Vivado 调用中被终止时也不会留下半个文件。

### HTTP 接口

评测当天，赛事方通过 HTTP 逐题投题。`serve/serve_api.py` 把每次请求写成一个临时
题目目录，调用 `run.sh`（`mode=baseline` 时调用 `run_baseline.sh`），再把结果返回。
接口格式见仓库根目录的 `docs/API_CONTRACT.md`。

```bash
export FPGACHINA_TOKEN=<令牌>
uvicorn serve.serve_api:app --host 127.0.0.1 --port 7860
```

HTTP 外层为 `run.sh` 设置超时并读取已写出的答案。当前对整个子进程树的统一取消仍待实现。

### 调用大模型

`agent/services/model.py` 支持两种后端，由环境变量 `LLM_BACKEND` 选择：

- `mock`：不联网的假模型，按题面端口生成一个输出恒为 0 的空模块，只用来检查流程是否
  跑得通
- `openai`：任何 OpenAI 兼容的 `/chat/completions` 接口，开发时可以是商用 API，
  提交时必须是本地推理服务

模型服务用 `ModelRequest` 接收 messages、输出上限、温度、超时和用途，返回 `ModelReply`。
超时、连接失败、HTTP 错误、非法 JSON 与响应格式错误通过 `ModelCallError.kind` 区分。
每次调用分配 `m001` 形式的 ID，未知 token 用量为 `null`，mock 不伪造 HTTP 响应或用量。
服务不自动重试。实际调用超时取 Node 上限、服务上限与本题剩余时间中的较小值。
采样参数由 Python Workflow 构造 Node 时显式传入，服务配置不再承担采样策略。

开发记录默认使用 `full`。每次运行在 `<输出目录>/records/<run_id>/` 中创建独立记录：

```text
run.json
calls/m001/
  request.json       # 请求 messages、实际参数与公开服务配置
  response.txt       # 原始 HTTP 响应文本（脱敏后；mock、无响应时不生成）
  response.json      # 可解析的完整 JSON，包括 reasoning 和服务扩展字段
  content.txt        # 供代码提取使用的正文
  result.json        # 标准回复或分类错误
  extraction.json    # 提取状态、诊断与候选 ID
nodes/e001/execution.json
candidates/c001/{solution.v,metadata.json}
checks/k001/result.json
task.json
selection.json
```

设 `AGENT_RECORD_ROOT=/绝对路径` 可将记录保存到输出目录以外。HTTP 服务也继承此设置；
因此请求临时目录被删除后，记录仍然保留。HTTP 默认不持久保存临时目录中的完整记录。
设 `AGENT_RECORD_LEVEL=basic` 只写必要 trace。直接运行 Python 入口也可以使用
`--record-root` 和 `--record-level`；这两个选项不改变 `run.sh` 的两个位置参数。
所有记录均使用脱敏后的副本，模型实际收到的请求和用于提取的回复不受修改。

---

## 3. Workflow 与扩展

默认 `single_generate`：

```text
题面与可选接口 → 一次直接生成 → 提取候选 → 显式选择并保存答案
```

默认温度为 `0.0`，输出上限为 `8192`，Node 超时上限为 `300` 秒；服务超时默认 `180` 秒，
实际调用受本题预算约束。生成提示不注入技能，不执行接口、lint 或综合检查，不进行重试。
官方 baseline 仍由原版 `baseline.py` 执行；Agent 的模型名、提取器和记录方式有自己的契约。

可选 `repair_loop`：

```text
生成 → 提取 → 保存并选择候选 → 接口检查 → lint → 综合
 ↑                         检查失败时携带诊断与上一份代码返回
```

该 Workflow 默认最多 3 轮、温度 `0.2`、输出上限 `4096`；反馈中的技能选择、提示和候选选择
沿用拆分前的策略，工具不可用或模型失败时停止。它仍选择最新提取候选，候选质量排序留待下一阶段。

选择流程：

```bash
# run.sh 默认使用 single_generate
LLM_BACKEND=mock ./run.sh ../tasks/ex03_lfsr8 /tmp/out

# 两个位置参数不变，通过运行条件选择可选流程
LLM_BACKEND=mock AGENT_WORKFLOW=repair_loop ./run.sh ../tasks/ex03_lfsr8 /tmp/out-repair

# Python 入口也可直接选择，并显式导入用户扩展模块
python3 -m agent.main --input <task_dir> --output <out_dir> \
  --workflow <registered_name> --import-module <module_path>
```

组件只在注册表中登记类，构造时再创建实例。Workflow 用 Python 定义循环、条件与异常处理，
通过 `build_node(name, **params)` 选择动作并传参，经过 `ctx.execute(node, input)` 执行。
新增实验 Workflow 与 Node 也放在 `agent/`，运行代码不依赖 `dev/` 或官方判定信息。

上下文提供模型、工具、预算、只读状态与候选操作。保存候选不会自动选择答案；Workflow 必须
调用 `ctx.select_candidate()`，并用 `ctx.finish()` 返回与已落盘选择一致的结果。
运行器支持 Workflow 工厂，在每题调用工厂创建新实例。构造参数、实现路径与实际执行动作自动记录。
完整接口和扩展示例见 [Python Workflow 接口](dev/docs/design/python-workflows.md)。

预算使用单调时钟，模型与工具调用获得剩余时间内的超时上限。它是合作式时间控制，尚不能终止
任意 Python 阻塞操作。未处理的普通异常会记录并保留已选答案；必要 trace 写入失败仍明确报错。

---

## 4. trace.jsonl 记录的内容

Agent trace 当前使用 schema version 3。每行一个 JSON 对象，并自动带有以下公共字段：

| 字段 | 含义 |
| --- | --- |
| `schema_version` | trace 格式版本，当前为 `3` |
| `run_id` | 本次 Agent 运行的标识，同一文件内保持一致 |
| `seq` | 从 1 开始连续递增的事件编号 |
| `ts` | 写入事件时的 Unix 时间戳 |
| `tool` | 事件来源或类别 |

各类事件自己的字段如下：

| `tool` | 何时写入 | 主要字段 |
| --- | --- | --- |
| `run` | 记录初始化与运行元数据 | 记录等级、题目 ID、Workflow 描述、服务与预算配置、Git commit 与 dirty 状态 |
| `node` | 动作开始与结束 | `execution_id`、父执行、组件参数、输入输出摘要、状态、耗时与错误详情 |
| `workflow` | 流程自定义事件 | 决策理由、提示资源哈希及自定义诊断 |
| `agent` | 开始、结束、出错、综合通过、提前停止 | `event`（start / done / error / accept / stop）、模型配置 |
| `env` | 开始时 | `vivado_available`：本机是否找到 Vivado |
| `skills` | 加载时、每次注入时 | 加载了哪些技能；本轮注入了哪些 |
| `llm` | 调用开始与结束 | `event=started/succeeded/failed`、`call_id`、`purpose`、`tokens_in`、`tokens_out`、`finish_reason`、`elapsed_s`、错误分类与证据引用 |
| `extract` | 每次解析模型回复 | `status`、`complete`、`target_module_found`、`module_names`、`multiple_blocks`、`suspected_truncation`、`diagnostics`；不记录代码正文 |
| `candidate` | 候选创建和选择时 | `candidate_id`、`source_call_id`、`parent_id`、`code_hash`、`reason` |
| `check_interface` | 每次检查接口 | `check_id`、`candidate_id`、统一状态、`blocking`、接口详情与摘要 |
| `lint`、`synth` | 每次调用 Vivado 工具 | `check_id`、`candidate_id`、`command`、统一状态、`rc`、耗时、摘要及可用日志路径 |
| `budget` | 时间不够而停止时 | `reason` |

`agent/recording/` 在写入前统一隐藏 API key、Cookie、Authorization、已知秘密与 URL
中的凭据。原始正文保存在详细记录中，trace 只保存摘要与引用；必要 trace 写入失败视为
基础设施错误。详细文件写入失败只发出警告并标记 `recording_incomplete`，不会替换原有模型
结果或错误。进程中途退出时只保留实际已发生的事件，不伪造调用结束。

`dev/eval/analyze.py` 按调用结束事件统计模型耗时、按调用 ID 统计调用次数，避免把开始和
结束重复计数；主办方 baseline 的 trace 仍可分析。未知用量的汇总只代表已知用量之和。
格式见 [记录格式](dev/docs/design/trace-schema.md)。

trace 同时用于三件事：工程质量评分、赛事方核对生成结果是否确实来自模型、团队自己的失败
分析，所以是必需的。主办方 baseline 文件保持不变，其 trace 继续按官方原格式输出。

---

## 5. 推理服务

比赛不限定推理后端，只要求服务提供 OpenAI 兼容的 `/v1/chat/completions`，能在单张
32 GB 显卡上、断网条件下运行，且方案和基线使用同一个服务。`serve/vllm.sh` 是示例方案
使用 vLLM 的启动脚本，**团队尚未确定最终使用的后端**。确定后，这里、`serve/` 中的
启动脚本、`manifest.json` 和 `model/MODEL.md` 会同步更新。

服务只能监听 `127.0.0.1`，不能对外暴露；对外只暴露投题接口的 7860 端口。

`serve/vllm.sh` 通过环境变量设置：`MODEL`（权重路径）、`PORT`、`MAX_LEN`、`GPU_UTIL`，
以及 `VLLM_EXTRA_ARGS`（额外的 vLLM 参数，默认为空，例如 `--reasoning-parser qwen3`）。
服务参数同时影响方案和基线，最终采用的参数要写进 `model/MODEL.md`。

已验证的情况（2026-09-24，AMD Radeon Cloud 的 W7900，gfx1100）：vLLM 0.16.1 能正常运行
BF16、AWQ、GPTQ 4 位（包括 MoE）模型；Qwen3 系列必须加 `--reasoning-parser qwen3`，否则
思考内容会混进回复正文，基线分数明显下降。决赛硬件 R9700（gfx1201）上尚未验证。
详见 `dev/decisions/0001-inference-backend.md`。

---

## 6. 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `LLM_BACKEND` | `mock` | `mock` 或 `openai` |
| `LLM_BASE_URL` | 无 | 模型服务地址，`openai` 后端必填 |
| `LLM_API_KEY` | 空 | 本地推理服务可以随便填 |
| `LLM_MODEL` | `mock-model` | 请求中使用的模型名 |
| `LLM_TIMEOUT_S` | `180` | 单次模型调用超时（秒） |
| `AGENT_WORKFLOW` | `single_generate` | 已注册 Workflow 名称 |
| `AGENT_DEADLINE_S` | `360` | 单题时间预算（秒），通过 HTTP 接口运行时由请求中的 `deadline_s` 覆盖 |
| `AGENT_RESERVE_S` | `20` | 为写出结果预留的时间（秒） |
| `AGENT_TMP` | 依次取 `EDA_TMP`、`/tmp` | Vivado 临时目录，必须在本地盘 |
| `AGENT_KEEP_WORK` | 未设置 | 设为 `1` 时保留每次 Vivado 调用的独立目录和完整日志，排查问题用 |
| `AGENT_SAVE_CANDIDATES` | 未设置 | 设为 `1` 时保存每个候选及 `selection.json`，只用于开发分析 |
| `AGENT_RECORD_LEVEL` | `full` | `full` 保存详细证据；`basic` 只保留必要 trace |
| `AGENT_RECORD_ROOT` | 输出目录下 `records/` | 独立记录根目录；HTTP 开发实验应设置到请求临时目录以外 |
| `AGENT_GIT_COMMIT` | 自动读取 | 镜像中没有 `.git` 时，由构建过程注入源码 commit |
| `AGENT_GIT_DIRTY` | 未知 | 与 `AGENT_GIT_COMMIT` 一起注入源码是否含未提交修改 |
| `RTL_PART` | `xczu3eg-sbva484-1-e` | 综合用的器件 |
| `RTL_TOP` | `TopModule` | 顶层模块名；未设置时从 `interface.txt` 中推断，推断不出则用 `TopModule` |
| `FPGACHINA_TOKEN` | 无 | 投题接口的令牌，`serve_api.py` 必须设置 |
| `MODEL_NAME` | 取 `LLM_MODEL` | 健康检查接口返回的模型名 |

温度、输出上限与轮数通过 Workflow 的 Python 构造参数设置；旧的 `LLM_MAX_TOKENS`、
`LLM_TEMPERATURE` 和 `AGENT_MAX_ROUNDS` 不再读取。正式提交时同步采样与模型声明。

---

## 7. 已知局限

1. 默认单次生成不验证代码，也不判断功能正确性；可选 lint、综合通过仅表示内部检查通过。
2. `repair_loop` 仍选择最新提取候选，尚无质量排序、重复检查复用或模型错误重试策略。
3. 修复仍返回完整文件，技能按日志字符串匹配，工具摘要仍较粗糙。
4. 预算尚无外层统一监督；HTTP 超时的子进程树回收与后端推理取消尚未完成。
5. 未实现 YAML 加载、统一实验入口、指标收集与历史重放。当前可以按注册名称运行单题流程。
6. 详细记录没有自动清理策略，且部分工具完整日志仍依赖 `AGENT_KEEP_WORK=1`。
7. 模型与服务尚未最终确定；混合思考模型需要合适的服务端正文与 reasoning 分离配置。

---

## 8. 相对示例方案的改动

| 日期 | 改动 | 说明 |
| --- | --- | --- |
| 2026-10-05 | Python Workflow、Node、Registry 与运行上下文 | 默认单次生成；可选修复流程；记录动作与构造参数 |
| 2026-09-22 | 新增 `dev/`、`.dockerignore` | 团队开发区，不随方案提交；不影响方案行为 |
| 2026-09-23 | trace 的 `llm` 记录新增 `finish` 字段 | 记录模型返回的 `finish_reason`，用于统计输出截断 |
| 2026-09-24 | `serve/vllm.sh` 新增 `VLLM_EXTRA_ARGS` | 传入额外的 vLLM 参数，默认为空，不改变原有行为 |
| 2026-09-28 | 重构模型客户端 | 校验配置，统一模型结果与异常，支持单次调用参数覆盖；不自动重试 |
| 2026-09-30 | 固定 `run.sh` 相对路径语义 | 切换到方案目录前固定输入输出路径，支持从任意当前目录调用 |
| 2026-09-30 | 增加候选与原子落盘 | 记录候选谱系和代码哈希，开发模式保存全部候选，异常时保留已有答案 |
| 2026-09-30 | 加固 Vivado 工具运行 | 统一工具结果，超时清理整个进程组，分离日志摘要与调试完整日志 |
| 2026-09-30 | 结构化代码和接口解析 | 报告截断与多草稿，解析 ANSI 和非 ANSI 端口，区分权威接口、题面提示和 bugfix 源码 |
| 2026-10-03 | 固定 trace version 1 | 增加公共事件字段、公开配置与 Git 元数据，统一隐藏秘密并兼容旧分析数据 |

可以用 `diff -r ../example . -x dev -x .dockerignore` 查看完整差异。
