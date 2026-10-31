# Agent 分层与编排设计

[文档入口](index.md) · [架构](architecture.md) · [接口契约](agent-interfaces.md)

当前仓库内置两条工作流，用于根据公开题面生成 RTL（寄存器传输级）代码：

- `single_generate`：按官方基线（baseline）生成 → 提取 → 选择候选 → 写入答案。
- `guided_verify`（默认）：独立规划 → 生成 → 结构检查 → 独立关键用例检查 → 归因 →
  有次数上限的修复 → 收尾；可选使用知识库检索。

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
structure -> repair_structure | build_checker | run_checker | finish
repair_structure -> structure
build_checker -> run_checker | finish
run_checker -> adjudicate | finish
adjudicate -> repair_behavior | build_checker | finish
repair_behavior -> structure
```

- `plan` 默认使用主模型 Qwen3.8-27B 生成逐行键值格式的计划，不接入小模型。
- `solve` 生成候选，可将规划阶段选中的技能和知识卡片加入提示词；默认关闭知识卡片检索。
- `structure` 通过 `interface`、`lint`、`synth` 三个工具别名执行接口检查、语法编译和综合检查。
- `build_checker` 生成行式关键用例表，由本地检查程序据此生成 Verilog 测试台；检查器构造不接收候选 RTL 或实测输出。
- `run_checker` 使用 Vivado Simulator（`xsim`）执行仿真和比较；`adjudicate` 处理失败或未知结果，修复次数有配置上限。
- 收尾按当前检查器的内容哈希和实际写入答案文件的候选查找证据，不把其他候选或旧检查器的结果当作当前答案通过的依据。

## 3. 模型配置组与请求上下文

- 模型配置组只按代码中的角色映射选择，模型不能自行切换配置组。
- `small` 与 `large` 是保留的配置组名称，不表示模型实际大小。默认均关闭，所有阶段使用主模型。
  显式研究配置仍可启用规划阶段对应的 `small`，以及生成、检查器构造、归因和修复阶段对应的 `large`。
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

- 候选通过 `CandidateStore` 分配 ID、保存源码和父候选关系；
- `last_written` 策略在登记候选时立即写入，收尾保留最后登记的候选；`selected` 策略在收尾写入 `selected_id` 指定的候选；
- 写入使用同目录临时文件和 `os.replace` 原子替换，避免留下只写了一部分的答案；
- `guided_verify` 的结果分别记录 `selected_id`、实际交付候选和证据候选；默认 `last_written` 可能交付尚未通过检查的候选，必须据实际交付候选判断检查状态。

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
