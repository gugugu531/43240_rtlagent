# Agent 分层与编排设计

[文档入口](index.md) · [架构](architecture.md) · [接口契约](agent-interfaces.md)

当前仓库内置两条工作流，用于根据公开题面生成 RTL（寄存器传输级）代码：

- `single_generate`：按官方基线（baseline）生成 → 提取 → 选择候选 → 写入答案。
- 默认 `guided_verify` 由策略角色选检查方式和技能，解题角色生成 RTL，经结构检查后按需运行独立行为表。解题角色可提交、改稿或请检查角色复核一个测试点。

`adaptive_verify`、`design_verify_loop` 和 `repair_loop` 已从当前仓库移除，历史实现保留在
工作区归档中。

## 1. 分层

| 层 | 主要文件 | 职责 |
|---|---|---|
| 入口 | `run.sh`、`agent/main.py` | 加载配置、任务、预算和运行图 |
| 编排 | `agent/orchestration/` | Burr 图、节点、工作流注册 |
| 上下文 | `agent/context/` | 模板渲染与提示词装配 |
| 领域 | `agent/domain/rtl/`、`agent/domain/knowledge/` | RTL 提取、接口、检查、知识库和检索 |
| 模型 | `agent/llm/` | OpenAI 兼容客户端、假模型（mock）、按角色选择模型配置组（profile） |
| 运行时 | `agent/runtime/`、`agent/observability/` | 预算、进程、记录和脱敏 |
| 答案交付 | `agent/submission/gateway.py`、`agent/domain/rtl/candidate.py` | 候选登记、选择、提交策略与 `solution.v` 原子写入 |

## 2. 工作流

### `single_generate`

```text
generate -> extract -> select -> finish
```

- 默认使用 `baseline_generate` 和 `baseline_extract`，复用官方基线的提示和提取函数。
- 默认配置不加载 Skill（技能文件），不调用 Vivado，也不做额外检查。显式研究配置可以替换生成与提取节点，见第 5 节。
- 显式设置 `AGENT_CONFIG=config/single_generate.yaml` 使用此流程。

### `guided_verify`

```text
initialize -> plan -> solve -> structure
structure -> repair_structure | build_checker | run_checker | author_decision | finish
repair_structure -> repair_structure | structure | finish
build_checker -> run_checker | author_decision
run_checker -> author_decision
author_decision -> structure | checker_review | author_decision | finish
checker_review -> run_checker | author_decision
```

- `plan` 默认使用主模型 Qwen3.8-27B 生成逐行键值格式的计划，不接入小模型。
- `solve` 生成候选，可将规划阶段选中的技能和知识卡片加入提示词；默认关闭知识卡片检索。
- `structure` 通过 `interface`、`lint`、`synth` 三个工具别名执行接口检查、语法编译和综合检查。
- 有明确代码错误时，`repair_structure` 让解题角色返回完整修订稿。无完整新稿时，可在预算内带上格式诊断重问。无法继续修复时按兜底规则交付。当前稿的 lint 和 synth 均通过，才会构造或执行行为表。
- `build_checker` 让检查角色独立生成测试点，每点用一条说明描述激励和期望，程序生成 Verilog 测试台。格式错误可按解析诊断纠正。
- `run_checker` 用 Vivado Simulator（`xsim`）运行采样测试台，再由 Python 按点比较实际值和期望值。修订 RTL 要重新检查结构，修正或撤回测试点后，只要仍有活动点且当前稿的 lint 和 synth 均通过，就再次运行当前表。`author_decision` 把当前 RTL、结构与行为结果和历轮短记交给解题角色。它可提交、返回完整改稿或指定一个点复核。`checker_review` 只依据公开资料对该点作出保留、修正或撤回决定。
- 收尾按当前检查器的内容哈希和实际写入答案文件的候选查找证据，不把其他候选或旧检查器的结果当作当前答案通过的依据。

## 3. 模型配置组与请求上下文

- 模型配置组只按代码中的角色映射选择，模型不能自行切换配置组。
- `small` 与 `large` 是保留的配置组名称，不表示模型实际大小。默认均关闭，所有阶段使用主模型。
  显式研究配置可启用策略角色对应的 `small` 以及解题、检查角色对应的 `large`。
- 默认入口 `run.sh` 使用 `config/guided_verify.yaml`，关闭知识卡片检索；技能仍可由规划选择。
- 每阶段重新构造消息列表 `messages`，不拼接其他阶段的聊天历史；各阶段仍共用推理服务。
- 模型思考开关沿用 `manifest.json` 的 `generation` 声明，不按请求类型另设一套。

## 4. 工具与提交

`ctx.call()` 和 `ctx.dispatch()` 共用注册表、参数校验、预算和记录。当前保留的检查工具：

```text
interface_check
vivado_lint
vivado_synth
```

`CandidateStore` 负责将候选代码原子写入 `solution.v`。`single_generate` 直接调用其 `select()`；
`guided_verify` 还使用 `SubmissionGateway` 管理提交策略：

- `CandidateStore` 分配 ID，保存源码、父候选关系与内容哈希，使用同目录临时文件和 `os.replace` 原子写入。
- `guided_verify` 使用 `author_decides`。仅做结构检查且 lint、synth 均通过时自动提交。行为路线由解题角色显式提交当前稿。
- 中断文件优先保留最近一份 lint、synth 均通过的候选，否则保留最近完整稿。最终以实际交付候选及其检查器版本查找证据。

## 5. 知识库

- `knowledge/cards.json` 保存 129 张卡片正文，不保存版本、文件哈希、路径或发布锁定信息。
- `knowledge/vectors.json` 保存 `card_id` 和向量；文本向量模型参数在
  `config/rag_embedding.yaml`。
- `agent/domain/knowledge/guided.py` 提供 BM25（基于词项匹配的排序算法）、稠密向量检索（`dense`）和卡片文本读取。
- RAG（检索增强生成）默认关闭。`single_generate` 的显式 RAG 配置使用 `rtl_generate` 和 `rtl_extract`；
  `guided_verify` 通过 `retrieval_mode` 选择检索范围。检索与提示词装配均检查卡片允许的阶段及 `injection_eligible` 字段，见[接口契约](agent-interfaces.md)。

## 6. 预算与记录

`Budget.remaining_s()` 扣除收尾预留；模型和工具调用受同一任务截止约束。默认入口使用
900 秒配置，阶段和工具超时会裁剪到剩余时间。

`trace.jsonl` 保存节点、模型、工具、知识检索、答案交付和结束事件；默认 `full` 记录级别还在
`records/<run_id>/` 保存完整请求、回复、候选和检查产物，`basic` 级别不写这些正文文件。
求解流程不得读取参考答案、官方测试台或判定反馈，因此也不能通过日志将这些信息回传给模型。
