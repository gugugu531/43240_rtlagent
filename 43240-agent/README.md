# 43240-agent — RTL 赛道参赛方案

本目录是队伍 43240 的参赛方案，也是最终提交给赛事方的目录。方案读入一道题的题面，
调用本地部署的大模型生成 Verilog / SystemVerilog 代码，可选用 Vivado 检查并反复修改，
最后输出 `solution.v`。

当前默认 `single_generate` 复用官方 baseline 的 RTL 提示、采样和提取规则，不加载技能或执行工具。
正式入口通过独立 Worker 和 Supervisor 管理预算、进程和中断恢复；模型与推理服务尚未最终确定。

| 流程 | 用途 | 验证边界 |
| --- | --- | --- |
| `single_generate` | 单次生成，作为默认入口 | 请求与提取对齐 baseline；完成不代表功能正确 |
| `repair_loop`、`evidence_repair` | 多轮修复或最多一次结构化修复 | 使用自身接口、编译和综合证据；不读取官方判定 |
| `evidence_a0/a1/a2` | E1：结构化修复与资料检索对照 | 支持初始检查点重放；完整题集收益仍需独立验证 |
| `tool_feedback`、`spec_test_repair`、`behavior_divergence` | 可选实验：工具反馈、规格自测、双候选行为分歧 | 分别最多 2/3/4 次模型请求；默认入口不变，不以模型期望或候选一致性证明正确 |
| `search_initial`、`search_r1/r2/r2_guided/c2/c3` | E2：有限修复与独立候选对照 | 支持共享起点、停止点及显式随机种子；不是已确定的提交策略 |
| `single_generate_long_output` | 长输出额度对照，需显式导入扩展 | 改变输出和超时额度，不作为严格 baseline 请求等价结果 |

基本运行、模型连接和输出说明见下文；这些说明随方案包交付。开发工作区中可进一步阅读
[Quickstart](dev/docs/quickstart.md)、[User Manual](dev/docs/user-manual.md)和[文档索引](dev/docs/readme.md)。

---

## 1. 目录结构

| 路径 | 作用 |
| --- | --- |
| `run.sh` | 单题入口：从任意当前目录读取一道题，输出代码和工具调用记录 |
| `run_baseline.sh`、`baseline.py` | 基线入口，赛事方提供，**不得修改** |
| `agent/main.py` | 单题参数解析、配置装配与已注册 Workflow 选择 |
| `config/example.yaml` | 带逐项中文注释的配置示例，也是正式入口默认配置；组件参数由 Python Workflow 定义 |
| `agent/core/configuration.py` | YAML 校验、覆盖来源、服务与预算配置、共享运行描述装配 |
| `dev/tools/submission.py` | 按明确清单检查、暂存方案并在没有 dev 的目录中验证默认入口 |
| `dev/tools/run.py` | 开发侧统一任务选择、采样调度与可选指标入口 |
| `dev/tools/datasets.py`、`balance_datasets.py` | 题集转换与均衡筛选；题库位于仓库根目录 `tasks/<来源>/<题号>/`，选题只维护 TXT 清单，不随方案打包，见[题集说明](dev/docs/design/datasets.md) |
| `dev/tools/log_viewer.html` | 本地日志查看器，导入输出目录后查看节点、工具调用与完整响应 |
| `agent/core/supervision.py` | 独立 Worker、硬超时、信号清理、选择恢复与记录交接 |
| `agent/workflows/repair_loop.py` | 修复流程，自带候选选择 `choose()` 与失败处理 `decide()`，可由子类替换 |
| `agent/workflows/evidence_repair.py` | 方案 A；复用修复流程的检查和选择，只注入有限结构化诊断并最多修复一次 |
| `agent/workflows/spec_repair.py` | 三个可选实验入口，共用方案 A 首稿/检查点，但独立编排自测、修复和候选保护 |
| `agent/core/runner.py` | 单次求解初始化、异常处理、最终结果与记录关闭 |
| `agent/core/context.py` | 本题状态、Node 执行与显式选择答案的公开接口 |
| `agent/prompts/context.py` | 保留必须上下文，按真实 chat template 计数并装配可选完整片段 |
| `agent/core/tokens.py` | 每题 token 账本；未知保持未知，可选累计输入输出/输出限额 |
| `agent/core/diagnostic.py` | 自身工具诊断、工具与版本、错误码及可核实的候选行号 |
| `agent/core/replay.py` | 只含求解信息的初始检查点，核验输入/源码/工具身份并扣除共享成本 |
| `agent/workflows/evidence_ablation.py` | E1 三组，复用同一个修复循环；不使用 judge 选择候选 |
| `agent/services/knowledge.py` | 加载外置的已验证修复卡，按完整错误码、工具、版本及可选诊断文本条件检索 |
| `agent/workflows/` | 默认单次生成、可选修复循环及用户实验 Workflow |
| `agent/nodes/` | 生成、提取、接口、lint 与综合动作 |
| `agent/nodes/baseline.py` | `single_generate` 专用节点，导入未修改的 baseline 规则，保留原始题面和提取结果 |
| `agent/prompts/builder.py` | 组装直接生成或修复提示，以及可选技能注入 |
| `agent/core/` | 模型、任务、组件、检查与结果契约，以及注册表、预算和运行元数据 |
| `agent/services/` | 模型、工具、检查缓存和进程服务；模型不自动重试，工具按需初始化 |
| `agent/nodes/extraction.py` | 结构化提取代码，识别目标模块、多草稿与截断回复 |
| `agent/core/interface.py` | 结构化解析 ANSI、非 ANSI 接口并输出逐字段差异 |
| `agent/core/candidate.py` | 定义候选 ID、来源、父子关系和代码哈希 |
| `agent/recording/artifacts.py` | 原子更新最终答案，并在开发模式保存每轮候选 |
| `agent/services/vivado.py` | 带进程组清理和结构化结果的 lint、综合工具 |
| `agent/services/repair_feedback.py` | 摘要截断前收集自身工具根因、提供词法赋值导航，并保守比较顶层输出无驱动证据 |
| `agent/services/port_signature.py` | 警告修复专用的保守端口声明语义比较；不支持的声明视为未知 |
| `agent/services/behavior.py`、`timing.py`、`plan_format.py`、`literal_spec.py`、`spec_ports.py` | 可选规格自测基础：校验受支持端口、时序和计划，程序生成测试台并区分公开属性与模型假设；默认流程不调用 |
| `agent/nodes/behavior.py`、`agent/workflows/spec_selection.py` | 显式导入的计划/自测 Node 与可调用候选保护函数；不注册或启用新的 Workflow |
| `agent/recording/` | 保存模型与动作证据、trace、脱敏及通用运行/模型统计 |
| `agent/prompts/skills.py` | 加载技能包，按工具报错挑选相关技能 |
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
| `<详细记录目录>/candidates/<候选编号>.v` | `full` 模式保存候选代码；来源、父候选和哈希记录在 trace 的 `candidate/create` 事件中 |
| `<输出目录>/selection.json` | 恢复检查点，包含候选正文、来源、哈希和选择原因，所有模式均写入 |

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

HTTP 时间从请求处理开始计算，覆盖输入准备、执行、进程清理与结果读取，不再使用 5 秒超时下限。
Agent 的 Supervisor 管理 Worker 与通过公开服务启动的工具进程；shell 转发 SIGTERM。baseline
只增加外部进程组监督，原始脚本、模型提示和 trace 不变。

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
task.json
calls/m001/
  request.json       # 请求 messages、实际参数与公开服务配置
  response.json      # 可解析的完整 JSON 响应，包括 reasoning 和服务扩展字段
  response.txt       # 只在响应不是合法 JSON 或使用 mock 时代替 response.json
candidates/c001.v
process_logs/*.log    # Supervisor 保存的完整工具与进程输出，中断时也可保留
```

每份数据只保存一处：调用状态、提取结论、Node 执行、检查结果、选择和监督结果都只写在
trace 中，详细记录目录只放 trace 装不下的正文。检查结果用 `log_paths` 指向对应的进程日志。

设 `AGENT_RECORD_ROOT=/绝对路径` 可将记录保存到输出目录以外。HTTP 服务也继承此设置；
因此请求临时目录被删除后，记录仍然保留。HTTP 默认不持久保存临时目录中的完整记录。
设 `AGENT_RECORD_LEVEL=basic` 只写必要 trace。直接运行 Python 入口也可以使用
`--record-root` 和 `--record-level`；这两个选项不改变 `run.sh` 的两个位置参数。
trace、详细证据和工具日志使用脱敏副本，模型实际收到的请求和用于提取的回复不受修改。
输出目录的 `solution.v` 和恢复检查点保存实际代码，供中断恢复；它们不属于脱敏证据副本。

---

## 3. Workflow 与扩展

默认 `single_generate`：

```text
题面与可选接口 → 一次直接生成 → 提取候选 → 显式选择并保存答案
```

提示、温度 `0.0`、`top_p=1.0`、输出上限 `8192` 和请求上限 `300` 秒直接取自未修改的
`baseline.py`。该 Workflow 不接受采样参数覆盖；不同策略应另注册 Workflow。题面和可选接口
保留读取时的首尾空白，系统提示固定要求 `TopModule`，不采用 `RTL_TOP` 或接口推断的模块名。
HTTP 请求只发送 baseline 的字段，不附加 `stream` 或认证头。请求模型名依次取 `MODEL_NAME`、
`/models` 第一项和 `default`；`LLM_MODEL` 仍用于 mock、修复流程及实验配置。统一实验入口将
配置中的模型名通过 `MODEL_NAME` 显式传给两个模式，覆盖遗留环境变量。

提取直接调用 `baseline.extract()`：保留第一个匹配代码块，再提取 `TopModule`，找不到时
保留文本。残缺代码和纯说明也作为候选保存；正常响应的空内容写出一个换行，请求失败写空文件。
现有结构化提取器只提供回复诊断，不筛选或改写这一路径的答案。`completed` 表示流程完成，
不表示代码完整或正确。`repair_loop` 继续使用原来的提示、请求参数和结构化提取节点。

通过标准入口运行时，`services.model.timeout_s` 省略或为 `null` 表示按 Workflow 取默认值：
`single_generate`、`evidence_repair`、`evidence_a0/a1/a2` 为 300 秒，其余（包括 `search_*`）为 180 秒。显式服务上限和整题剩余预算仍可缩短调用，
Supervisor、中断恢复和原子写出保持生效。直接注入 `ModelConfig()` 仍显式使用其 180 秒上限。
模型发现最多等 30 秒，也受服务上限和剩余预算约束，耗时计入整题预算，不算一次生成调用。

等价性指相同 RTL 输入与模型服务、预算充足且正常 API 响应下的生成请求 JSON 和最终文件字节。
不要求复刻 baseline 的冗余模型查询、异常文本或进程中断行为；mock 只验证流程。HTTP 请求的
`request.json` 在 `request` 字段保存实际出站 JSON 的脱敏副本，另记实际超时、用途与请求类型。

长输出补测可显式导入 `agent.workflows.single_generate_long_output`，选择
`single_generate_long_output`。它复用上述生成、提取和保存过程，仅把单次输出上限改为
`32768`、请求超时改为最多 `900` 秒，并记录 `experiment_override` 事件。
实验配置还应显式设置 `services.model.timeout_s: 900` 和 `runtime.deadline_s: 960`；
服务上限与剩余预算仍会缩短请求。模型服务需要足够的上下文和缓存容量。
这是单独的额度对照实验，不属于严格 baseline 请求等价结果，也不改变默认流程或 `repair_loop`。

可选 `repair_loop`：

```text
生成 → 提取 → 保存候选 → 接口检查 → lint → 综合
 ↑             每步按已有证据更新选择；明确代码错误时反馈修复
```

该 Workflow 默认最多 3 轮、温度 `0.2`、输出上限 `4096`，每个请求最多重试 1 次、模型调用
总数最多 4 次。只有允许重试的模型连接、超时或 HTTP 错误才重试相同消息；服务本身仍只调用一次。
明确代码错误进入修复，超时、环境故障和未知错误默认停止，避免把基础设施问题当成 RTL 缺陷。
另有下述明确输出无驱动警告的有界修复；它不把综合成功伪装成编译失败。

最新候选、修复对象与最终答案分别管理。确认有代码或权威接口错误的候选不作为答案；其余候选
按真实综合、lint 和接口通过证据比较，同等证据保留已有选择。未知检查不当成通过；综合通过不代表
功能正确。相同源码与任务、配置、工具身份的确定性检查可在本题复用，记录引用来源而不重复调用工具。
自定义修复 Workflow 可继承 `RepairLoop`，覆盖 `choose()` 或 `decide()`，开展不同选择或失败处理实验。

`repair_loop` 默认在原有预算内尝试修复明确的顶层输出无驱动警告。新稿必须实际通过编译、综合，
受支持的端口声明语义保持不变，且完整诊断中的无驱动输出/位集合严格缩小，才替换旧稿。
替换检查单独比较 ANSI 端口的名称、方向、顺序、signedness（符号性）以及全部常量
packed/unpacked 范围（含边界方向）；只忽略 wire/reg/logic 类型修正、等价空白和显式 unsigned。
参数化、预处理、非 ANSI、其他类型、动态/表达式维度或可能的端口再声明均视为未知，保留旧稿；
通用接口解析器的 high 置信度不证明完整端口语义。诊断缺失、截断或格式未知时也保留旧稿。
警告减少不代表功能正确。可用 `repair_output_drivers: false` 关闭；`evidence_repair`、E1/E2
保持该警告触发关闭，共享的编译错误归因和修复提示更新仍适用。

另提供可选规格自测基础，现由 `spec_test_repair` 和 `behavior_divergence` 显式使用，
**不接入默认入口和已有 E1/E2 等流程**。显式导入
`agent.nodes.behavior` 可使用 `spec_test_plan` 和 `spec_behavior_check` Node；动作仍由 Workflow
通过 `ctx.execute()` 调度。计划只看公开题面与接口，完整支持格式的二值真值表可程序化枚举，
其他期望值均标为模型假设。程序校验后生成自己的测试台，不执行模型编写的测试代码或读取官方 TB。
自测仅支持无符号标量/一维降序向量；时序部分限单时钟、明确复位和唯一输出寄存器组。
可调用保护函数只依据同一计划下严格改善的受支持属性，保留旧的工具通过证据、端口语义和探针覆盖；
模型期望值分数不能单独推翻可编译候选。未知、计划拒绝、自测通过都不等于官方功能判定。
复位依据支持非相邻的原文段落，首次与末次复位检查都逐段验证；positive/negative edge
同样按时序规格处理。模型假设采样中的 X/Z 单独记录为不确定观察，不计入已判定断言或失配；
没有确定失配但存在不确定观察时，自测返回不可用。
开发接口、支持范围和限制见[规格自测基础](dev/docs/design/spec-test-foundation.md)。

三个新增实验入口分别为 `tool_feedback`（最多 2 次模型请求）、`spec_test_repair`（最多 3 次）和
`behavior_divergence`（最多 4 次），各最多修复一次、不自动重试；真值表枚举不占模型请求。
首稿共用方案 A 的消息和提取，不等同官方 baseline。直接启动保存 `initial.json`，也可恢复同一首稿，
恢复时扣除已有时间和 token 成本。修复稿完成必要检查后才参与选择；编译修复后必须进入所需的自测阶段。
双候选分歧只记录，不用投票或一致性裁决。规格组不以纯综合警告或综合代码错误绕过严格属性保护。
显式配置、调用和失败边界见[可选实验工作流](dev/docs/design/experimental-workflows.md)；尚无正式题集增益结论。

可选 `evidence_repair` 复用同一套候选选择和失败归因，但固定为一份初始候选加最多一次修复。它通过
`structured_feedback` Node 把提取或检查失败整理成证据编号、阶段、状态、归因、稳定错误码和有限摘要；
不读取完整日志、官方 testbench、参考答案或 judge 结果，也不启用技能、ICL、规划、反思和检索。

方案 A 使用与 baseline 相同的生成参数（8192 tokens、temperature 0、top_p 1、单次上限
300 秒），但保留自己的提示和结构化提取。最终实际超时仍受服务和整题剩余预算约束。
Vivado `VRFC 10-1280`、`10-9336` 等明确源码诊断会进入修复；环境故障优先单独归因。
如果修复没有完整代码或所有候选检查失败，方案 A 保留完整旧候选并标记
`failed_check_fallback`，不会把失败检查改成通过。原有 `repair_loop` 选择规则保持不变。

E1 的 `evidence_a0` 使用方案 A 同一首次提示与提取，只保留首份候选并执行自身检查；
`evidence_a1` 使用结构化反馈最多修复一次；`evidence_a2` 额外检索本地提供并经过独立小例子验证的
错误短卡，最多两张，按实际工具/版本和完整错误码匹配。卡片可要求同一错误的诊断文本包含指定内容，
不允许其他错误或 warning 代替该条件。未配置知识库、无法加载或无命中时不增加提示。
`runtime.initial_state` 可指定 A0 导出的 `initial.json` 做受控重放，核验输入、源码、工具身份，
复用自身检查并扣除共享首次时间与 token 成本，不读取官方 judge 或参考答案。
所有求解仍经 run.sh/Supervisor；开发实验和隔离判定在 dev 中调度。三组都是实验变体，默认流程未切换。

E2 的 `search_r1/r2` 最多修复一/两次，`search_c2/c3` 最多生成两/三份独立候选；
`search_initial` 保存初始检查点，`search_r2_guided` 按每轮自身错误检索外置短卡。
采样在 Python 中声明，默认 temperature=0.6、top_p=0.95、base_seed=20261013，逐次 seed 递增。
未配置知识库时不增加资料；通过 YAML 的 `services.knowledge.corpus_path` 指定本地资料，
缺失或格式错误时记录原因并继续原修复提示。资料内容单独提供，不随 Git 上传。
三次调用流程建立初始检查点后，会在第三次调用前或提前停止时保存 `stop_after_two.json`；
它记录共享前缀的真实状态，不额外调用模型，不可把共享成本重复相加。

上下文保留题面、接口、完整候选和反馈，可选资料按整段装配。`services.model` 下可设置
本地 tokenizer、上下文容量和累计 token 限额，默认不启用累计限额。未知用量不算零。
`enable_thinking` 只影响普通生成/修复请求；默认 `baseline_rtl` 不传该选项，计数也按模板默认值。

新增上下文、诊断、短卡检索和候选策略的接口约定见
[Agent 运行接口](dev/docs/design/agent-runtime.md)。

选择流程：

```bash
# run.sh 默认使用 single_generate
LLM_BACKEND=mock ./run.sh ../tasks/example/example_ex03_lfsr8 /tmp/out

# 两个位置参数不变，通过运行条件选择可选流程
LLM_BACKEND=mock AGENT_WORKFLOW=repair_loop ./run.sh ../tasks/example/example_ex03_lfsr8 /tmp/out-repair

# 方案 A：结构化反馈，最多修复一次（真实检查需要 Vivado）
LLM_BACKEND=mock AGENT_WORKFLOW=evidence_repair ./run.sh ../tasks/example/example_ex03_lfsr8 /tmp/out-evidence

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
完整接口和扩展示例见 [Python Workflow 接口](dev/docs/user-manual.md#10-python-组件与扩展)。

预算使用单调时钟，动作可设置最少启动时间，并为清理和写出结果预留时间。正式入口在独立 Worker
中运行 Python Workflow，Supervisor 在预算结束或收到信号时先 TERM、再 KILL 并回收受管理进程。
自定义外部动作使用 `ctx.processes.run(ProcessRequest(...))`；自行创建并脱离进程组的子进程不在保证范围。

选择先提交包含代码和哈希的原子检查点，再替换 `solution.v`；中断后校验并恢复。Supervisor 只在
Worker 停止后追加记录，不伪造模型或 Node 的结束。关闭模型连接不证明共享服务已停止推理，记录为 unknown。
用于依赖注入和单元测试的进程内 Runner 仍是合作式预算，不提供任意 Python 阻塞的硬停止。

---

## 4. trace.jsonl 记录的内容

每行一个 JSON 对象，以 `run_id`、递增 `seq`、Unix 时间戳 `ts`、类别 `tool` 和事件 `event` 关联过程。
代码版本记录于运行元数据中的 Git 短 commit；不另设 trace 格式版本。

| 需要追踪什么 | 事件与关联编号 |
| --- | --- |
| 配置、题目和记录目录 | `run/metadata`、`run/recording` |
| 模型请求和结果 | `llm/started/succeeded/failed`，以 `call_id` 关联 |
| 动作和嵌套步骤 | `node` 生命周期，以 `execution_id` 关联 |
| 提取、候选与最终答案 | `extract`、`candidate/create/select`，保留来源调用与候选编号 |
| 接口、lint、综合与复用 | 检查编号、状态及日志引用；复用不算新工具执行 |
| 决策、预算和结束清理 | `workflow`、`budget`、`supervisor/result` |

完整字段约定在开发工作区的[记录格式](dev/docs/design/trace-schema.md)维护。
没有结束事件的调用保持未知，模型正文和完整工具日志按引用保存于详细记录。

`agent/recording/` 在写入前统一隐藏 API key、Cookie、Authorization、已知秘密与 URL
中的凭据。原始正文保存在详细记录中，trace 只保存摘要与引用；必要 trace 写入失败视为
基础设施错误。详细文件写入失败只发出 `recording/warning` 警告，不会替换原有模型
结果或错误。进程中途退出时只保留实际已发生的事件，不伪造调用结束。

`dev/tools/analysis/analyze.py` 按调用结束事件统计模型耗时、按调用 ID 统计调用次数，避免把开始和
结束重复计数；检查开始与结束按 ID 合并，复用检查另计，只有开始事件的工具仍计为一次尝试。
主办方 baseline 的 trace 仍可分析。未知用量的汇总只代表已知用量之和。
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
详见 `dev/docs/notes/0001-inference-backend.md`。

---

## 配置与开发实验

默认使用 `config/example.yaml`，可通过 `AGENT_CONFIG` 或 run.sh 的附加 `--config` 参数选择。
该文件带有逐项注释，可复制到开发配置目录后修改。旧 `config/default.yaml` 已改名，显式引用旧路径的命令或 `AGENT_CONFIG` 需同步调整。
配置只选择 Workflow、外部服务和运行条件；采样与组件策略保留在 Python。
生效顺序为内置默认、YAML、支持的环境变量、CLI，trace 的运行元数据记录生效值和来源。

```bash
# 指定单题、重复采样，只收集模型和运行指标
python3 dev/tools/run.py --config dev/configs/smoke.yaml --task ex03_lfsr8 --samples 3

# 已连接真实模型服务后，同时运行 Agent 与原始 baseline 并进行官方判定
python3 dev/tools/run.py --config dev/configs/remote-smoke.yaml
```

指标选项为 runtime、model、judge；未选 judge 不启动判定。参考答案与判定结果不进入 Agent。
原始实验产物在 dev/runs/，新实验笔记集中放 dev/docs/experiments/。
配置字段、公开接口、产物和边界见[配置与实验说明](dev/docs/user-manual.md#12-开发实验与指标)。

## 6. 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `LLM_BACKEND` | `mock` | `mock` 或 `openai` |
| `LLM_BASE_URL` | 无 | 模型服务地址，`openai` 后端必填 |
| `LLM_API_KEY` | 空 | 本地推理服务可以随便填 |
| `LLM_MODEL` | `mock-model` | mock、修复流程及统一实验配置的模型名；直接运行 single_generate 使用 MODEL_NAME 或发现服务模型 |
| `LLM_TIMEOUT_S` | 按 Workflow | single_generate、evidence_repair、evidence_a0/a1/a2 默认 300 秒，其他 180 秒；显式值限制单次调用 |
| `AGENT_CONFIG` | `config/example.yaml` | YAML 配置路径；相对路径按调用者当前目录解析 |
| `VIVADO_BIN` | PATH | 显式 Vivado 可执行文件目录 |
| `AGENT_WORKFLOW` | `single_generate` | 已注册 Workflow 名称 |
| `AGENT_DEADLINE_S` | `360` | 单题时间预算（秒），HTTP 请求中的 `deadline_s` 只能缩小实际预算 |
| `AGENT_RESERVE_S` | `20` | 为清理和写出结果预留的时间（秒）；预算小于此值时直接停止 |
| `AGENT_TMP` | 依次取 `EDA_TMP`、`TRACK_TMP`、`/tmp` | Vivado 临时目录，必须在本地盘 |
| `AGENT_KEEP_WORK` | 未设置 | 设为 `1` 时保留每次 Vivado 调用的独立目录和完整日志，排查问题用 |
| `AGENT_RECORD_LEVEL` | `full` | `full` 保存详细证据；`basic` 只保留必要 trace |
| `AGENT_RECORD_ROOT` | 输出目录下 `records/` | 独立记录根目录；HTTP 开发实验应设置到请求临时目录以外 |
| `AGENT_GIT_COMMIT` | 自动读取 | 镜像中没有 `.git` 时，由构建过程注入源码 commit |
| `AGENT_GIT_DIRTY` | 未知 | 与 `AGENT_GIT_COMMIT` 一起注入源码是否含未提交修改 |
| `RTL_PART` | `xczu3eg-sbva484-1-e` | 综合用的器件 |
| `RTL_TOP` | `TopModule` | 顶层模块名；未设置时从 `interface.txt` 中推断，推断不出则用 `TopModule` |
| `FPGACHINA_TOKEN` | 无 | 投题接口的令牌，`serve_api.py` 必须设置 |
| `MODEL_NAME` | 未设置 | baseline 与 single_generate 的请求模型名；未设时发现服务模型；也用于健康检查返回值 |

single_generate 的采样常量固定；其他 Workflow 的温度、输出上限与轮数通过 Python 构造参数设置。旧的 `LLM_MAX_TOKENS`、
`LLM_TEMPERATURE` 和 `AGENT_MAX_ROUNDS` 不再读取。正式提交时同步采样与模型声明。

---

## 7. 已知局限

1. 默认单次生成不验证代码，也不判断功能正确性；可选 lint、综合通过仅表示内部检查通过。
2. 工具诊断只识别少数明确的代码错误，未知错误默认停止；完整日志支持继续分析。
3. 修复仍返回完整文件，技能按日志字符串匹配，工具摘要仍较粗糙。
4. 硬监督依赖 Linux；自由启动的脱离进程组子进程不受保证。共享模型服务的推理取消没有协议支持。
5. 已支持 E1/E2 初始检查点重放；通用历史完整流程重放、自动消融比较尚未实现。
6. 详细记录没有自动清理策略。强制中断可能没有完整的逻辑检查结论或留下临时工作目录，但保留已写的进程输出。
7. 模型与服务尚未最终确定；混合思考模型需要合适的服务端正文与 reasoning 分离配置。

---

## 8. 相对示例方案的改动

| 日期 | 改动 | 说明 |
| --- | --- | --- |
| 2026-10-11 | single_generate 对齐官方 RTL baseline | 复用提示、采样与提取规则；对齐模型选择和原始输入，保留日志、预算与监督；不改变 repair_loop |
| 2026-10-11 | 增加 evidence_repair 方案 A | 结构化有限诊断、最多一次修复；保留现有 Workflow 作为独立对照 |
| 2026-10-08 | 精简运行记录 | 去掉 txt/json 双份和与 trace 重复的文件；取消 trace 版本号，改记 Git 短 commit；删除 `save_candidates` |
| 2026-10-08 | 选择与失败策略下放到 Workflow | 删除 `agent/policies/`；检查结果分类改为 `CheckResult.classify()`；修复流程的决策结果不变 |
| 2026-10-08 | Quickstart、User Manual 与注释配置 | 文档按上手与完整使用拆分；默认配置改名为 `config/example.yaml`，默认运行值保持不变 |
| 2026-10-05 | 模块归位、开发目录集中与打包检查 | 正式运行独立于 dev；Docker 包含默认配置和原始 baseline 文件 |
| 2026-10-05 | YAML 配置与统一实验 | 单题、采样、并发与 runtime/model/judge 指标 |
| 2026-10-05 | 候选保护、失败处理、检查复用与独立监督 | 保留较强证据的答案；回收受管理进程；恢复中断选择和记录 |
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

## 提交目录检查

开发文档统一见 [dev/docs/readme.md](dev/docs/readme.md)，远程管理位于 dev/tools/remote/。

```bash
python3 dev/tools/submission.py --stage /tmp/agent-submission \
  --task ../tasks/example/example_ex03_lfsr8 --output /tmp/agent-submission-smoke
```

暂存目标必须不存在，且位于源码目录外。复制范围明确包含 Agent、默认配置、技能、服务、模型
声明、两个入口与原始 baseline.py；不复制 dev、任务、外置模型权重或缓存。清单与哈希保存在
暂存目录旁，独立 smoke 使用 mock，不读取开发配置。Dockerfile 也复制 config/ 与 baseline.py。
此检查不替代参考答案审核、模型与依赖准备、官方基础镜像构建或目标 GPU 验证。
