# Agent 接口契约

[文档入口](index.md) · [分层设计](agent-layers.md)

本页描述当前 `single_generate`、`guided_verify` 和知识检索接口。模型根据公开题面生成 RTL（寄存器传输级）代码；下面的字段名和事件名均对应当前源码。

## 1. 模型请求

`Client.chat()` 接收消息列表，内置节点通常按以下形式构造系统消息和用户消息：

```python
[
    {"role": "system", "content": "..."},
    {"role": "user", "content": "..."},
]
```

调用参数包括 `purpose`、`max_tokens`、`temperature`、`top_p`、`timeout_s` 和可选
`profile`。`profile` 指模型配置组；内置流程通过 `agent/roles.py` 按阶段选择，不从模型回复中读取。

回复对象提供：

```text
call_id
content
finish_reason
tokens_in / tokens_out
model
reasoning（可选）
```

模型错误按 `ModelError.kind` 分类；HTTP 200 不代表内容有效。

## 2. 工具接口

节点可以调用 `ctx.call(name, **args)`；运行上下文根据工具注册表校验参数并记录调用。下表使用注册名，`guided_verify` 分别将它们映射为 `interface`、`lint`、`synth` 三个调用别名：

| 工具 | 参数 | 返回 |
|---|---|---|
| `interface_check` | `candidate_id` | `CheckResult` |
| `vivado_lint` | `candidate_id`、可选 `timeout_s` | `CheckResult` |
| `vivado_synth` | `candidate_id`、可选 `timeout_s` | `CheckResult` |

`CheckResult` 至少包含：

```text
status: passed | failed | timeout | unavailable | error | skipped
summary
blocking
rc
failure_kind: code | checker | environment | timeout | unknown
details
log_paths
candidate_id
kind
```

检查结果通过 `bind_result()` 绑定候选代码哈希、检查器实现哈希和可选的检查套件（`suite`）哈希。`status` 为 `skipped`、`unavailable` 或未知值时，不能记为检查通过。

## 3. 阶段状态

`single_generate` 使用：

```text
round, target_id, reply_id, has_candidate, stop_reason, status
```

`guided_verify` 使用：

```text
settings, method, target_id, parent_id, action,
checker_status, stop_reason, status
```

内部运行数据放在 `ctx.store["guided"]`，包括规划（`plan`）、结构检查（`assessments`）、仿真观测（`observations`）、
行为检查结果（`behaviors`）、检查器（`checker`）和请求额度账本（`ledger`）。这些对象只在本次进程中保留。
Burr 状态必须能序列化为 JSON；完整正文交给记录器保存，不能据此认为 `ctx.store` 支持断点恢复。

## 4. 提示词

`TemplateRenderer` 从 `agent/context/prompts/` 读取 Markdown 模板，仍由 Jinja2 渲染变量和条件：

```text
system.md
repair.md
repair_analysis_system.md
repair_analysis.md
```

`repair.md` 同时用于 `guided_verify` 首稿和修复；题面、公开接口、计划、反馈和父候选由调用节点传入。
模板不读取参考答案、官方测试台或判定反馈。
缺少必需变量会报错；自定义模板目录也须使用新的 `.md` 名称，不保留旧扩展名兼容入口。

## 5. 知识检索

Skill（技能文件）的启用不依赖卡片检索模式。运行时从 `skill/` 的直接子目录自动发现技能，并为每题保存正文快照；
`guided_verify` 的规划阶段最多选择两个技能，实际使用前还会检查阶段、准入状态和冲突组约束。
新增文件的最小格式及默认行为见[技能扩展指南](../skill/README.md)。
`guided_verify` 的 RAG（检索增强生成）默认关闭。卡片检索范围和排序方式可分别配置：

```text
retrieval_mode: off | legacy | rag | all
retrieval_strategy: bm25 | dense
```

- `off`：不检索知识卡片。
- `legacy`：候选范围限于 `activation_state=legacy_policy` 的卡片。
- `rag`：候选范围包含 `legacy_policy` 和 `restricted` 卡片。
- `all`：将候选范围扩展到 `shadow` 和 `mechanical_only`，用于研究配置。

上述名称都是卡片中的状态值。除 `off` 外，各模式均要求 `injection_eligible=true`，并通过 `phases` 和可选 `injection_stages` 的阶段检查；`all` 不会绕过这些条件。内置 `guided_verify` 使用 `pre_generation` 阶段。排序可选 BM25（基于词项匹配的排序算法）或稠密向量检索（`dense`）。

检索接口：

```python
from agent.domain.knowledge import guided

query = "RTL 位宽与有符号数检查"
cards, report = guided.retrieve(query, mode="rag", limit=5)
texts = [guided.card_text(card) for card in cards]
```

`dense` 检索使用 `config/rag_embedding.yaml` 中的文本向量模型别名、向量维度、池化方式（`pooling`）、L2 归一化和查询模板。
`retrieve()` 的默认排序方式为 `bm25`；使用 `dense` 时必须提供 `embedding_url`。
知识库和向量文件不保存版本、文件哈希、路径或发布锁定信息。

## 6. 提交

`SubmissionGateway.submit_text()` 校验完整模块和题目顶层名，创建候选并登记。返回：

```text
policy
candidate_id
code_hash
published
```

`SubmissionGateway` 用于 `guided_verify`。默认 `last_written` 策略在登记候选时立即写入 `<output>/solution.v`，
`finalize()` 再确认并写入最后登记的候选；`selected` 策略在 `finalize()` 中写入 `CandidateStore.selected_id` 指定的候选。
`CandidateStore.select()` 本身也会立即写入答案。`single_generate` 直接使用此方法，不经过 `SubmissionGateway`。

`finalize()` 返回的 `final` 字段记录 `target_id`、`selected_id`、`overrode_selected` 和 `published` 等信息；
`guided_verify` 的结果另外记录 `published_id` 与 `evidence_candidate_id`。应按实际交付候选及当前检查器查找检查结果，不能把“文件已写入”当成“检查通过”。

## 7. 事件

`trace.jsonl` 每行是一个 JSON 对象，`tool` 表示事件来源，`event` 表示事件类型。下表用 `tool/event` 表示两者的组合：

```text
run/start, run/config, run/graph, run/end
node/started, node/finished, node/failed
llm/started, llm/finished, llm/failed
tool/started, tool/finished, tool/failed
interface/result, lint/result, synth/result
knowledge/retrieval, submission/published, submission/finalized
```

工具结果以实际调用别名为 `tool`，所以上面的 `interface/result` 等事件适用于默认 `guided_verify` 别名；
直接按注册名调用时，事件来源也使用该注册名。事件还会保存节点状态、参数及摘要，并非只有文件引用。
`full` 记录级别将完整请求、回复和运行产物写入 `records/<run_id>/`；`basic` 不生成这些正文文件。
未知值、未触发检查或未交付都不能写成通过。
