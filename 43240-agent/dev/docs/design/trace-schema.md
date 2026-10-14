# 运行记录格式

本文是当前接口的专题参考；完整索引见[User Manual](../user-manual.md)。

本文描述当前 Agent 记录。官方 baseline 保持原样，使用官方 trace 格式。

## 对外 trace

`trace.jsonl` 必须存在，每行一个 JSON 对象。公共字段包括
`run_id`、递增的 `seq`、Unix 时间戳 `ts`、事件类别 `tool` 和动作 `event`。

trace 不记录格式版本。需要确定格式时，看 `run/metadata` 中 `git.commit` 记录的 7 位短 hash。
旧记录里可能还有 `schema_version` 字段，日志查看器和分析工具会忽略它。
检查状态使用 `passed/failed/timeout/unavailable/error/skipped`。

模型调用分为三个事件：

| 事件 | 内容 |
| --- | --- |
| `llm/started` | `call_id`、用途 `purpose`、公开服务配置 |
| `llm/succeeded` | `call_id`、模型名、服务请求 ID、`finish_reason`、耗时、token 用量、响应引用 |
| `llm/failed` | `call_id`、错误 `kind`、`retryable`、HTTP 状态码、耗时、错误摘要、证据引用 |

开始事件和结束事件属于同一次调用。进程被终止时允许只有开始事件。未知 token 用量是
`null`，实际的零是 `0`。mock 明确标记为 mock，不生成 HTTP 响应文件或假用量。

`node/started` 保存执行 ID、父执行、组件参数和输入摘要；`node/succeeded` 只保存执行 ID、耗时和输出摘要，
`node/failed` 只保存执行 ID、耗时和错误类型与信息，不重复开始事件已有的字段。
输入输出摘要只保留引用：候选写成 `candidate_id`，模型回复写成 `call_id`，检查结果写成 `check_id` 和状态；
不超过 80 字符的单行字符串原样保留，更长的文本只记字节数和 sha256。
模型调用、提取、候选与工具事件附带所属 `execution_id`，嵌套动作结束后恢复父动作关联。

`extract/result` 记录调用 ID、候选 ID（没有候选时为 `null`）、完整性、模块名、多草稿、
截断标记和诊断。`candidate/create` 记录 `source_call_id`，可从最终选择追溯生成来源。
工具事件记录命令、状态、返回码、耗时、摘要，以及完整日志所在的 `log_paths`。检查的 `details.executed=false` 表示复用，
`reused_from_check_id` 指向原检查；不计为新工具执行。`workflow/check_started` 与完成结果按 check ID 合并，
只有开始事件时记为未完成尝试。模型正文不内联到 trace；摘要最多 2000 字符。

可选 `behavior` 检查的 `details` 将模型假设和公开属性分开统计：
`hypothesis_assertions`、`property_assertions` 只计已知观察，
`hypothesis_mismatches`、`property_mismatches` 只计确定失配；
`hypothesis_inconclusive`、`property_inconclusive` 分别统计无法判定的观察，不计入前两类。
总 `assertions` 和 `mismatches` 分别为两类已知计数之和。旧记录缺少不确定计数字段时应视为未知，
不能补成零。`first_mismatch` 只指向确定失配。支持范围与状态判定见[规格自测基础](spec-test-foundation.md)。

`run/recording` 记录等级和详细目录，`run/metadata` 记录题目 ID、Workflow 类型与参数、公开服务配置、运行预算、
配置生效值及来源（`configuration`，实验样本另有指向实验配置的 `parent_config`）与 Git 信息。
Git commit 只记 7 位短 hash。Git 不可用时记录未知，也可以通过构建环境注入 commit 和 dirty 状态；注入完整 hash 时同样截成 7 位。
`candidate/select` 记录选中的候选和原因；`supervisor/result` 记录停止原因、Worker 退出码、选择恢复、
清理状态与后端取消状态。

## 详细文件

`RecordingConfig(level="full", root=...)` 开启完整记录；默认是 full。未指定 root 时放在
`<输出目录>/records/<run_id>/`，指定 root 时放在 `<root>/<run_id>/`。

详细目录只保存 trace 装不下的正文，每份数据只存一处：

- `task.json`：本题允许提供的题面、接口及解析来源。
- `calls/m001/request.json`：实际消息与请求参数。HTTP 身份验证头不写入；公开服务配置在 `llm/started` 事件里。
- `calls/m001/response.json`：响应是合法 JSON 时保存完整内容，保留 reasoning、其他 choices 与供应方字段。
- `calls/m001/response.txt`：响应不是合法 JSON 时保存原始文本；mock 保存它生成的正文。两者只会有一个。
- `candidates/c001.v`：候选代码；来源、父候选和哈希在 `candidate/create` 事件里。
- `process_logs/`：Supervisor 持有的完整进程输出，强制中断时仍可保留；检查事件的 `log_paths` 指向这里。
  没有 Supervisor 的进程内运行（例如单元测试）退回到 `tool_logs/`。

调用状态、提取结论、Node 执行、检查结果、选择和监督结果只写在 trace 中，不再另存文件。

`ArtifactRef` 由 run ID 和相对文件路径组成。调用 ID 在一次运行内递增；每次运行使用新 run ID。
HTTP 设置独立记录根目录后，请求临时目录清理不影响这些文件。basic 等级不写详细文件。

## 故障与秘密处理

保存的是脱敏副本：递归隐藏敏感字段、替换环境与显式服务配置中的秘密、过滤 URL 凭据和查询参数。
这不会修改发送给模型的请求，也不会修改用于提取的正文。文件写入采用同目录临时文件和原子替换。

先解析 JSON，再保存响应（合法 JSON 存为 response.json，否则存原始文本），最后检查 HTTP 状态和响应字段，
因此 HTTP 错误、非 JSON 和响应字段错误仍有证据。
连接失败或超时未收到响应时，不创建虚构响应文件。可重试标记供 Workflow 的失败处理判断，服务本身不重试。

详细文件不可写时，发出 `recording/warning`。
原模型结果和错误保持原样。必要 trace 不可写则抛出 `RecordingError`，按基础设施故障处理。
Supervisor 只在 Worker 停止后接管记录，追加 `supervisor/result`，其中 `status` 标明是否被中断。
已有调用和 Node 的 started 状态保持原样，不能用监督结果伪造调用结束。最后一行若被打断，原始
片段另存为输出目录的 `trace_partial.txt`，返回 trace 保持有效 JSONL。
`backend_inference_cancelled=unknown` 明确表示只确认客户端结束，不能确认共享服务已取消推理。

输出目录中的 `selection.json` 是必须写入的恢复检查点，包含实际候选代码、来源、哈希和原因。
先原子提交检查点，再更新 solution；Supervisor 校验哈希后完成必要的恢复。检查点与实际答案不做
证据脱敏。run ID 由 Supervisor 生成后传给 Worker，因此两边不需要额外的交接文件。

当前分析工具读取新版调用生命周期，并保留官方 baseline 分析。汇总 token 数只表示已知部分；
通用历史 trace 重放尚未实现。E1/E2 的初始检查点重放是另一项能力，见[运行接口](agent-runtime.md)。
