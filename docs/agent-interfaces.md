# Agent 接口契约

[文档入口](index.md) · [分层设计](agent-layers.md)

本页只描述当前保留的 `single_generate`、`guided_verify` 和知识检索接口。

## 1. 模型请求

`Client.chat()` 接收标准消息列表，至少包含：

```python
[
    {"role": "system", "content": "..."},
    {"role": "user", "content": "..."},
]
```

调用参数包括 `purpose`、`max_tokens`、`temperature`、`top_p`、`timeout_s` 和可选
`profile`。profile 由 `agent/roles.py` 按阶段决定，不从模型回复中读取。

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

节点可以调用 `ctx.call(name, **args)`；工具注册表负责参数校验和记录。当前工具：

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

检查结果通过 `bind_result()` 绑定候选、检查器版本和可选 suite 身份。

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

内部运行数据放在 `ctx.store["guided"]`，包括 plan、assessments、observations、
behaviors、checker 和预算快照。状态必须是可序列化数据；大正文放入记录器。

## 4. 提示词

`TemplateRenderer` 从 `agent/context/prompts/` 读取模板。当前保留：

```text
system.j2
repair.j2
```

`repair.j2` 同时用于 guided 首稿和修复；题面、公开接口、计划、反馈和父候选由宿主传入。
模板不读取参考答案、官方测试台或判定反馈。

## 5. 知识检索

`guided_verify` 的计划阶段可选择：

```text
retrieval_mode: off | legacy | rag | all
retrieval_strategy: bm25 | dense
```

- `legacy`：只取 `activation_state=legacy_policy` 的卡片；仍须通过阶段和 `injection_eligible` 检查。
- `rag`：取 `legacy_policy` 和 `restricted` 卡片，并要求 `pre_generation` 阶段和 `injection_eligible=true`。
- `all`：包含 shadow 和 mechanical_only，仅用于开发检查。

检索接口：

```python
from agent.domain.knowledge import guided

cards, report = guided.retrieve(query, mode="rag", limit=5)
text = guided.card_text(cards[0])
```

dense 检索使用 `config/rag_embedding.yaml` 中的模型别名、维度、pooling、L2 归一化和
query 投影。知识库和向量文件只保存内容，不保存版本、sha256、路径或 release lock。

## 6. 提交

`SubmissionGateway.submit_text()` 校验完整模块和题目顶层名，创建候选并登记。返回：

```text
policy
candidate_id
code_hash
published
```

最终发布由 `SubmissionGateway.finalize()` 完成，写入 `<output>/solution.v`。答案选择可以是
`last_written` 或 `selected`，两者都在结果中记录实际发布候选和证据候选。

## 7. 事件

`trace.jsonl` 常用事件：

```text
run/start, run/config, node/started, node/ended,
llm/request, llm/reply, llm/finished,
tool/call, tool/result, knowledge/retrieval,
submission/published, submission/finalized, run/end
```

事件只保存摘要和引用；完整内容在 `records/<run_id>/`。任何未知值、未触发检查或未交付
都不能写成通过。
