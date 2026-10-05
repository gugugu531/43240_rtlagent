# 第三阶段实施与验证

日期：2026-10-05。用户已审阅第三阶段架构与接口计划，并授权实施。
设计见[候选、失败处理与运行监督](../design/runtime-reliability.md)。

## 已完成

- SelectionPolicy 与 FailurePolicy 独立于 Node 和服务，可以在 Python Workflow 构造时替换。
  记录实际生效的策略类型、参数和每次决定。最新候选、修复对象、已选答案分别管理。
- 默认选择只比较真实通过证据；明确代码或权威接口错误的候选不作为答案。后续较弱候选不能
  覆盖较强证据的答案；全部确认无效时清空选择。同等证据保留已有选择。
- 工具失败保守分类：明确代码诊断才修复，环境、超时与未知错误默认停止。retryable 模型连接、
  超时或 HTTP 错误按独立次数和总调用次数限制重试相同消息，模型服务本身不重试。
- 本题 CheckCache 使用任务、源码、检查种类、配置和工具身份。复用记录新 check ID、当前候选、
  原证据 ID 和 executed=false；未知身份、环境错误、超时和未知失败不复用。
- Budget 区分求解与清理预留；动作可以声明 minimum_s。进程内 CancellationToken 提供合作式取消。
- 正式 CLI 使用 RunSpec 与独立 Worker，在 Worker 中构造注册组件。保留进程内 Runner 的
  依赖注入能力。Supervisor 按墙钟预算与信号终止 Worker，并通过自己持有的 ProcessExecutor
  启动、终止、回收工具进程组。Linux subreaper 用于接管并回收孤儿后代。
- 自定义外部动作可通过 ctx.processes.run 调用，带预算和开始、结果证据。工具完整日志在临时目录
  删除前写入独立记录目录；Supervisor 持有的进程输出在强制中断时也能留下证据，保存副本脱敏。
- 每次选择先原子提交正文与来源检查点，再替换 solution；监督进程校验哈希并恢复。Worker 停止后
  才交接 trace；未完成的调用和 Node 不伪造结束，部分 JSONL 最后一行单独保留。
- shell 转发 TERM；HTTP 覆盖准备、执行、清理和返回预算，移除 5 秒超时下限。官方 baseline
  只增加外部监督，原始两个文件不修改。默认 single_generate 仍单次调用、无技能、无检查、无重试。
- trace 格式更新为 4，分析工具按 check ID 合并开始和结果，复用另计，保留官方 baseline 分析。

## 验证

本阶段本地验收日志为 `/tmp/stage3-tests.txt`；示例 smoke 输出为 `/tmp/fpgachina-stage3-smoke/`。
这些是本地验证文件，不纳入仓库或正式提交，不是模型跑分实验。

```bash
PYTHONPATH=/tmp/fpgachina-stage1-deps python3 -m unittest discover -s 43240-agent/dev/tests -v
LLM_BACKEND=mock 43240-agent/run.sh tasks/ex03_lfsr8 /tmp/fpgachina-stage3-smoke
cmp example/baseline.py 43240-agent/baseline.py
cmp example/run_baseline.sh 43240-agent/run_baseline.sh
```

结果：97 项测试通过。覆盖真实阻塞 Python Workflow、选择恢复、忽略 TERM 的工具及其后代回收、
阻塞模型 HTTP 请求、shell 收到 SIGTERM 后在测试的 3 秒上限内退出、HTTP 1 秒预算不被扩大到
5 秒、同一请求重试、确认错误与未知错误分离、修复对象与最终答案分离、检查复用与统计、完整
工具日志在工作目录删除后保留且脱敏、trace 最后一行中断及启动预算耗尽。

默认示例单题：1 次模型调用、0 次检查、solution.v 为 177 字节，选择恢复校验通过，
监督记录没有未回收进程。两个 baseline 文件与 example 逐字节相同，git diff --check 通过。

测试中的模型、编译器输出是假数据，进程、信号和本地 HTTP 生命周期是真实执行。
上述提交前验收未启动云端实例，未使用真实模型或 Vivado；这些验证不能证明代码功能正确、
得分改善或真实工具诊断覆盖充分。用户随后授权的真实 Vivado、HTTP 与云端尝试见
[后续验证](2026-10-05-stage3-remote-validation.md)：本机工具通过；首次云端尝试阻塞后，重新启动的 GPU 诊断与真实模型小规模测试已完成，
见[最新验证](2026-10-05-gpu-diagnosis-and-model-validation.md)。具体 GPU 故障根因仍未确认。

## 当前边界与后续

- 硬监督针对 Linux 正式入口和公开服务管理的进程组；自定义动作自行脱离管理的子进程不受保证。
  进程内 Runner 不提供自由 Python 阻塞的硬停止。强制停止可能留下工具临时工作目录，需后续清理策略。
- 客户端结束不证明共享模型服务已取消推理，明确记录 backend_inference_cancelled=unknown。
- 诊断只确认有限的代码错误形式，未知失败保留日志并停止。工具检查重试、其他选择策略可以通过
  自定义 Workflow / policy 做实验，当前没有自动猜测修复原因。
- 尚未提供 YAML 配置加载、统一实验入口、测评指标、历史重放；这些需在下一阶段先交用户审阅计划。
- 当前阶段完成后只作本地独立 commit，暂不推送或创建 PR。用户已有实验笔记不纳入本阶段提交。
