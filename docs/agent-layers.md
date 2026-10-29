# Agent 分层与编排设计

[文档入口](index.md) · [架构](architecture.md) · [接口契约](agent-interfaces.md)

当前仓库只保留两条工作流：

- `single_generate`：官方 baseline 生成 → baseline 提取 → 选稿 → 写答案。
- `guided_verify`：小模型规划 → 生成 → 结构检查 → 独立 key-case checker → 归因 →
  有界修复 → 收尾；可选使用知识库检索。

`adaptive_verify`、`design_verify_loop` 和 `repair_loop` 已从当前仓库移除，历史实现保留在
工作区归档中。

## 1. 分层

| 层 | 主要文件 | 职责 |
|---|---|---|
| 入口 | `run.sh`、`agent/main.py` | 加载配置、任务、预算和运行图 |
| 编排 | `agent/orchestration/` | Burr 图、节点、工作流注册 |
| 上下文 | `agent/context/` | 模板渲染与提示词装配 |
| 领域 | `agent/domain/rtl/`、`agent/domain/knowledge/` | RTL 提取、接口、检查、知识库和检索 |
| 模型 | `agent/llm/` | OpenAI 兼容客户端、mock、profile 路由 |
| 运行时 | `agent/runtime/`、`agent/observability/` | 预算、进程、记录和脱敏 |
| 提交 | `agent/submission/gateway.py` | 候选登记、选稿与 `solution.v` 原子发布 |

## 2. 工作流

### `single_generate`

```text
generate -> extract -> select -> finish
```

- 使用 `baseline_generate` 和 `baseline_extract`，保持官方 baseline 的提示和提取行为。
- 不加载 Skill，不调用 Vivado，不做额外检查。
- 默认入口 `run.sh` 使用 `config/single_generate.yaml`。

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

- `plan` 使用 small profile 生成扁平计划。
- `solve` 生成候选，并可选注入 planner 选中的知识卡片。
- `structure` 通过 interface/lint/synth 工具检查。
- `build_checker` 生成行式 key-case 表，宿主生成 Verilog testbench。
- `run_checker` 执行 xsim 比较；`adjudicate` 只处理失败或未知，修复次数有配置上限。
- 收尾按当前 checker 指纹和实际发布候选取证据，不支持跨候选拼接通过。

## 3. 模型与 profile

- 模型 profile 只按角色映射，模型不能自行选择 profile。
- `guided_verify` 默认：
  - `small`：planner；
  - `large`：solve、checker、adjudicate、repair；未启用时回落到主模型。
- `config/guided_verify.yaml` 默认使用 legacy 知识检索；RAG 可选配置单独启用。
- 模型思考开关沿用 `manifest.json` 的 `generation` 声明，不按请求类型另设一套。

## 4. 工具与提交

`ctx.call()` 和 `ctx.dispatch()` 共用注册表、参数校验、预算和记录。当前保留的检查工具：

```text
interface_check
vivado_lint
vivado_synth
```

`SubmissionGateway` 是唯一写 `solution.v` 的入口：

- 候选通过 `CandidateStore` 分配 ID、保存源码和父候选关系；
- `last_written` 与 `selected` 策略均可配置；
- 发布使用同目录临时文件 + `os.replace`，不会留下半写答案；
- 收尾记录 `selected_id`、实际发布候选和证据候选，避免把未检查候选误报为通过。

## 5. 知识库

- `knowledge/cards.json` 保存 129 张卡片正文，不保存版本、sha256、路径或 release lock。
- `knowledge/vectors.json` 保存 `card_id` 和向量；embedding 参数在
  `config/rag_embedding.yaml`。
- `agent/domain/knowledge/guided.py` 提供 BM25/dense 检索和卡片文本读取。
- `single_generate` 的 RAG 配置使用 `rtl_generate`/`rtl_extract`；
  `guided_verify` 通过 `retrieval_mode` 选择不检索、legacy 或 RAG 候选。

## 6. 预算与记录

`Budget.remaining_s()` 扣除收尾预留；模型和工具调用受同一任务截止约束。默认入口使用
900 秒配置，阶段和工具超时会裁剪到剩余时间。

`trace.jsonl` 保存节点、模型、工具、知识检索、提交和结束事件；`records/<run_id>/` 保存
完整请求、回复、候选和检查产物。日志不包含参考答案、官方测试台或判定反馈。
