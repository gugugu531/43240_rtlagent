> **文档状态：归档验证记录：只说明该次版本和测试范围。** 历史证据保留，当前框架用法与限制以[详细参考](../user-manual.md)为准。

# Agent 重构第二阶段进展

| 项目 | 状态 |
| --- | --- |
| 范围 | Registry、运行上下文、Node、Python Workflow 与运行器 |
| 审阅调整 | 默认 Workflow 使用近似 baseline 的单次生成策略；其余按已审阅计划执行 |
| 分支 | `feat/python-workflows`，依赖第一阶段提交 `edd791f` |
| 实施 | 已完成，代码与本记录形成第二阶段独立提交；尚未推送 |
| 后续 | 下一阶段先提交具体计划，审阅后才开始修改 |

总体设计见[设计方案](2026-10-05-agent-redesign-plan.md)，公开接口见
[Python Workflow 接口](../design/python-workflows.md)，记录格式见[记录格式](../design/trace-schema.md)。

## 已完成

默认 `single_generate` 只进行一次直接生成、提取和显式选择，不加载技能或执行接口、lint、综合。
默认温度为 0，输出上限为 8192，Node 超时上限为 300 秒；实际请求还受模型服务上限和剩余预算限制。
官方 baseline 入口与文件保持原样。默认 Agent 仍使用自己的模型服务、提取器与完整记录。

`repair_loop` 是可选流程，使用生成、提取、接口、lint、综合 Node 组织多轮修复。
默认最多 3 轮、温度 0.2、输出上限 4096，继续选择最新提取候选，后续模型失败保留已写出的答案。
本阶段不增加质量排序、检查缓存或错误重试策略。

`NODE_REGISTRY` 与 `WORKFLOW_REGISTRY` 只登记实现类，拒绝重复名称，支持查询、构造和显式模块导入。
组件类型和构造参数由 Python Workflow 指定；外部服务配置只描述后端、模型、地址、凭据和超时上限。
旧的 `LLM_MAX_TOKENS`、`LLM_TEMPERATURE`、`AGENT_MAX_ROUNDS` 不再读取，没有旧内部接口转发层。

`RunContext` 保存本题候选、检查与执行历史，公开只读状态和显式操作方法。
候选登记与答案选择分开；只有选择才原子更新 `solution.v`。`ctx.finish()` 返回状态快照，
运行器校验返回结果与本题状态、已写出的选择一致。

`ctx.execute()` 自动记录动作开始、结束、耗时、参数、父执行和错误详情；模型调用、候选与检查关联
所属执行 ID。嵌套动作结束后恢复外层关联。完整模型文本仍由模型记录保存，动作只写摘要或引用。
自定义组件明确提供描述，不可获取的参数标为未知；敏感构造参数与错误中的已知秘密统一脱敏。

`Runner` 建立逐题上下文、服务、预算与产物，支持注入假服务；优先使用每题创建实例的 Workflow 工厂。
未处理普通异常被记录，保留已选答案。工具链只在调用工具时初始化，默认流程不会探测 Vivado。
时间预算使用单调时钟，调用超时由动作上限、服务上限与剩余时间共同限制。

单题与 HTTP 复用同一入口，`run.sh` 的两个位置参数和官方 HTTP 响应字段没有改变。
新增 `--workflow`、`--import-module` 等 Python 入口选项，`AGENT_WORKFLOW` 可供 shell 与 HTTP 选择流程。
详细记录保存任务、Node、候选、检查、最终选择和停止原因；独立目录中的记录不会随 HTTP 临时目录删除。

trace 升级为 version 3，统一检查状态为 passed、failed、timeout、unavailable、error、skipped。
现有分析器不把 Node、候选选择、提取或生命周期事件计为工具调用，模型开始与结束仍只计一次。
模型声明和 manifest 已同步默认流程及 8192 输出上限；其他模型与服务占位项仍未完成实测填写。

## 验证

在本分支工作区执行：

```bash
python3 -m unittest discover -s 43240-agent/dev/tests -v
LLM_BACKEND=mock AGENT_WORKFLOW=single_generate \
  AGENT_RECORD_ROOT=/tmp/fpgachina-stage2-smoke-records \
  43240-agent/run.sh tasks/ex03_lfsr8 /tmp/fpgachina-stage2-smoke
diff example/baseline.py 43240-agent/baseline.py
diff example/run_baseline.sh 43240-agent/run_baseline.sh
git diff --check
```

结果：78 项测试全部通过。覆盖默认策略、多轮反馈与候选来源、自定义组件注册、重复名称与构造错误、
逐题状态隔离、嵌套动作、不可变视图、结果一致性、Node 错误、秘密脱敏、预算耗尽、记录失败、
工具初始化失败、单题路径与 HTTP 持久记录，以及第一阶段和已有工具测试。

示例题 smoke 检查确认模型完成调用 1 次、工具检查 0 次，生成了非空答案；分析器也报告 1 次模型调用和零工具调用。
此检查只验证流程与接口，不表示 mock 答案功能正确。测试使用假模型与假工具，没有真实模型或 GPU 跑分。
本机 FastAPI 测试依赖从 `/tmp/fpgachina-stage1-deps` 加载；日志在 `/tmp/stage2-test-result.txt`。

官方 baseline 逐字一致，官方只读文件未变更。用户已有未跟踪实验记录未纳入本阶段提交。

## 当前边界

- 预算仍是合作式控制，不能强制停止任意 Python 阻塞、回收整个任务子进程树或取消服务端推理。
- 可选修复流程仍可能用新的较差候选覆盖旧选择；质量保护、重复检查复用和错误路由属于下一阶段。
- 没有 YAML 加载、统一实验工具、可选测评指标或重放，也没有整体迁移旧 dev 目录。
- 部分工具完整日志仍依赖 `AGENT_KEEP_WORK=1`，详细记录尚无磁盘清理策略。
