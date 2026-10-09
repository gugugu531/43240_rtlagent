> **文档状态：归档验证记录：只说明该次版本和测试范围。** 历史证据保留，当前框架用法与限制以[详细参考](../user-manual.md)为准。

# 第四阶段进展：配置与统一实验入口

## 已完成

按本阶段经审阅的范围实现配置加载、统一实验入口和可选指标，默认仍为近似 baseline 的
`single_generate`。Workflow、Node 和动作参数由 Python 定义；YAML 只选择 Workflow、
本地扩展、模型与工具服务、运行条件和实验，不提供 bindings 或流程图。
接口、配置字段和产物结构见[设计文档](../user-manual.md#12-开发实验与指标)。

- CLI、HTTP 与实验样本共用配置解析和 RunSpec 构造；严格检查未知字段、重复键、类型和版本，
  保存原始配置、生效值及逐字段来源。HTTP 的预算上限只能缩小配置预算。
- 每个 Agent 样本调用独立正式入口；题目选择支持单题、清单、排除和多次采样。
  固定题目顺序与题面/接口哈希，启动前检查输入变化，保留源码快照和样本记录。
- runtime/model 指标读取运行产物；judge 指标在开发区调用未改动的官方判定与聚合逻辑。
  不启用 judge 时不运行判定，参考答案和判定结果不进入 Agent 上下文。
- 求解与指标分别调度，外部求解与判定进程支持 TERM/INT 回收；取消、缺失数据和指标异常
  显式记录，模型 token 未知不写成零，环境失败不当作有效零分样本。
- 新笔记统一放入 dev/docs；旧 eval/remote 工具和旧实验记录暂未整体迁移。

## 验证与证据

本地回归命令：

```bash
PYTHONPATH=/tmp/fpgachina-stage1-deps python3 -m unittest discover -s 43240-agent/dev/tests -v
```

116 项测试通过，日志为 `/tmp/fpgachina-stage4-tests.log`。覆盖配置与优先级、调用者相对路径、
单题选择、任务变化、并发样本隔离、扩展 Workflow/Node、独立记录目录、指标异常、未知 token、
本地 HTTP 传输以及实验中断和子进程回收。本地 HTTP 测试使用可控服务，不能代替真实模型验证。
`git diff --check`、Python 编译检查通过；两个 baseline 文件与 example 逐字节相同。

| 实验 | 条件 | 结果与含义 |
| --- | --- | --- |
| [stage4-mock](../experiments/20261005-191114-stage4-mock-6e70ebfb.md) | ex03，两次 mock 采样，不启用 judge | 两个样本完成；验证入口、隔离与产物，不能证明功能正确 |
| [stage4-vivado-smoke](../experiments/20261005-191812-stage4-vivado-smoke-1b9df732.md) | ex03，mock 生成，真实 Vivado 判定 | L1；验证判定指标接入，不作为模型效果结论 |
| [stage4-real-single](../experiments/20261005-193024-stage4-real-single-ff1050ad.md) | ex03，真实 Qwen3-8B，Agent 与 baseline 各一次 | 均为 L3，各一次模型调用，runtime/model/judge 均正常；仅单题，不能推断整体增益 |

真实模型运行的 Agent 求解耗时约 3.75 秒，baseline 约 4.49 秒；两者均记录输入 271、输出
129 token。数字来自 stage4-real-single 的逐样本 solve.json 与 metrics.json，不包含后续判定耗时。
实验源码版本以该次 source 快照为准，运行时尚未提交；后续还有日志脱敏和记录目录相关修正，
最终版本通过本地回归，不能把运行快照直接等同于最终 commit。

另以同一真实服务验证 HTTP 入口：只通过 AGENT_CONFIG 指定模型配置，ex03 返回 HTTP 200、
完整规定字段与 380 字符答案，耗时约 3.49 秒。请求预算 60 秒，Worker 预算约 59.75 秒，
结果为 completed/c001；独立记录目录在请求临时目录删除后仍保留。
证据在 `dev/runs/20261005-stage4-http/` 的 response.json、服务日志及记录目录。

云端 GPU 本轮最小运算检查通过，真实模型请求正常。使用临时服务关闭 thinking，仅用于本轮
验证，不修改提交服务默认策略；本轮未复现此前 GPU 阻塞，仍不能确认其具体根因。
诊断日志在 `dev/runs/20261005-stage4-cloud/`。测试结束已销毁云端实例，状态为 not_found；
本地转发、HTTP 服务和防休眠进程已停止。remote.env 未修改或提交。

## 当前边界

- 历史模型回复重放、选择重放、自动消融比较和全量旧目录迁移尚未实现。
- 源码快照不包含依赖包或模型权重；扩展来源缺失或源码因脱敏改变时标为不完整。
- 自定义 Python 指标本身不受独立进程硬监督；本阶段中断验证针对受管理的外部求解和判定进程。
  自行脱离进程组的后代及共享模型服务的推理取消仍不作保证。
- 真实模型验证仅覆盖单题与正常 HTTP 请求，不证明全题集效果、异常请求下的后端推理取消
  或最终比赛 GPU 的兼容性。
- 本阶段仅整理本地提交，不推送或创建 PR。后续阶段须先交用户审阅具体架构与接口计划。
