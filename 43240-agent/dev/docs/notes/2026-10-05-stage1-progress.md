> **文档状态：归档验证记录：只说明该次版本和测试范围。** 历史证据保留，当前框架用法与限制以[详细参考](../user-manual.md)为准。

# Agent 重构第一阶段进展

| 项目 | 状态 |
| --- | --- |
| 范围 | 模型调用与证据记录；单题、HTTP 入口接入 |
| 分支 | `feat/model-call-recording`，基于已合并文档的 `main`（`4e5fa0e`） |
| 实施 | 已完成，独立提交为 `edd791f`；尚未推送 |
| 后续 | 第二阶段开始前先提供具体架构与接口计划，等待审阅 |

总体方向见[设计方案](2026-10-05-agent-redesign-plan.md)，记录格式见
[记录格式](../design/trace-schema.md)。本阶段不实现 Workflow、Node、注册机制、统一指标或目录整体迁移。
不为旧模型客户端和旧 trace API 提供兼容层；官方入口保持规定的参数与响应结构。

## 已完成

模型层分为 `core` 的请求、回复、错误与配置契约，以及 `services` 的传输与标准化服务。
`ModelService.chat(request)` 只执行一次调用。HTTP 后端返回完整响应文本；服务先记录再解析，
因此非 JSON、HTTP 错误和合法 JSON 中不符合协议的响应都能留下诊断证据。

`ModelReply` 提供调用 ID、正文、模型名、服务请求 ID、结束原因、用量、耗时和响应引用。
未知用量保留 `null`；mock 只提供明确标记的正文，不伪造 HTTP 或 token 数据。
`ModelCallError.kind` 区分配置、连接、超时、HTTP、JSON、响应结构和后端内部错误；服务不自动重试。

`RunRecorder` 负责必要 trace 和可选详细记录。默认 full，basic 只写 trace。
详细文件包含请求、原始响应文本、完整 JSON、正文、标准结果及提取证据，均写入脱敏副本。
响应中的 reasoning 与额外字段不会因标准化而丢失。敏感信息过滤不会修改实际输入或提取正文。

每次调用有独立 `m001` 等编号。提取失败仍保存其状态与诊断；成功候选记录
`source_call_id`。因此可以沿最终候选、来源调用、原始正文和提取结果追踪问题。
本阶段沿用现有候选选择策略，后续模型失败仍保留已经原子写出的答案。

单题入口支持 `--record-root`、`--record-level`；`run.sh` 仍是两个位置参数。
HTTP 子进程继承 `AGENT_RECORD_ROOT`，并记录实际请求的 task ID；配置独立根目录后，
请求临时目录删除不影响详细记录。请求响应仍只有官方规定的字段。

必要 trace 写入失败作为基础设施故障处理。可选详细文件写入失败发出警告，尽可能在 manifest
标记 `recording_incomplete`；原模型结果和错误保持原样。中途终止只留下实际已发生的事件，
没有结束事件的调用仍是未完成状态。

现有分析器作了随 trace 格式升级所需的小幅调整：开始与结束不重复计数，未完成调用计为一次尝试，
读取新的 `finish_reason`，记录警告不算工具调用。未知用量的汇总仅表示已知部分；统一指标仍待实现。

## 验证

在本分支工作区运行：

```bash
python3 -m unittest discover -s 43240-agent/dev/tests -v
diff example/baseline.py 43240-agent/baseline.py
diff example/run_baseline.sh 43240-agent/run_baseline.sh
git diff --check
```

测试结果：62 项全部通过。覆盖成功响应与扩展字段、参数传递、错误证据、无响应错误、脱敏、
请求不可变、详细记录失败、必要 trace 失败、未完成调用、截断与多草稿、多轮候选来源、
单题缺少 interface.txt、相对路径、HTTP 临时目录清理和已有工具进程管理。
单题与 HTTP 用真实 `run.sh` 子进程、mock 模型和排除 Vivado 的 PATH 检查契约；没有运行真实模型或 GPU 测评。

本机默认 Python 缺少项目已声明的 FastAPI 依赖，因此将测试依赖安装在
`/tmp/fpgachina-stage1-deps`，通过 `PYTHONPATH` 加载；没有修改工作区环境或依赖版本要求。
测试日志保存于本机 `/tmp/stage1-test-result.txt`。正常安装 `requirements.txt` 的环境可直接执行上述命令。
基线逐字一致，官方只读文件未改动，用户已有未跟踪实验记录未纳入本次改动。

## 当前限制

HTTP 未设置独立根目录时，详细记录仍随临时目录删除。显式设置 `AGENT_RECORD_ROOT` 才能持久保存。
进程强制退出不保证 manifest 写入结束状态，应联合调用状态和 trace 判断是否完成。
详细记录需要额外存储和写入时间，目前没有做真实模型性能测试或自动清理策略。
Python Workflow、Node 注册、统一实验入口、模块消融与最终目录精简均未开始。
