# Python Workflow 与 Node 接口

本文描述当前提供的接口。默认流程是 `single_generate`：一次直接生成、提取和选择。
可选 `repair_loop` 包含多轮接口检查、lint 与综合反馈。官方 baseline 文件保持原样。

## 组织与依赖

```text
入口 → Supervisor → Worker 内 Runner → Workflow → ctx.execute(Node, input)
                               ↓
                       模型、工具、预算、候选与事件接口
```

Workflow 决定顺序、循环、异常处理和选择；Node 封装动作；服务负责调用与证据记录。
Runner 初始化本题环境、接收结果、保留已有答案并关闭记录，不决定求解策略。

实验 Workflow 与 Node 也放在 `agent/`。运行代码不能导入 `dev/` 或读取参考实现、官方判定信息。

## 注册与构造

```python
WORKFLOW_REGISTRY.register(name)(workflow_class)
NODE_REGISTRY.register(name)(node_class)

registry.get(name)       # 返回实现类
registry.names()         # 返回已注册名称
build_workflow(name, **params)
build_node(name, **params)
load_extensions(module_names)
```

名称只用英文小写字母、数字、下划线或连字符。重复注册与未知名称报错。
注册表不执行构造函数，不保存实例。内置组件显式导入；用户模块由 `load_extensions()` 或
CLI 的 `--import-module` 显式导入，不自动扫描目录。

组件必须提供 `run()` 与 `describe()`。可继承 `Component` 获得常规元数据描述；统一构造接口
会捕获参数，包括构造函数默认值。直接构造时，Component 从构造参数对应的实例属性获取描述，
取不到的字段明确标为 unknown。不能保存构造元数据属性的自定义对象需要自行返回等价描述。

`ComponentSpec` 保存注册名称、模块路径、实现类名和参数。描述为不可变快照，写入时脱敏。
任意对象不会通过 `repr()` 写入记录；不可描述的参数标为未知。

## 动作与流程契约

```python
class Node(Protocol[InputT, OutputT]):
    def run(self, ctx: RunContext, input: InputT) -> OutputT: ...
    def describe(self) -> ComponentSpec: ...

class Workflow(Protocol):
    def run(self, ctx: RunContext) -> WorkflowResult: ...
    def describe(self) -> ComponentSpec: ...
```

本阶段同步执行 Node，不提供并行调度器。输入输出可以是不同的类型；内置动作使用明确的
dataclass（数据类）。默认 Node 为生成、提取、接口检查、lint 和综合。
生成 Node 不重试，提取 Node 注册候选但不选择答案，检查 Node 只返回检查证据。

组件类型、温度、输出上限、提示方式、技能开关和轮数在 Workflow 的 Python 构造函数里指定。
外部服务配置只提供后端、地址、模型、凭据与服务超时上限。没有 YAML Node 列表或 bindings。

## 上下文公开接口

| 接口 | 用途 |
| --- | --- |
| `ctx.task` | 不可变 TaskSpec，包含题面、接口、目标模块与接口来源 |
| `ctx.execute(node, input)` | 执行动作并记录开始、结束、错误、耗时与父执行 |
| `ctx.llm.chat(request)` | 单次模型调用与完整响应记录 |
| `ctx.tools.check_interface(task, candidate)` | 确定性接口检查与证据记录 |
| `ctx.tools.lint/synth(candidate, top, timeout_s=...)` | 工具检查，实际调用时才初始化工具链 |
| `ctx.processes.run(ProcessRequest)` | 自定义外部动作，由 Supervisor 启动进程、保存日志并管理进程组 |
| `ctx.cancellation.cancel/raise_if_cancelled` | 进程内合作式取消；硬停止由外部监督提供 |
| `ctx.apply_selection(decision)` | 执行策略决定，保留或更新答案，必要时清除已确认无效的选择 |
| `ctx.budget.remaining_s/can_start/timeout_s` | 剩余时间、动作启动判断与超时上限 |
| `ctx.state` | 候选、检查、动作、当前选择与停止原因的只读快照 |
| `ctx.create_candidate(...)` | 分配本题候选 ID，登记来源并保存候选 |
| `ctx.register_candidate(candidate)` | 登记已有候选，拒绝重复 ID 或不存在的父候选 |
| `ctx.record_extraction(...)` | 保存提取结果，包括没有候选的提取 |
| `ctx.new_check_id()` | 分配本题检查 ID |
| `ctx.record_check(result)` | 记录自定义检查，要求关联已登记候选 |
| `ctx.select_candidate(id, reason=...)` | 显式选择，原子写答案并记录原因 |
| `ctx.emit(event, **fields)` | 保存流程决策或自定义事件 |
| `ctx.finish(reason=..., status=...)` | 返回当前选择与停止原因的结果快照 |

登记和选择分开。仅登记新候选不会更新 `solution.v`；选择规则由 Workflow 决定。
Runner 校验返回结果与本题状态、已写出答案一致。

Node 异常会记录并重新抛给 Workflow；框架不自动把异常转成修复动作。Workflow 可以显式处理，
未处理的普通异常由 Runner 记录并保留已经选择的答案。

## 自定义示例

以下示例只统计提示长度，再进行单次生成；不修改核心框架，也不读取判定信息：

```python
from agent.core.components import Component
from agent.core.registry import NODE_REGISTRY, WORKFLOW_REGISTRY, build_node
from agent.nodes.generate import GenerateInput
from agent.nodes.extract import ExtractInput


@NODE_REGISTRY.register("prompt_size")
class PromptSize(Component):
    def run(self, ctx, input: str) -> int:
        return len(input.encode("utf-8"))


@WORKFLOW_REGISTRY.register("record_size_then_generate")
class RecordSizeThenGenerate(Component):
    def __init__(self, max_tokens=8192):
        self.max_tokens = max_tokens
        self.size = build_node("prompt_size")
        self.generate = build_node(
            "rtl_generate", max_tokens=max_tokens, temperature=0.0,
        )
        self.extract = build_node("rtl_extract")

    def run(self, ctx):
        size = ctx.execute(self.size, ctx.task.prompt)
        ctx.emit("prompt_size", bytes=size)
        reply = ctx.execute(self.generate, GenerateInput(ctx.task))
        result = ctx.execute(self.extract, ExtractInput(reply))
        if result.candidate is not None:
            ctx.select_candidate(result.candidate.id, reason="single_generation")
        return ctx.finish(reason="completed")
```

放在可导入的 `agent/` 模块中，使用 `--import-module` 导入，再通过 `--workflow` 选择注册名称。

## 运行器与依赖注入

```python
runner = Runner(
    model_config,
    backend_factory=make_backend,
    toolchain_factory=RtlToolchain,
)
result = runner.run(
    task,
    lambda: build_workflow("single_generate", max_tokens=8192),
    options=RunOptions(output_dir=output_dir),
)
```

优先传入 Workflow 工厂，Runner 每题调用工厂获得新 Workflow 与 Node。也允许传入本题独立构造的
Workflow 实例；调用者不应跨题复用可变实例。Runner 每次创建独立上下文、记录器、候选状态与预算。
构造在输出文件建立后进行，未知注册名称和构造错误也能留下失败记录。

服务工厂可替换为假模型和假工具，用于模块或完整流程测试；不需要 GPU。

## 记录与当前边界

Node 执行使用 `e001` 等 ID；调用、候选和检查记录关联执行 ID。嵌套 `ctx.execute()` 记录父执行，
结束后恢复外层关联。输入输出保存摘要、哈希或对象引用，大段消息与正文仍由模型记录保存。
详细记录保存每个动作、候选、检查以及最终选择和停止原因，HTTP 独立目录可以保留这些证据。

统一检查状态为 `passed/failed/timeout/unavailable/error/skipped`；接口检查另外保存 blocking 和
来源详情。提示推断的接口差异可以是不阻断的 failed，不能标成检查通过。

预算采用单调时钟，超时取 Node 上限、服务上限与剩余预算中的较小值。`remaining_s(include_reserve=True)`
可查看包括清理预留时间的剩余量；`timeout_s(limit_s, minimum_s)` 不满足动作最低时间时抛 BudgetExhausted。
生成、lint 与综合 Node 允许设置 minimum_s。

生产入口使用 `Supervisor.run(RunSpec)`。RunSpec 保存任务、已注册 Workflow 名称和可序列化 Python
参数、扩展模块、运行选项及可选模型服务配置；Worker 内重建组件，不向生产边界传入闭包或实例。
Supervisor 强制停止阻塞 Worker 并管理公开进程服务；进程内 Runner 仍适合依赖注入和单元测试。
候选策略、失败策略和缓存的接口见 [可靠运行设计](runtime-reliability.md)。共享模型服务的内部推理
不在进程监督范围，自行脱离受管理进程组的子进程也不在保证范围。
YAML 加载、统一实验入口与可选指标已提供，见[配置与实验](configuration-and-experiments.md)。
历史重放尚未实现。
