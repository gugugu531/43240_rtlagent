# 运行记录格式

本文是当前接口的专题参考；完整索引见[User Manual](../user-manual.md)。

本文描述当前 Agent 记录。官方 baseline 保持原样，使用官方 trace 格式。

## 对外 trace

`trace.jsonl` 必须存在，每行一个 JSON 对象。版本为 `schema_version=4`，公共字段包括
`run_id`、递增的 `seq`、Unix 时间戳 `ts`、事件类别 `tool` 和动作 `event`。

版本 4 增加选择决策、检查复用、外部动作与独立监督证据，运行元数据分别描述 Workflow、服务和预算。
检查状态使用 `passed/failed/timeout/unavailable/error/skipped`。

模型调用分为三个事件：

| 事件 | 内容 |
| --- | --- |
| `llm/started` | `call_id`、用途 `purpose`、公开服务配置 |
| `llm/succeeded` | `call_id`、模型名、服务请求 ID、`finish_reason`、耗时、token 用量、响应引用 |
| `llm/failed` | `call_id`、错误 `kind`、`retryable`、HTTP 状态码、耗时、错误摘要、证据引用 |

开始事件和结束事件属于同一次调用。进程被终止时允许只有开始事件。未知 token 用量是
`null`，实际的零是 `0`。mock 明确标记为 mock，不生成 HTTP 响应文件或假用量。

`node/started/succeeded/failed` 保存执行 ID、父执行、组件参数、摘要、耗时与错误。
模型调用、提取、候选与工具事件附带所属 `execution_id`，嵌套动作结束后恢复父动作关联。

`extract/result` 记录调用 ID、候选 ID（没有候选时为 `null`）、完整性、模块名、多草稿、
截断标记和诊断。`candidate/create` 记录 `source_call_id`，可从最终选择追溯生成来源。
工具事件记录命令、状态、返回码、耗时与摘要。检查的 `details.executed=false` 表示复用，
`reused_from_check_id` 指向原检查；不计为新工具执行。`workflow/check_started` 与完成结果按 check ID 合并，
只有开始事件时记为未完成尝试。模型正文不内联到 trace；摘要最多 2000 字符。

`run/recording` 记录等级和详细目录，`run/metadata` 记录题目 ID、Workflow 类型与参数、公开服务配置、运行预算与 Git 信息。
Git 不可用时记录未知，也可以通过构建环境注入 commit 和 dirty 状态。

## 详细文件

`RecordingConfig(level="full", root=...)` 开启完整记录；默认是 full。未指定 root 时放在
`<输出目录>/records/<run_id>/`，指定 root 时放在 `<root>/<run_id>/`。

- `run.json`：格式版本、等级、时间、元数据、调用与动作状态、最终结果和 `recording_incomplete`。
- `task.json`：本题允许提供的题面、接口及解析来源。
- `nodes/e001/execution.json`：动作类型、参数、输入输出摘要、父执行、耗时与错误详情。
- `candidates/c001/solution.v` 与 `metadata.json`：候选正文及来源。
- `checks/k001/result.json`：统一检查证据。
- `selection.json`：已选择候选及原因。
- `supervision.json`：真实中断原因、Worker 退出码、选择恢复、清理状态与后端取消状态。
- `tool_logs/`：完整逻辑工具日志，独立于临时工作目录。
- `process_logs/`：Supervisor 持有的进程输出，强制中断时仍可保留。
- `calls/m001/request.json`：实际消息与请求参数，以及公开服务配置。HTTP 身份验证头不写入。
- `response.txt`：收到的原始 HTTP 响应文本，写入前脱敏。
- `response.json`：可解析的完整 JSON；保留 reasoning、其他 choices 与供应方字段。
- `content.txt`：标准回复正文，成功解析后生成；mock 也生成。
- `result.json`：标准回复元数据或分类错误。
- `extraction.json`：提取结果与候选关联。

`ArtifactRef` 由 run ID 和相对文件路径组成。调用 ID 在一次运行内递增；每次运行使用新 run ID。
HTTP 设置独立记录根目录后，请求临时目录清理不影响这些文件。basic 等级不写详细文件。

## 故障与秘密处理

保存的是脱敏副本：递归隐藏敏感字段、替换环境与显式服务配置中的秘密、过滤 URL 凭据和查询参数。
这不会修改发送给模型的请求，也不会修改用于提取的正文。文件写入采用同目录临时文件和原子替换。

先保存响应文本，再尝试 JSON 与协议解析，因此 HTTP 错误、非 JSON 和响应字段错误仍有证据。
连接失败或超时未收到响应时，不创建虚构响应文件。可重试标记供 Workflow 的 FailurePolicy 判断，服务本身不重试。

详细文件不可写时，发出 `recording/warning`，并尽可能在 run.json 标记记录不完整。
原模型结果和错误保持原样。必要 trace 不可写则抛出 `RecordingError`，按基础设施故障处理。
Supervisor 只在 Worker 停止后接管记录，追加 `supervisor/result` 并将 run.json 标为 interrupted。
已有调用和 Node 的 started 状态保持原样，不能用监督结果伪造调用结束。最后一行若被打断，原始
片段另存为输出目录的 `trace_partial.txt`，返回 trace 保持有效 JSONL。
`backend_inference_cancelled=unknown` 明确表示只确认客户端结束，不能确认共享服务已取消推理。

输出目录中的 `selection.json` 是必须写入的恢复检查点，包含实际候选代码、来源、哈希和原因。
先原子提交检查点，再更新 solution；Supervisor 校验哈希后完成必要的恢复。检查点与实际答案不做
证据脱敏。`run_locator.json` 只定位本次 run ID 和记录目录，供监督进程交接。

当前分析工具读取新版调用生命周期，并保留官方 baseline 分析。汇总 token 数只表示已知部分；
统一指标与目录迁移已完成；回放暂缓。
