# 43240-agent — RTL 赛道参赛方案

本目录是队伍 43240 的参赛方案，也是最终提交给赛事方的目录。方案读入一道题的题面，
调用本地部署的大模型生成 Verilog / SystemVerilog 代码，再用 Vivado 检查并反复修改，
最后输出 `solution.v`。

> **当前状态：** 智能体仍沿用主办方示例方案的三轮生成主流程，但已经拆出模型客户端、
> 代码提取、接口解析、候选数据、产物保存和工具运行模块，并为模型异常、路径契约、
> 候选落盘及子进程清理增加了测试。
> 模型和推理后端尚未最终确定，候选模型的 baseline 实测见
> `dev/notes/2026-09-24-baseline-sweep.md`。本文描述的是现有代码的实际行为；改进计划见
> 「已知局限」。

---

## 1. 目录结构

| 路径 | 作用 |
| --- | --- |
| `run.sh` | 单题入口：从任意当前目录读取一道题，输出代码和工具调用记录 |
| `run_baseline.sh`、`baseline.py` | 基线入口，赛事方提供，**不得修改** |
| `agent/main.py` | 智能体主流程：多轮「生成 → 检查 → 修改」循环、时间控制、记录 trace |
| `agent/llm.py` | 调用大模型，校验配置并标准化返回结果或异常 |
| `agent/extraction.py` | 结构化提取代码，识别目标模块、多草稿与截断回复 |
| `agent/interface.py` | 结构化解析 ANSI、非 ANSI 接口并输出逐字段差异 |
| `agent/candidate.py` | 定义候选 ID、来源、父子关系和代码哈希 |
| `agent/artifacts.py` | 原子更新最终答案，并在开发模式保存每轮候选 |
| `agent/tools.py` | 接口检查，以及带进程组清理和结构化结果的 lint、综合工具 |
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
| `<输出目录>/candidates/` | 开发模式下每个候选的代码和元数据 |
| `<输出目录>/selection.json` | 开发模式下当前选择的候选、哈希和选择原因 |

`run.sh` 无论成功失败都以退出码 0 结束，并保证两个输出文件存在。这样「没做出来」
（空文件）和「服务出错」能够区分开。`solution.v` 在运行开始时即创建为空文件，之后通过
同目录临时文件和原子替换更新，进程在模型或 Vivado 调用中被终止时也不会留下半个文件。

### HTTP 接口

评测当天，赛事方通过 HTTP 逐题投题。`serve/serve_api.py` 把每次请求写成一个临时
题目目录，调用 `run.sh`（`mode=baseline` 时调用 `run_baseline.sh`），再把结果返回。
接口格式见仓库根目录的 `docs/API_CONTRACT.md`。

```bash
export FPGACHINA_TOKEN=<令牌>
uvicorn serve.serve_api:app --host 127.0.0.1 --port 7860
```

它会在 `deadline_s - 5` 秒时主动结束 `run.sh`，返回当时已写出的结果，避免被赛事方
判为超时。

### 调用大模型

`agent/llm.py` 支持两种后端，由环境变量 `LLM_BACKEND` 选择：

- `mock`：不联网的假模型，按题面端口生成一个输出恒为 0 的空模块，只用来检查流程是否
  跑得通
- `openai`：任何 OpenAI 兼容的 `/chat/completions` 接口，开发时可以是商用 API，
  提交时必须是本地推理服务

模型客户端会校验环境配置，把超时、连接失败、HTTP 错误和响应格式错误统一转换成
`LLMError` 子类，并返回正文、token、`finish_reason`、模型名、请求 ID 和耗时等标准字段。
客户端本身不自动重试：它不知道本题还剩多少时间、是否已有可用候选，重试决策应由 Agent
控制流负责。`chat()` 支持为单次调用覆盖超时、输出 token 上限和温度，当前控制流仍使用
环境变量中的默认值。

---

## 3. 处理流程

```
prompt.txt ─► 读题 ─► 加载技能包、提示词
                          │
          ┌───────────────▼─────────────────────────────────────────┐
          │ 第 N 轮（最多 AGENT_MAX_ROUNDS 轮，默认 3）              │
          │                                                         │
          │ 1. 组装提示词：system.md + 题面                          │
          │    （第 2 轮起）+ 相关技能 + repair.md（上一轮代码与报错） │
          │ 2. 调用大模型，从回复中提取代码块                        │
          │ 3. 建立候选并原子更新当前答案                            │
          │ 4. check_interface  接口检查   不通过 → 带着报错进入下一轮 │
          │ 5. lint             xvlog+xelab 不通过 → 带着报错进入下一轮 │
          │ 6. synth            综合       通过 → 结束，输出本轮代码   │
          │                               不通过 → 带着报错进入下一轮 │
          └─────────────────────────────────────────────────────────┘
                          │
                          ▼
              solution.v（最后一次提取到的代码）+ trace.jsonl
```

检查按代价从低到高排列：接口检查是纯文本比较，几乎不花时间；lint 需要几秒；综合需要
几十秒。之所以把接口检查放在最前面，是因为端口名或模块名写错时，赛事方的测试台无法
连接这个模块，整题得 0 分，比功能写错（还能得 0.2 分）代价更大。

**各步的细节：**

- **技能注入**：第 1 轮不注入技能。之后每轮用上一轮的报错和题面去匹配各技能的
  `Log signatures`（日志特征字符串），命中的技能最多取 2 条，放进提示词。
- **提取代码**：识别 `verilog`、`systemverilog`、`sv` 等代码围栏和无围栏模块，优先选择
  包含目标顶层模块的完整代码，同时保留同一代码块中的辅助模块。提取结果会明确记录模块名、
  多代码块、冲突草稿和疑似截断；没有完整 `module ... endmodule` 时不创建候选。
- **候选记录**：每次成功提取都分配 `c001` 形式的 ID，记录轮次、来源、父候选和 SHA-256
  代码哈希。当前仍采用原有策略：最后一次成功提取的代码立即成为兜底答案；综合通过时把选择
  原因更新为 `synth_passed`。设 `AGENT_SAVE_CANDIDATES=1` 会额外保存全部候选。
- **接口检查**：ANSI 与非 ANSI 模块声明统一解析为 `InterfaceSpec`，记录来源、置信度、端口
  方向和位宽，并输出逐字段差异。`interface.txt` 有内容时以它为准，解析失败或不一致都会
  拦截。评测题集没有该文件时，从题面的规则化端口清单解析，但只作为提示；bugfix 题中嵌入
  的待修源码不会被误当作接口规格。
- **没有 Vivado 时**：lint 和综合都返回 `status=unavailable`（`rc=-1`），接口检查通过后
  直接输出代码，不会假装检查过。
- **工具运行**：每次 lint、综合都使用独立的本地临时目录和进程组，返回统一的
  `ToolResult`。状态明确区分 `ok`、`failed`、`timeout` 和 `unavailable`；超时时先结束
  整个进程组，短暂等待后仍未退出则强制结束，避免残留 Vivado 子进程。顶层模块名在写入
  Tcl 前会按 Verilog 标识符规则校验。
- **工具日志**：trace 只记录有限长度的摘要。设置 `AGENT_KEEP_WORK=1` 时保留每次调用的
  独立工作目录和 `lint.full.log` / `synth.full.log` 完整日志，并在 trace 中记录路径；默认
  情况下调用结束即删除工作目录。
- **时间控制**：每轮开始、lint 和综合之前，检查剩余时间（`AGENT_DEADLINE_S` 减去已用
  时间和 `AGENT_RESERVE_S` 余量），不够就停止。模型调用出错时也会停止。
- **最终输出**：综合通过时输出该轮代码；否则输出最后一次提取到的代码，即使它没有通过
  检查。每次选择都原子更新 `solution.v`，后续模型调用失败不会丢掉已有候选。
- **任何异常**都会被捕获并记入 trace，仍然写出 `solution.v`（可能为空）。

---

## 4. trace.jsonl 记录的内容

每行一个 JSON 对象，都带有时间戳 `ts`。`tool` 字段表示记录类型：

| `tool` | 何时写入 | 主要字段 |
| --- | --- | --- |
| `agent` | 开始、结束、出错、综合通过、提前停止 | `event`（start / done / error / accept / stop）、模型配置 |
| `env` | 开始时 | `vivado_available`：本机是否找到 Vivado |
| `skills` | 加载时、每次注入时 | 加载了哪些技能；本轮注入了哪些 |
| `llm` | 每次调用模型 | `round`、`tokens_in`、`tokens_out`、`finish`（模型返回的 `finish_reason`，`length` 表示输出被截断）、`elapsed_s` |
| `extract` | 每次解析模型回复 | `status`、`complete`、`target_module_found`、`module_names`、`multiple_blocks`、`suspected_truncation`、`diagnostics`；不记录代码正文 |
| `candidate` | 候选创建和选择时 | `candidate_id`、`parent_id`、`code_hash`、`reason` |
| `check_interface` | 每次检查接口 | `round`、`candidate_id`、`code_hash`、`status`、`blocking`、接口来源与置信度、逐字段 `differences`、`excerpt` |
| `lint`、`synth` | 每次调用 Vivado 工具 | `round`、`candidate_id`、`code_hash`、`command`、`status`、`rc`、`elapsed_s`、`excerpt`；调试保留目录时还有完整日志和工作目录路径 |
| `budget` | 时间不够而停止时 | `reason` |

trace 同时用于三件事：工程质量评分、赛事方核对生成结果是否确实来自模型、团队自己的
失败分析，所以是必需的。

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
| `LLM_MAX_TOKENS` | `4096` | 单次输出上限，须与 `MODEL.md` 一致 |
| `LLM_TEMPERATURE` | `0.2` | 采样温度 |
| `LLM_TIMEOUT_S` | `180` | 单次模型调用超时（秒） |
| `AGENT_MAX_ROUNDS` | `3` | 最多几轮 |
| `AGENT_DEADLINE_S` | `360` | 单题时间预算（秒），通过 HTTP 接口运行时由请求中的 `deadline_s` 覆盖 |
| `AGENT_RESERVE_S` | `20` | 为写出结果预留的时间（秒） |
| `AGENT_TMP` | 依次取 `EDA_TMP`、`/tmp` | Vivado 临时目录，必须在本地盘 |
| `AGENT_KEEP_WORK` | 未设置 | 设为 `1` 时保留每次 Vivado 调用的独立目录和完整日志，排查问题用 |
| `AGENT_SAVE_CANDIDATES` | 未设置 | 设为 `1` 时保存每个候选及 `selection.json`，只用于开发分析 |
| `RTL_PART` | `xczu3eg-sbva484-1-e` | 综合用的器件 |
| `RTL_TOP` | `TopModule` | 顶层模块名；未设置时从 `interface.txt` 中推断，推断不出则用 `TopModule` |
| `FPGACHINA_TOKEN` | 无 | 投题接口的令牌，`serve_api.py` 必须设置 |
| `MODEL_NAME` | 取 `LLM_MODEL` | 健康检查接口返回的模型名 |

---

## 7. 已知局限

以下是现有代码的不足，也是后续改进的方向：

1. **无法判断功能是否正确。** 赛事方的参考测试台不提供，lint 和综合通过只说明代码能
   编译、能综合，不说明功能正确。判定等级从 L1（可编译，0.2 分）到 L2（仿真结果与
   参考实现一致，0.7 分）是得分跨度最大的一步，而现有流程对此没有任何检查。
2. **每轮都重写整个文件。** 修改时让模型输出完整文件，没有区分「在上一版基础上局部
   修改」和「从头重写」哪种更合适。
3. **报错摘要比较粗糙。** `summarize_log()` 只按固定关键词（`ERROR:` 等）挑选日志行，
   不区分 lint 报错和综合报错。
4. **技能挑选只靠字符串匹配。** 第 1 轮不注入技能；之后只有报错中出现技能声明的特征
   字符串才会注入，最多 2 条。技能包目前只有 1 条。
5. **各轮平均分配时间。** 没有根据第 1 轮成功率最高这一点调整时间分配。
6. **模型错误尚无重试策略。** 模型客户端已经把请求超时、连接失败、HTTP 错误和响应格式
   错误统一转换成 `LLMError`；多轮循环收到错误后会停止，并返回循环内已有的最后一个候选。
   但第一次调用就失败时仍然只能输出空文件，也还没有根据剩余时间决定是否重试。客户端已
   支持单次调用覆盖超时，等统一时间预算完成后由控制流使用。
7. **依赖服务端把思考内容分开。** 混合思考模型（如 Qwen3）的思考过程如果留在回复正文里，
   提取代码时可能取到思考中的草稿。服务端需要加 `--reasoning-parser`（见第 5 节），
   或关闭思考。
8. **候选选择没有质量排序。** 候选的身份、父子关系、哈希和检查结果已经可以追踪，但当前
   仍直接选择最后一次成功提取的代码，没有比较多个候选的功能正确性或可靠程度。

---

## 8. 相对示例方案的改动

| 日期 | 改动 | 说明 |
| --- | --- | --- |
| 2026-09-22 | 新增 `dev/`、`.dockerignore` | 团队开发区，不随方案提交；不影响方案行为 |
| 2026-09-23 | trace 的 `llm` 记录新增 `finish` 字段 | 记录模型返回的 `finish_reason`，用于统计输出截断 |
| 2026-09-24 | `serve/vllm.sh` 新增 `VLLM_EXTRA_ARGS` | 传入额外的 vLLM 参数，默认为空，不改变原有行为 |
| 2026-09-28 | 重构模型客户端 | 校验配置，统一模型结果与异常，支持单次调用参数覆盖；不自动重试 |
| 2026-09-30 | 固定 `run.sh` 相对路径语义 | 切换到方案目录前固定输入输出路径，支持从任意当前目录调用 |
| 2026-09-30 | 增加候选与原子落盘 | 记录候选谱系和代码哈希，开发模式保存全部候选，异常时保留已有答案 |
| 2026-09-30 | 加固 Vivado 工具运行 | 统一工具结果，超时清理整个进程组，分离日志摘要与调试完整日志 |
| 2026-09-30 | 结构化代码和接口解析 | 报告截断与多草稿，解析 ANSI 和非 ANSI 端口，区分权威接口、题面提示和 bugfix 源码 |

可以用 `diff -r ../example . -x dev -x .dockerignore` 查看完整差异。
