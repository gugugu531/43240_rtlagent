# 43240_rtlagent — RTL 赛道参赛方案

本仓库是队伍 43240 的方案与提交目录。方案读入题面，调用本地大模型生成
Verilog / SystemVerilog，输出 `solution.v` 和调用记录。模型与推理后端须按实际部署固定，正式实测结果尚未封存；
[manifest.json](manifest.json)、[MODEL.md](model/MODEL.md) 和 [REPORT.md](REPORT.md) 仍有待填写项。

本次主分支仅保留最近测试的五条工作流及其依赖，合入多稿比较和性质修复，保留设计检查器的有界原文恢复与精确诊断。
历史消融、旧候选搜索、初稿重放、长输出、额外采样与提取预设及其专用组件已移除。
本包沿用主分支的模型与服务声明，不把研究环境的模型身份或成绩写成正式验收结果；
真实部署前必须填写并核对 manifest 与 MODEL。后续云端测试只使用 AMD Radeon GPU，通过 SSH 连接。
有限仿真、mock 和既有研究记录均不能代替正式预算下的真实模型验收。

当前内置五个 Workflow（求解流程）、13 个 Node（动作）和 5 个 Tool（工具）：

| Workflow | 行为 | 验证边界 |
| --- | --- | --- |
| `single_generate`（默认） | 按官方 baseline 的提示、采样和提取规则生成一次 | 不加载技能、不运行工具；完成不代表功能正确 |
| `repair_loop` | 生成、提取、接口检查、lint（编译检查）、综合；默认最多生成 2 轮，即最多修复 1 次 | 只使用自身检查证据；不读取官方判定或参考答案 |
| `design_verify_loop` | 分开生成设计计划、RTL 和受限行为模型，审阅后用 Vivado 仿真比较，按归因修复并回归，最后综合 | 检查也可能有误；有限仿真及模型审阅不证明功能完全正确 |
| `behavior_search` | 独立生成多稿 RTL，共用输入运行 Vivado 仿真，匿名比较轨迹并按题面选择、修复或增加测试 | 相同输出不等于正确，不按多数投票；裁决属于模型审阅 |
| `property_repair_loop` | 从题面生成性质和输入序列，经审阅后由 Vivado 检查断言，对反例再次仿真，再决定修复 RTL 或性质 | 只覆盖实际执行的有限输入，仿真通过不称为形式证明 |

本仓库可独立部署和运行。题库、官方判定器、历史实验记录位于本仓库之外的开发工作区，均不属于运行依赖。

## 1. 准备与运行

需要 Python 3.10 或以上版本与 [requirements.txt](requirements.txt) 中的依赖。修复流程还需要可用的 Vivado 与授权；
真实模型运行需要预先准备本地权重和推理环境。正式运行断网，不能临时下载依赖、模型或扩展。

### 单题入口

以下命令均在本仓库目录执行；`run.sh` 也支持从其他当前目录调用，输入、输出和 `AGENT_CONFIG`
的相对路径按调用者当前目录解释。

```bash
# 检查单次生成流程，无需 GPU 或 Vivado
LLM_BACKEND=mock ./run.sh /path/to/task /tmp/rtl-out

# 使用有限修复；需要 Vivado，mock 只替代模型
LLM_BACKEND=mock AGENT_CONFIG=config/presets/repair_loop.yaml \
  ./run.sh /path/to/task /tmp/rtl-repair-out

# 官方基线入口，参数相同
./run_baseline.sh /path/to/task /tmp/rtl-baseline-out
```

`mock` 按题面端口生成输出恒为 0 的模块，只用于检查流程。真实运行选择 `openai` 后端，
连接提供 OpenAI 兼容 `/v1/chat/completions` 的本地服务：

```bash
# Qwen3-8B 是当前示例，替换为实际固定版本的本地权重
export MODEL=/models/Qwen3-8B
export MODEL_NAME=Qwen3-8B LLM_MODEL=Qwen3-8B
export LLM_BACKEND=openai LLM_BASE_URL=http://127.0.0.1:8000/v1
./serve/start.sh
./run.sh /path/to/task /tmp/rtl-out
./run_baseline.sh /path/to/task /tmp/rtl-baseline-out
```

| 输入与输出 | 说明 |
| --- | --- |
| `<题目目录>/prompt.txt` | 题面，包含模块名和端口要求 |
| `<题目目录>/interface.txt` | 可选模块声明；正式评测题集不提供，缺失时按空处理 |
| `<输出目录>/solution.v` | 最终答案；没有答案时为空文件 |
| `<输出目录>/trace.jsonl` | 必需调用记录，每行一个 JSON 对象 |
| `<输出目录>/selection.json` | 已选择答案的恢复检查点，包含实际代码、来源、哈希与原因 |
| `<输出目录>/records/<run_id>/` | 默认详细记录目录，可配置为独立根目录 |

正常进入求解后，`run.sh` 即使求解失败也以退出码 0 结束；错误类别写入 trace，不能用退出码判断代码正确性。
运行开始创建协议文件，答案通过原子替换更新；中断时恢复已提交的选择，没有候选才保留空答案。
输出目录须可写，调用前应使用新的输出目录。

### HTTP 投题与镜像

`serve/start.sh` 是常驻服务统一入口：检查已有推理服务，否则独立启动并等待就绪，同时启动本地 EDA
临时目录清理。HTTP 投题另外启动服务：

```bash
export FPGACHINA_TOKEN='<令牌>'
uvicorn serve.serve_api:app --host 127.0.0.1 --port 7860
```

使用默认的一个 uvicorn Worker，不使用多 Worker 或热重载。`POST /v1/solve` 返回 202 和任务编号，
`GET /v1/jobs/{job_id}` 查询 `queued`、`running` 或带答案与 trace 的 `done`；健康检查及请求示例见
[serve/README.md](serve/README.md)。三个端点均校验令牌。非空 `nonce` 用于重复投递去重，任务串行执行，
时限从投题起算并包含排队。任务与去重状态只保存在当前 HTTP 进程，重启后清空。

HTTP 层将题面写入临时目录，按 `mode` 调用方案或 baseline，再返回输出文件。默认不会在请求结束后
持久保存完整模型记录；需要留存时设置独立的 `AGENT_RECORD_ROOT`。健康检查是固定就绪响应，
不能代替模型、配置和单题链路验证。HTTP 响应保留请求 `task_id`，Agent 内部默认使用临时输入目录名。

`serve/` 四个文件采用上游 `f7a8bd4` 的官方示例。推理服务仅监听 `127.0.0.1`，通过 `rc-tunnel`
对外暴露投题接口 7860。方案和 baseline 必须使用同一个推理服务及上下文、思考设置。
`Dockerfile` 基于官方基础镜像，构建上下文为本仓库；镜像标签仍为占位项，构建时须指定实际镜像：

```bash
export OFFICIAL_BASE_IMAGE='替换为实际官方镜像地址与标签'
docker build --build-arg BASE_IMAGE="$OFFICIAL_BASE_IMAGE" -t 43240-rtlagent .
```

该命令是构建入口，不表示当前镜像、依赖或目标 GPU 已完成验证。

## 2. 当前流程与失败处理

### single_generate

```text
题面与可选接口 → 单次生成 → baseline 提取 → 选择并保存答案
```

生成 Node 直接复用未修改 `baseline.py` 的系统提示与常量：温度 `0.0`、`top_p=1.0`、
输出上限 `16384` token、请求上限 `840` 秒，不接受采样参数覆盖。保留原始题面与接口的首尾空白，
提示固定要求 `TopModule`，不采用 `RTL_TOP` 的推断结果。模型名依次取 `MODEL_NAME`、服务 `/models`
第一项与 `default`；`LLM_MODEL` 用于 mock 和修复流程。

提取直接调用 `baseline.extract()`：去掉思考段、取第一个匹配代码块，再提取 `TopModule`，找不到则保留文本。
残缺代码或说明文字仍可成为答案；正常空回复输出换行，请求失败输出空文件。结构化提取器只记录诊断，
不改写此流程的答案。`completed` 仅表示流程完成。

这里的 baseline 等价性指：相同 RTL 输入、模型服务、充足预算及正常 API 响应下，生成请求 JSON 与最终文件字节一致。
模型发现耗时计入整题预算，最多 30 秒且受服务上限约束；不要求复刻 baseline 的冗余查询、异常文字或中断行为。

### repair_loop

```text
生成 → 结构化提取 → 接口检查 → lint → 综合
 ↑       提取失败或明确代码错误时，在轮数内反馈修复
```

默认 `max_rounds: 2`，生成 Node 的默认装配参数为温度 `0.2`、输出上限 `4096` token、请求上限 `180` 秒。
轮数可通过配置修改；没有模型请求重试或工具重试。只有提取失败或明确归因的代码错误可进入下一轮；
模型错误、工具环境错误、未知故障、超时或预算不足时停止。接口的提示性差异允许继续，阻断差异停止后续检查；
lint 通过才综合，综合成功即停止，warning 不单独触发修复。

第一次提取出的非空候选立即保存为兜底。后续候选只有接口不阻断、lint 与综合均通过才替换答案；
后续失败或中断保留已有答案。兜底选择和失败证据分别记录，不把兜底标成检查通过。检查通过也不证明题目功能正确。
相同源码、任务、配置与工具身份下的确定性检查可在本题复用，未知指纹不缓存。

### design_verify_loop

通过 `config/presets/design_verify_loop.yaml` 选择。默认最多 3 轮 RTL、1 次检查模型修订。计划和检查各自从题面生成并独立审阅，公开题面片段有 `source_id` 和原始字符区间；引文只容许空白差异，不能改写事实。计划审阅明确返回 `accept`、`revise` 或 `reject`，接受与实质修改冲突时要求重新回答。解析、来源、期望自检或审阅失败，可在构造次数上限内带具体错误重试；无法构造检查时仍保留 RTL 和结构检查结果。

行为模型是受限 JSON 表达式，不执行模型生成的 Python 或测试台代码；固定驱动调用 Vivado 的 `xvlog`、`xelab`、`xsim`。`schema_version: 1` 保持旧单时钟格式兼容；无状态用 `state: {}`，组合逻辑用 `clock: null`。状态初值保持未知，复位必须在状态转移或显式异步复位契约中给出，驱动不会自动初始化期望值。生成和审阅均读取完整表达式语义；运行仿真前先求期望值并统计真实可比较位，全无比较的套件不能变成有效检查。

多时钟可用 `clocks: {clk_a: {edge: posedge}, clk_b: {edge: negedge}}`，每个状态写 `clock: clk_a`，每步用 `edges: [clk_a]` 指定活动沿，不能同时使用旧 `clock`/`edge`。同一步的多个沿共享更新前状态，不同步骤表示不同事件次序；每步末尾将时钟归回非活动电平。这是有界离散事件仿真，不表示任意频率、亚稳态或 CDC（跨时钟域）硬件安全证明。`async_resets` 可分别绑定复位端口、有效极性和不重叠的状态子集；复位断言先稳定，再运行所列活动沿。保持复位有效且没有相关沿时，状态保持，不反复求复位表达式。

`output_valid` 为输出指定 1 位有效条件，`output_masks` 为输出指定同宽比较位掩码，均只引用输入和模型状态。默认全部有效且比较所有位；忽略必须有题面依据，不能为迎合 DUT（待测实现）修改。必要位未知、有效条件未知、掩码未知分别报告，未定义位外的 X 不影响有效位比较。全被排除的采样不计验证通过；记录场景、输入、比较样本/输出值/位数及未知数量。

功能失配先分析 RTL、设计计划或检查模型哪一侧有问题。期望未知仅可依据公开规格修正检查器，不能据此修改 RTL 或强行置零。检查修订只传原文引文和已有表达式的修改位置，保留全部旧输入、边沿、采样、时钟绑定、有效条件和掩码；也禁止通过改状态间接撤销旧采样的有效比较。旧版与新版分别保存，所有已编译候选按同一新版重测。编译/综合修复传入结构化诊断及省略统计；返回完全相同的 RTL 时，在剩余轮次内给一次“修改未落实”的反馈，不重复执行工具。

新稿须保留已通过场景并有进展才晋升。最终独立验收应有实际不同的输入序列，仅改名或重排不算新增；无状态、无时钟且总输入不超过 12 位，所有二进制输入的全部输出位已比较时，可跳过冗余验收。此条件只说明所建组合模型的输入覆盖，不证明模型符合全部题意。验收无效或重复仍综合已经自检通过的候选，但保留 `acceptance_*` 未完成状态。无套件时综合代码错误也能触发修复；环境失败停止。未知值、缺失事件不记为通过，修改稿综合通过后才完成最终选择。

| 参数位置 | 默认值和用途 |
| --- | --- |
| Workflow `max_rounds` / `checker_revisions` | 3 / 1；限制 RTL 轮次和规格限定的检查模型修订 |
| Workflow `plan_retries` / `unchanged_retries` | 1 / 1；限制计划重建和重复代码反馈，后者仍计入 RTL 轮次 |
| Workflow `plan_max_tokens` / `review_max_tokens` | 4096 / 4096；计划与计划审阅的输出上限 |
| `roles.suite_builder.params` | `construction_retries: 1`、`generation_max_tokens: 8192`、`review_max_tokens: 4096` |
| `roles.json.params.reserve_s` | 研究预设 120 秒，节点通用默认 0；辅助调用不用这部分剩余时间，因预留截短而超时记真实失败后允许 RTL fallback |
| `roles.functional_tool.params.save_vcd` | 默认 `false`；开启后保留 VCD，并给 `xelab` 添加所需调试信息 |

研究预设总预算为 14400 秒，独立于运行层的收尾预留。输出额度和辅助预留是上限控制，不保证模型产物完成或正式 900 秒内的效果。

### behavior_search

通过 `config/presets/behavior_search.yaml` 选择。默认独立生成 3 稿 RTL，再执行最多 2 次增加测试、修复或重新生成动作。独立生成不接收其他候选代码。
共享检查生成者只看题面，固定驱动用 Vivado 仿真；输出轨迹匿名排列，裁决必须引用原文并经另一次独立审阅。不把输出多数当正确答案，也不把相同输出当验证通过。

每份新稿运行全部保留输入；过去确认的违例不会被新一轮相同输出掩盖。初始化时未采样的未知值仅作历史，采样与时钟边沿信息保留到裁决；只有实际采样事件能支持结论。仅对最终所选候选综合，环境失败或中断时保留已保存答案。

### property_repair_loop

通过 `config/presets/property_repair_loop.yaml` 选择。默认最多 3 轮 RTL、1 次性质修订。性质是引用题目原文的受限 JSON 表达式，输入序列、复位启动和输入约束均显式列出；独立审阅后用固定驱动调用 Vivado `xvlog`、`xelab`、`xsim`，不使用其他验证工具。
当前支持组合逻辑及具有明确启动复位序列的单时钟设计，固定宽度的无符号表达式与一步历史值；不支持的语义明确停止性质检查。

每个场景使用独立 DUT（待测模块实例）。驱动在约定采样时点逐条记录输入、输出、约束和断言状态；事件缺失、未知值、性质未被触发不能记为检查通过。
发现违例后，保留相同复位和输入前缀第二次运行 Vivado，只有再次观察到相同失败和实际输出，才让诊断角色决定是否修改 RTL。性质修订保留全部原输入、启动、约束及未涉及性质，并记录指定性质表达式的变化；所有候选在同一版本重新比较。

`simulation_checked` 只表示所列性质在实际执行输入上未发现违例，不代表性质覆盖全部题意，也不代表任意输入上的证明。该路线已按用户要求从形式工具方案调整为 Vivado 性质仿真。

### 预算与监督

默认整题预算为 900 秒，预留 20 秒用于清理和写出。实际模型超时取 Node 上限、服务上限与本题剩余预算的较小值。
模型服务不自动重试，超时、连接、HTTP、JSON 和响应格式错误分别记录。共享思考声明来自 `manifest.json`
的 `generation`，实际思考设置以当前 manifest 声明为准；一致的部分配置继承完整声明，冲突值或额外未声明的思考字段会被拒绝。

正式入口在独立 Worker 中执行，由 Supervisor（进程监督器）按单调时钟控制期限，停止时先 TERM 再 KILL，
回收受管理进程。选择先写带哈希的原子检查点，再替换答案；Worker 停止后校验与恢复。
没有结束事件的调用保持未知，不伪造完成。自行脱离进程组的子进程不受回收保证；客户端停止也不能证明共享推理服务已取消请求。
进程内 Runner 供依赖注入与测试使用，只提供合作式预算。

## 3. 配置与扩展

默认配置为 [config/presets/single_generate.yaml](config/presets/single_generate.yaml)，仅有五份完整预设位于 [config/presets/](config/presets/)。默认文件已替代旧 `config/example.yaml`，外部调用须更新配置路径。
通过 `AGENT_CONFIG` 或 `--config` 选择文件；配置内部相对路径按配置文件目录解析。
优先级依次为内置默认、YAML、支持的环境变量、命令行参数，实际值与来源写入 trace。

```bash
python3 -m agent.main --input /path/to/task --output /tmp/rtl-out \
  --config config/presets/repair_loop.yaml --record-level basic
```

schema version 3 按名称选择组件；未指定的依赖使用 Python 声明的默认值，只写 `workflow: repair_loop` 也能装配。
`params` 覆盖 Workflow 参数，`roles.<实例ID>` 精确覆盖实现和参数。例如：

```yaml
schema_version: 3
workflow: repair_loop
params: {max_rounds: 2}
nodes: [rtl_generate, rtl_extract, interface_check, vivado_lint, vivado_synth]
tools: [interface_check_tool, vivado_lint_tool, vivado_synth_tool]
roles:
  generate:
    params: {temperature: 0.1}
  lint:
    params: {timeout_s: 45}
```

服务连接、工具路径和预算分别放在 `services.model`、`services.tools` 与 `runtime`；完整字段见默认配置。
可配置本地 tokenizer、上下文容量与累计 token 额度，默认不启用累计额度，未知用量保持未知。
开发组件可在 `ModelRequest` 显式设置 `add_generation_prompt` 和 `continue_final_message`；
默认省略这两个字段，`baseline_rtl` 禁止设置。续写要求最后一条为非空 assistant 文本，并显式关闭生成前缀。
显式设置任一字段都必须使用支持完整请求计数的计数器；计数不是 exact 时，在发送请求前拒绝。
当前续写计数仅核验过 Qwen3 的固定模板（SHA-256 `a55ee1b1660128b7098723e0abcd92caa0788061051c62d51cbe87d9cf1974d8`）
与 Transformers 5.16.1 的文本处理；其他模板返回未知。它不改变共享 thinking 设置、不恢复隐藏状态，
也不保证服务的生成端点支持该模式。现有 Workflow 尚未启用续写；上线前仍需实际生成与 parser 验证。
同一角色有多个候选、未知或未使用的选择会报错。展开的 schema version 2 完整配置仍可读取，供固定实验参数使用；
version 1、`--workflow`、`AGENT_WORKFLOW`、`--import-module` 和顶层 `imports` 已不支持。

常用环境变量如下；服务启动参数另见 [serve/README.md](serve/README.md)。

| 变量 | 默认值或用途 |
| --- | --- |
| `LLM_BACKEND`、`LLM_BASE_URL` | 默认 `mock`；`openai` 必须指定服务地址 |
| `LLM_API_KEY` | 默认空；通过配置的 `api_key_env` 读取 |
| `MODEL_NAME`、`LLM_MODEL` | 前者用于 baseline 与默认流程，后者默认 `mock-model`，用于 mock 和修复流程 |
| `LLM_TIMEOUT_S` | 覆盖服务单次调用上限；各流程以所选预设为准 |
| `AGENT_CONFIG` | 配置路径，默认 `config/presets/single_generate.yaml` |
| `AGENT_DEADLINE_S`、`AGENT_RESERVE_S` | 默认 900 与 20 秒；HTTP 传入排队后的剩余预算 |
| `AGENT_RECORD_LEVEL`、`AGENT_RECORD_ROOT` | 默认 `full` 与输出目录下 `records/`；`basic` 只保留必要 trace |
| `VIVADO_BIN`、`RTL_PART` | Vivado 可执行文件目录；默认器件 `xczu3eg-sbva484-1-e` |
| `RTL_TOP` | 非默认流程的顶层名；未设时从接口推断，再回退 `TopModule` |
| `AGENT_TMP` | 工具临时目录，依次回退 `EDA_TMP`、`TRACK_TMP`、`/tmp`；须使用本地盘 |
| `AGENT_KEEP_WORK` | `1` 保留 Vivado 独立工作目录和完整日志 |
| `AGENT_GIT_COMMIT`、`AGENT_GIT_DIRTY` | 镜像没有 `.git` 时注入源码版本与修改状态 |
| `FPGACHINA_TOKEN` | HTTP 接口必需令牌 |

旧的 `LLM_MAX_TOKENS`、`LLM_TEMPERATURE`、`AGENT_MAX_ROUNDS` 不再读取，采样和轮数使用组件参数。
`serve/vllm.sh` 读取 `MODEL`、`PORT`、`MAX_LEN`、`HIP_VISIBLE_DEVICES`、`VRAM_BUDGET_GB`、`GPU_UTIL`；
默认显存预算 30 GB，据卡容量计算比例，不能替代实测峰值。服务模型名为权重目录名。
脚本固定使用 `--no-enable-log-requests`，不读取 `VLLM_EXTRA_ARGS`，也不自动适配旧版参数。

### 组件职责

| 目录 | 职责 |
| --- | --- |
| `agent/core/` | 类型、组件与上下文协议、预算、状态、候选和诊断；不依赖其他 Agent 层 |
| `agent/composition/` | 配置解析、组件发现、依赖校验和逐题装配 |
| `agent/runtime/` | 执行上下文、Runner、Supervisor、工具与检查缓存 |
| `agent/workflows/`、`agent/nodes/`、`agent/tools/` | 流程策略、动作与可注入工具 |
| `agent/services/` | 模型、进程、Vivado 和代码提取等服务 |
| `agent/prompts/`、`skill/` | 提示构造与技能正文；当前内置流程不检索技能 |
| `agent/recording/` | trace、详细证据、脱敏、原子产物与中断恢复 |

内置 Node 名称为 `baseline_generate`、`baseline_extract`、`rtl_generate`、`rtl_extract`、`interface_check`、
`vivado_lint`、`vivado_synth`、`research_json`、`build_functional_suite`、`functional_check`、`behavior_difference`、
`property_build`、`property_sim_check`；Tool 为 `interface_check_tool`、`vivado_lint_tool`、`vivado_synth_tool`、
`functional_sim_tool`、`property_sim_tool`。

`research_json` 是可选研究动作，接收原题面、明确指令和限定上下文，返回完整 JSON 对象。
它记录实际模型调用，拒绝截断、重复键、非有限数值和非对象回复；不判断生成的行为要求是否正确，
也不执行生成内容。单次生成与结构修复不使用此动作；其余三条流程通过它构造或审阅检查。

扩展分别继承 `Workflow`、`Node[InputT, OutputT]`、`Tool[InputT, OutputT]`，放入所属目录，
声明字面量 `component_name`、`assembly_roles` 与 `assembly_defaults`。配置读取器通过 AST（抽象语法树）发现组件，
无需中央注册；同题同 ID 共享实例，每题重新装配。构造函数只校验和保存参数，依赖通过带类型的构造参数、
`dependencies` 与 `dependency_types` 声明，由装配器注入。导入、类型校验和构造在受监督 Worker 中进行。
重复键、未知字段、错误引用、不可达组件、依赖环或类型不匹配会在执行前拒绝。

Workflow 决定分支、循环、选择和停止，用 `ctx.execute(node, input)` 执行动作。Node 通过 `ctx.llm`
调用模型，通过 `ctx.call()` 调用通用工具，通过 `ctx.check()` 执行 RTL 检查。
RTL 检查 Tool 返回无检查编号的 `CheckOutcome`，运行层编号、关联候选并发布证据；
通用 Tool 可以自定义输入输出类型。ToolContext 不负责答案选择。
保存候选后须由 Workflow 显式调用 `ctx.select_candidate()`，再以 `ctx.finish()` 返回一致的结果。
外部进程使用 `ctx.processes.run(ProcessRequest(...))`；组件依赖必须无环，不导入开发区或官方判定器。

当前不提供旧搜索消融、旧规格自测或初稿重放；`runtime.initial_state` 已撤下，`selection.json`
只用于本次运行中断恢复。技能正文和纯提示渲染能力保留，但没有内置 `use_skills` 或 `skill_lookup` Tool。

## 4. 输出记录与分析边界

`trace.jsonl` 以 `run_id`、递增 `seq`、时间戳 `ts`、类别 `tool` 和事件 `event` 关联过程。
运行元数据包含 Git 短 commit、有效配置与 `assembly_sha256`，不另设 trace 格式版本。
模型用 `call_id`，Node 用 `execution_id`，通用工具用 `tool_call_id` 关联开始与结束；
提取、候选创建与选择、检查及复用、预算和监督结果分别记录。`llm/started` 直接引用实际请求文件；`candidate/change` 记录父/子 hash、增删行数及真实 diff 文件，空改动也明确记录。冻结映射的 Node 输入输出保留可追溯字段。未知 token 用量为 `null`，检查复用不算新执行。
原始 baseline 继续输出官方格式的 trace。

模型服务的 `ModelReply.reasoning` 单独保留服务返回的 `reasoning` / `reasoning_content` 文本，
不把它拼入 `content` 或自动用于提取、修复、续写。`fields` 是不可变副本；缺失、null、空字符串、
非空文本和非法类型分别记录。两个字段的值不完全相同时（包括文本与null并存）状态为 `conflict`；任一字段类型非法时为 `invalid`，
这两种情况下 `text` 返回 null，不自动择一。相同的双字段文本可读取一次，不裁剪空白或做文本归一化。
这些可选字段异常不使原本有效的正文失败；完整原值仍由详细回复记录保存。trace仅增加字段状态和字符数，
不复制思考全文。字符数不代表token用量，预算仍只采用原服务usage；mock和旧回复的状态为 `absent`。
`available`只表示服务提供了可读取字符串，完整性仍须结合`finish_reason`判断；本接口不检查JSON重复键或未知字段别名。
这是后续生成策略的接口准备，不改变现有流程或请求，也不表示已经实现两阶段预算控制。

`full` 模式保存以下详细证据，trace 只保留状态、摘要与引用：

```text
records/<run_id>/
  task.json
  calls/m001/request.json
  calls/m001/response.json   # 非 JSON 响应或 mock 改为 response.txt
  candidates/c001.v
  candidates/c002.diff      # 相对其父候选的实际改动
  process_logs/*.log
```

记录前隐藏 API key、Cookie、Authorization、已知秘密和 URL 凭据；实际模型请求与用于提取的回复不受脱敏修改。
功能检查另在输出 artifacts 下保存规范化 suite、driver、阶段日志、期望分析、采样结果和 result，检查详情给出路径及候选/suite/driver hash；`save_vcd` 开启时包含波形。这些运行产物不进入提交包。
`solution.v` 与 `selection.json` 保存实际代码。必需 trace 写入失败视为基础设施错误；详细文件失败发出
`recording/warning`，不覆盖已有模型结果。中断只保留真实发生的事件和已写日志。
详细记录没有自动清理策略，强制中断仍可能留下临时目录或未结束的调用。

## 5. 封存与提交范围

以下要求依据本地已同步的上游 `f7a8bd4`；日期均为北京时间 2026 年，完整条款见
[上游封存说明](https://gitee.com/Vickyiii/rtlagent2026/blob/f7a8bd465c2a820e006c7a00ecc7df468974635b/docs/SUBMISSION.md)。
验证窗口为 10 月 16 至 30 日，10 月 31 日 10:00 从私有仓库默认分支封存并开始投题，服务需提前就绪；
11 月 4 日 18:00 前提交报告与同一仓库链接。仓库与导出目录名为 `43240_rtlagent`；
Gitee 邀请 `Vickyiii`（`daisycw@126.com`），或 GitHub 邀请 `vickyiii`，授予只读或以上权限。

正式方案须在单张 32 GB 显卡断网运行，辅助模型也计入总显存并如实声明。正式单题时限为 900 秒。
评分采用归一化增益，满分线为 `g=0.6`，计算草稿见 REPORT。仍需补齐固定模型 revision、许可证、
推理版本、实测显存、官方镜像验证、正式结果、失败分析、演示视频和大模型协作记录。
当前示例配置、mock 检查与历史 W7900 实验均不能作为最终 R9700 硬件或能力验收。

提交包包含运行入口、Agent、配置、技能、服务、模型声明、报告和许可证。不得打包开发区 `dev/`、题库 `tasks/`、
参考答案、测试台、凭据、运行日志或缓存；参考材料不得进入 Agent、技能或模型提示。
权重不进入 Git，必须提前准备并在 MODEL.md 声明公开地址和固定 revision。
`baseline.py` 与 `run_baseline.sh` 为受保护的官方原文件，不修改。新增文件名只用英文小写字母、数字、下划线或连字符，
固定赛事文件名沿用原要求。

## 6. 开发资料

如使用包含本仓库的完整工作区，团队文档入口为 `../dev/docs/readme.md`，其中包含首次运行、日常使用、
架构接口、记录格式与历史实验索引；开发规范为 `../dev/docs/conventions.md`。
这些资料和工具不随方案交付，独立运行所需命令与配置均已在本文及仓库内文件中列出。
本地流程验证不能代替参考材料审核、依赖准备、官方镜像构建或目标 GPU 验证。
