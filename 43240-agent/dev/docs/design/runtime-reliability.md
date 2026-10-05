# 第三阶段：候选、失败处理与运行监督设计

本阶段按用户审阅的计划完善可靠运行。默认 single_generate 保持单次生成，不添加检查、技能或重试。
实现与验证结果单独写入[阶段进展](../notes/2026-10-05-stage3-progress.md)。

## 架构分工

```text
单题 CLI / run.sh
  └─ Supervisor：单调时钟、取消信号、Worker 生命周期、输出恢复、记录交接
       ├─ Worker：Runner → Python Workflow → Node / 服务
       │    ├─ SelectionPolicy / FailurePolicy：由 Workflow 构造并选择
       │    └─ ToolService / CheckCache：执行和保存证据，不决定修复策略
       └─ ProcessExecutor：启动工具进程、管理进程组、记录输出、TERM / KILL / 回收
```

HTTP 外层监督 Agent shell 或原始 baseline shell。baseline 不进入 Node、策略或检查缓存。
生产运行使用独立 Worker；进程内 Runner 用于模块测试、依赖注入和调试。
当前是 Linux 同步实现，一个 Worker 同时等待一个外部命令，不引入并行 Node 调度。

## 候选与选择

```python
SelectionPolicy.choose(candidates, checks, current_id) -> SelectionDecision
SelectionDecision(candidate_id, changed, reason, evidence_ids)
ctx.apply_selection(decision) -> None
```

latest 是刚提取的候选；repair_target 是下次反馈携带的代码；selected 是已经落盘的答案。
它们不能用同一个变量代替。自定义 Workflow 可以替换选择策略，也可以直接显式选择。
策略可继承 Component 描述参数，实际生效的选择与失败策略写入 workflow/policies，支持实验追溯。

默认选择策略排除不完整、目标缺失、确认代码错误或权威接口失败的候选。其余候选先比较真实综合
通过，再比较 lint 和接口通过；同等证据保留已有选择，没有已有选择时保留较早候选。
只有完整提取但未验证的代码可作回退；超时、环境错误和未知状态不增加通过证据。
确认所有候选无效时清除答案，避免继续提交已经确认错误的代码。综合通过不证明功能正确。

选择先原子写入包含正文、候选 ID、来源、哈希和理由的检查点，再原子替换 solution。
Supervisor 接管后检查身份和哈希，可以完成尚未写出的答案更新；无效检查点不得虚构选择来源。

## 失败判断与次数边界

```python
Diagnostic(kind, message, confidence, source_id, code=None)
classify_model_error(error) -> Diagnostic
classify_check(result) -> tuple[Diagnostic, ...]
FailurePolicy.decide(diagnostics, attempts, budget) -> FailureDecision
AttemptState(model_calls, request_retries, repairs)
FailureDecision(action, reason, diagnostic_ids)
```

诊断区分确认代码错误、模型可重试错误、模型终止错误、环境故障、超时和未知。
普通非零退出不足以归因 RTL；只有明确的编译器代码诊断和阻断接口差异触发修复。
工具许可、路径等问题属于环境。无法确认原因时保留 unknown 与完整日志，默认停止。

可重试模型连接、超时和指定 HTTP 状态在预算与次数允许时重试相同消息；配置、认证、JSON
和响应字段错误默认终止。重试与修复次数分别记录，所有模型调用还受总数限制。
repair_loop 默认最多 3 轮、每个请求 1 次重试、4 次模型调用。服务和 Node 本身不自动重试。
工具环境错误和超时当前采用停止策略；需要检查重试的实验可以定义自己的 Workflow。

## 本题检查复用

```python
CheckKey(task_fingerprint, code_hash, kind, config_fingerprint, tool_fingerprint)
CheckCache.get(key) -> CheckResult | None
CheckCache.put(key, result) -> None
```

缓存只活在本题上下文中。相同题面、接口、top、代码、检查种类、配置和工具身份才允许命中。
工具身份由二进制路径与文件身份、环境、器件和工具实现摘要组成；自定义工具需要提供 fingerprint。
身份未知时不复用。只保存真实通过或明确代码失败，不缓存环境错误、超时和未知失败。

重复源码仍保留新的候选 ID、模型调用和父子关系。复用生成新的 check ID，关联当前候选与原始
check ID，标记 executed=false，不重新执行工具，也不伪造耗时。

## 时间、取消与进程

```python
Budget.remaining_s(include_reserve=False) -> float
Budget.can_start(minimum_s=0) -> bool
Budget.timeout_s(limit_s, minimum_s=0) -> float
CancellationToken.cancel(reason) -> None
CancellationToken.raise_if_cancelled() -> None

Supervisor.run(spec: RunSpec) -> WorkflowResult
Supervisor.cancel(reason='cancelled') -> None
ProcessExecutor.run(request: ProcessRequest) -> ProcessResult
ProcessExecutor.cancel_all(deadline) -> CleanupResult
ctx.processes.run(request: ProcessRequest) -> ProcessResult
```

RunSpec 是可重建的生产输入：TaskSpec、注册名称、JSON 可序列化参数、扩展模块、RunOptions、
开始时刻和可选 ModelConfig；不接受 Workflow 闭包或正在使用的 Node 实例。
RunOptions 保存输出、总预算、清理预留和记录设置。模型和工具按实际剩余时间封顶；Node 可以
声明 minimum_s。预算小于预留时间时不启动求解。

ProcessRequest 保存 command、cwd、timeout_s、可选 env 和 TERM 等待时间。
ProcessResult 保存 rc、status、elapsed_s、output；CleanupResult 保存已终止进程组和未回收进程。
工具实际由 Supervisor 启动，Worker 用本地管道等待结果，避免仅杀 Worker 后留下独立会话工具。
超时或取消先 TERM，再有界 KILL；Linux Supervisor 采用 subreaper（接管孤儿后代进程）并回收。
日志写文件，避免输出管道占满或后代持有管道阻止返回。

自定义外部动作使用 ctx.processes；自行启动并脱离受管理进程组的子进程不受保证。
关闭模型客户端仅确认连接侧停止，不能据此声称共享后端取消了推理；记录 unknown。

HTTP deadline 从请求开始，覆盖准备、运行、清理和读结果。外层为清理和返回留出时间，不设
5 秒下限。shell 转发 TERM 给 Supervisor；正式流程必须满足官方 SIGTERM 后 10 秒退出要求。

## 记录交接与边界

Worker 是唯一 trace 写入者。Supervisor 确认 Worker 停止后接管，保存真实停止、清理和恢复结果。
正在执行的模型、Node 或工具保留开始状态，不编造结束事件。详细目录在 full 模式保存工具
完整日志和监督结果；最后一行中断的 trace 片段单独保存。

本阶段不增加 YAML 加载、统一实验入口、测评指标或重放机制。这些仍需在后续阶段审阅计划。
