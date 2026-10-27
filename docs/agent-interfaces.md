# Agent 接口契约

状态：已实现。`ToolResult`、有界工具循环、提交网关、`submit_answer`/`finish_task`、
模型 profile 路由、`ContextBundle`、`PromptAssembly` 与 Stage 描述均已落地。
`Usage` 对象仍以内联字段记录。分层背景见 [Agent 分层与编排设计](agent-layers.md)。
字段名以下文为准；实现时若需偏离，先更新本文件。

## 1. LLM 接口

### 1.1 请求

```python
@dataclass(frozen=True)
class LLMRequest:
    role: str                  # analyst / author / builder / reviewer / attributor
    profile: str               # small / medium / large，由配置映射到实际模型
    messages: list[dict]       # 已装配的消息，不再二次改写
    context_ref: str | None    # ContextBundle 产物路径或 ID
    params: dict               # temperature、top_p、max_tokens、timeout_s、response_format
    tools: tuple[dict, ...] = ()
    step: int = 0              # 阶段内工具循环步数，从 0 开始
```

约束：

- `messages` 由 L2 装配层生成；LLM 层不拼接业务上下文。
- `params` 的来源是工作流参数与清单声明；思考开关不允许按调用覆盖。
- `profile` 只决定模型与配额，不改变消息内容。实现为 `Client.chat(profile=...)`：
  未配置、未启用或未知 profile 都回落到主模型；`profile` 与实际 `model` 写入
  `llm/finished` 事件。角色映射见 `agent/llm/router.py`。

### 1.2 回复与用量

```python
@dataclass(frozen=True)
class Usage:
    tokens_in: int | None
    tokens_out: int | None
    wall_s: float
    model: str
    source: str                # reported / estimated / unknown

@dataclass(frozen=True)
class LLMReply:
    call_id: str
    content: str
    tool_calls: tuple[dict, ...]
    finish_reason: str | None
    usage: Usage
    raw_ref: str | None        # 完整原始响应产物路径
```

兼容说明：现有 `agent/llm/types.py` 的 `Reply` 已提供 `call_id`、`content`、`tool_calls`、
`finish_reason`、`tokens_in`、`tokens_out`、`model`；实现时在其上增加 `Usage` 或提供转换函数，
不删除旧字段。未知用量保持 `None`，不记为零。

## 2. 工具接口

### 2.1 工具描述

```python
@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict         # JSON Schema，严格校验
    side_effect: str           # readonly / mutating / control
    timeout_s: float
    max_excerpt_bytes: int = 2048
```

### 2.2 结果信封

```python
@dataclass(frozen=True)
class ToolResult:
    tool: str
    call_id: str
    rc: int                    # 0 成功；1 领域失败；2 参数非法；3 超时；4 不可用
    status: str                # passed / failed / timeout / error / skipped
    excerpt: str               # <= 2048 字节，UTF-8 边界截断
    artifacts: tuple[str, ...] # 完整输出文件
    elapsed_s: float
    truncated: bool
    failure_kind: str          # code / checker / environment / timeout / unknown
    meta: dict
```

规则：

- 模型只读取 `rc`、`status`、`excerpt` 与 `artifacts` 路径；完整内容按需读取。
- `excerpt` 连同 `\n[truncated]` 标记不超过 2048 字节；记录器二次截断不会吃掉标记。
- `to_dict()` 保留完整宿主字段；`to_model_dict()` 去掉 `meta.details`、命令等载荷。
  `Ctx.dispatch()` 返回后者并做 JSON 归一化，避免 Path/dataclass 进入 tool 消息。
- 参数校验失败返回 `rc=2`，不抛异常给模型自由文本。
- 进程类工具超时先结束整个进程组，再返回 `rc=3`。
- 现有 `CheckResult` 通过 `ToolResult.from_check_result()` 适配；`summary` 映射为 `excerpt`，
  `log_paths` 映射为 `artifacts`，保留 `failure_kind` 与 `details` 到 `meta`。

### 2.3 两条调用路径

```text
模型路径：LLMReply.tool_calls -> 白名单校验 -> ToolSpec.input_schema -> dispatch -> ToolResult -> 回填消息
节点路径：node -> ctx.call(name, **args) -> 同一工具实现 -> 原生结果
```

模型路径由 `agent/runtime/agent_loop.py` 驱动，固定步数上限；每条 `tool_calls` 都经过
白名单与 JSON 参数校验。`Ctx.dispatch()` 统一返回 `ToolResult` 字典；`Ctx.call()` 仍返回
领域对象，供节点直接使用。两条路径共用预算、超时、进程组与记录。

当前已注册的模型可调用工具：

| 工具 | 作用 | 返回 |
| --- | --- | --- |
| `submit_answer` | 校验完整 RTL、创建候选并按策略登记/发布 | `ToolResult`，`meta.record` 含候选与策略 |
| `finish_task` | 请求当前阶段结束 | `ToolResult`，`meta.reason` |

`tool_steps` 默认 0；实验配置 `config/adaptive_tools.yaml` 设为 2。每步消耗一次 completion。

## 3. 上下文与提示词

### 3.1 ContextBundle

```json
{
  "bundle_id": "ctx-<id>",
  "task": {
    "prompt_ref": "records/<run_id>/task/prompt.txt",
    "interface_ref": null,
    "top": "TopModule"
  },
  "sections": [
    {"id": "route", "kind": "route", "trust": "host", "content": {}, "tokens_est": 0},
    {"id": "skill:fsm", "kind": "knowledge", "ref": "knowledge/...", "trust": "frozen"},
    {"id": "tool:lint-1", "kind": "tool_result", "ref": "records/.../tool-1.json", "trust": "observed"}
  ],
  "limits": {"max_input_tokens": 30000, "reserved_output_tokens": 8192}
}
```

- 实现位置：`agent/runtime/prompt.py` 的 `ContextBundle`；`adaptive_analyze` 保存
  `adaptive/context-bundle.json`。任务段只存题面哈希与字节数，不复制正文。
- 大段正文只存引用；`content` 仅用于短结构。
- `trust` 取值：`host`、`frozen`、`observed`、`model`。模型生成的建议不能标成 `host`。
- 已冻结证据只读；后续节点只追加 section。

### 3.2 装配结果

```python
@dataclass(frozen=True)
class PromptAssembly:
    template: str              # 如 repair.j2
    template_sha256: str
    messages: list[dict]
    kept_sections: tuple[str, ...]
    dropped_sections: tuple[str, ...]   # 因预算裁剪，必须可见
    tokens_est: int
    messages_sha256: str
```

裁剪优先级：任务原文 > 公开接口 > 已记录证据 > 冻结知识 > 历史消息。任何裁剪都写日志，不静默丢弃。

## 4. 阶段描述

```python
@dataclass(frozen=True)
class StageSpec:
    node: str                  # 工作流节点别名
    role: str                  # LLM 角色；纯宿主阶段为 executor
    tools: tuple[str, ...]     # 模型可自主调用的工具白名单
    max_steps: int             # 工具循环上限；>= 1
    reads: tuple[str, ...]     # State 字段
    writes: tuple[str, ...]
    stage_budget: str          # 对应工作流参数中的阶段限额名
```

默认值：分析、构造、复核、归因 `max_steps=1`；作者 `max_steps=3`；修复当前为
`max_steps=1` 且没有模型可调用工具；纯宿主阶段 `max_steps=0` 且不调用模型。
实现表为 `agent/runtime/stages.py` 的 `ADAPTIVE_STAGES`，角色统一来自 `agent/roles.py`；
`stage_spec()` 同时接受节点名和请求标签（`draft_tool_2`）。当前只有作者阶段声明了
`submit_answer` 与 `finish_task`。

## 5. 提交接口

### 5.1 工具

```text
submit_answer(code: str, top: str | None = None, note: str | None = None)
  -> {candidate_id, code_hash, accepted, published}
```

- 校验失败：`rc=2`，`status=error`，附原因，不写 `solution.v`。
- 校验成功且策略为 `last_written`：原子发布到 `solution.v`，`published=true`。
- 策略为 `selected`：只登记候选，由晋升规则决定是否发布。

实现位置：`agent/rtl/submission.py` 的 `SubmissionGateway`，以及
`agent/nodes/submission_tools.py` 的工具注册。`CandidateStore.publish()` 只做原子发布，
不修改 `selected_id`；`select()` 仍表示证据选稿。

### 5.2 收尾

```text
finalize_submission(reason)
  -> {policy, published_id, code_hash, delivery}
```

触发：图进入 `finish`、工作截止、`SIGTERM`、异常收尾。幂等；没有候选时 `delivery=empty`。

### 5.3 事件

```json
{
  "tool": "submission",
  "event": "finalized",
  "policy": "last_written",
  "candidate_id": "c003",
  "code_hash": "...",
  "selected_id": "c002",
  "overrode_selected": true,
  "delivery": "complete_rtl",
  "reason": "workflow_finished"
}
```

`overrode_selected` 用于在 LWW 期间显式暴露“覆盖了哪次证据选稿”，便于事后审计。

## 6. 兼容与迁移

- 现有 `Reply`、`CheckResult`、`CandidateStore.select()` 保留；新接口以适配器叠加。
- 现有 `record.emit` 的 2 KB `excerpt` 截断与 `docs/API_CONTRACT.md` 的建议一致，不另设第二套截断。
- `trace.jsonl` 必须继续包含 `ts`、`tool`、`rc`、`excerpt`、`tokens_in`、`tokens_out`。
- 新事件只追加，不删除旧字段；日志查看器按存在字段展示，缺失保持未知。
