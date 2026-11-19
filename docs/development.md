# 模块扩展与开发规范

[文档入口](index.md) · [架构与设计原则](architecture.md)

本规范针对当前基于 Burr 的实现。Burr 用于组织节点、状态和条件连线。修改前先确认目标仓库、分支、提交和未提交改动；示例、测试与真实运行必须指向同一份源码。不要从目录名、旧笔记或另一个工作树的结果推断当前能力。

## 1. 先决定扩展放在哪里

| 变化 | 应修改的位置 | 最少需要说明的契约 |
| --- | --- | --- |
| 多一个求解阶段或阶段实现 | `agent/orchestration/nodes/` | 输入状态、输出状态、节点参数、模型与工具调用、失败语义 |
| 一项可复用工具能力 | 工具注册适配层与相应领域模块 | 参数类型、返回结构、预算、错误与调用证据 |
| 调整阶段顺序、条件或重试策略 | `agent/orchestration/workflows/` | 初始状态、节点别名、分支优先级、终止条件与上限 |
| 改默认预算或替换已有节点 | `config/` | 有效覆盖值、兼容范围；不以 YAML 实现新流程逻辑 |
| 新模型协议或后端 | `agent/llm/` 与 `agent/config.py` | 请求、分词、生成声明、错误、用量、重放与真实服务验证 |
| 新 RTL（寄存器传输级）检查语义或仿真能力 | `agent/domain/rtl/` 与检查工具适配层 | 输入范围、未知值、采样、比较、候选／检查器身份 |
| 固定方法或诊断卡 | `skill/`、`knowledge/`、`agent/domain/knowledge/` | 适用边界、使用阶段、完整正文、实际使用内容的记录方式；见 [知识契约](knowledge.md) |
| 新提示模板 | `agent/context/prompts/`；检查表、逐点复核和解题决策的请求分别见 `agent/domain/rtl/` 的 `guided_checker.py`、`guided_revision.py` 和 `guided_author.py` | 模板变量、公开信息边界、响应数据结构（schema）、语义校验 |
| 预算、进程或记录机制 | `agent/runtime/`、`agent/observability/` | 跨工作流兼容、取消、资源回收、日志字段与迁移行为 |

先复用已有能力，再新增接口。相同检查逻辑不应分别复制到节点、工具调用和新工作流中。仅更换参数不必新建实现；改变输入／输出或失败语义时，不能假装只是一个预设。

## 2. 公共入口与三个名称

扩展通常从 `agent.kit` 导入 `Ctx`、`State`、`node`、`tool`、`workflow`、`when`、`expr`、`default`、`CheckResult`。RTL 相关类型和函数按需要从 `agent.domain.rtl` 下的具体模块导入；通用运行时内部不要反向依赖 `agent.kit` 这一汇总入口。

三个名称不要混用：

- **注册名**：装饰器的名称，例如 `counter_advance`，对应具体 Python 实现。
- **节点别名**：某个工作流里的位置，例如 `advance`。连线、入口、日志节点名和 YAML 的 `nodes` 键引用它。
- **工具别名**：工作流或配置中的调用名称，例如 `increment`。`ctx.call("increment", ...)` 经配置选择具体注册实现。

`use` 引用注册名。`node`、`tool`、`workflow` 使用三个独立注册表，同一注册表重名会报错。装饰器注册发生在模块导入时：新增内置模块必须加入 `agent/orchestration/nodes/__init__.py` 或 `agent/orchestration/workflows/__init__.py`；也可通过显式插件导入。仅创建一个文件不会自动启用。

## 3. 节点契约

```python
@node("implementation_name", reads=["input_field"], writes=["output_field"])
def stage(ctx: Ctx, state: State, *, limit: int = 2) -> State:
    # 执行有界操作，返回新的 State。
    return state.update(output_field=state["input_field"] + limit)
```

上面是签名示意，完整可执行例见第 8 节。

- `ctx` 在前，`state` 在后；返回 Burr `State`，不返回表示局部更新的字典。当前接口不使用旧架构的 `Runtime[Ctx]`、状态归并函数（reducer）或调度基类。
- 声明实际读取与更新的字段，初始读取字段由工作流的 `state` 或构造函数初始化。包括分支判断依赖的字段、错误状态和停止原因，不只声明成功分支。
- 状态必须能直接序列化为 JSON，不能包含 NaN、文件句柄、客户端或进程对象。用 `state.update()` 更新，不原地修改内部字典或嵌套对象。
- 配置参数应使用类型注解与明确默认值。参数适配器拒绝未知名称、`*args`、`**kwargs` 和位置专用参数，节点参数在构造运行图时严格验证。
- `reads`、`writes` 声明是图契约，不是 Python 沙箱；开发者仍须保证真实实现遵守它们，并测试状态变化与分支。
- 跨阶段的决定写到状态，再交给图路由。节点内重问必须有限且记录每次尝试；不要吞掉取消、截止或环境失败后假装完成。

## 4. 工具契约

工具函数形如 `fn(ctx: Ctx, candidate_id: str, *, timeout_s: float = 300)`。**当前 `Ctx.call()` 无条件注入首参 ctx**，不支持无 ctx 的原生函数直接注册。`ctx`、`state` 是参数适配器排除的保留名称，不要将工具业务参数命名为 `state`。

`ctx.call(alias, ...)` 先取得该别名的配置参数，再以本次调用参数覆盖，最后严格校验完整参数。工具配置在构造运行图时只预检已提供的参数，调用时才检查必需参数是否齐全。调用返回原对象，并自动记录开始、结束、结果摘要与错误；同次调用的日志由 `span_id` 关联。

返回值若需要进入日志或作为工具结果返回模型，应为可序列化为 JSON 的数据，或记录器支持的数据类及 Pydantic 模型；RTL 检查优先使用 `CheckResult`，通过 `bind_result()` 关联实际候选和检查器版本。`Literal` 类型注解本身不等于普通 `dataclass` 的运行时校验，适配层必须保证值正确。

外部命令使用 `ctx.processes.run(command, cwd=..., timeout_s=...)`，命令为参数列表。不要另起不受管理的 subprocess 或把用户文本拼成 shell 命令；环境不可用、超时、返回码错误与 RTL 失败分别处理。程序退出码 0 之外仍要检查实际产物、采样与比较数据。

模型工具调用可使用 `ctx.tool_schema(alias)` 与 `ctx.llm.run_tools(...)`。参数结构来自完整函数签名，不会自动隐藏配置已经给定的参数；`ctx.call()` 对未配置名字还会查询注册表，所以 `tools` 配置并非访问控制白名单。模型可调用范围应显式传给 `run_tools`，插件也必须来自可信源码。

## 5. 工作流与配置契约

`@workflow(...)` 声明节点、工具、工作流默认参数和初始状态。构造函数接收 `(builder, p)`，返回配置了状态、条件连线和入口的 `builder`；不要在构造函数发出模型或工具请求。

新节点通过 `workflow.nodes` 注册映射装配，不能只用 `builder` 添加动作：记录钩子与图元数据会查阅该映射。条件连线引用图中别名，按所需优先级列出，将兜底 `default` 放在相关条件之后。为循环定义正常结束、失败与证据不足时的去向。`guided_verify` 的结构修复、解题改稿、检查表格式修正和逐点复核共用单题预算，重复无进展的格式错误也有相应的退出条件。

运行器把别名 **`finish`** 视为终止动作；不要用它命名中途阶段。仅设置 `state.status="completed"` 不会自动停止其他连线。图无下一步也可结束。设置 `runtime.max_steps` 后，走完指定步数仍未结束就记录 `max_steps`。值为 `null` 时取消步数上限，每步仍检查运行时限。

配置规则以 [config.py](../agent/config.py) 和 [graph.py](../agent/orchestration/graph.py) 为准：

| 配置项 | 当前行为 |
| --- | --- |
| `nodes` | 只能覆盖工作流已经声明的节点别名，不能在 YAML 中任意追加节点 |
| `tools` | 可以增加或替换工具别名 |
| 组件覆盖 | 替换整个 `{use, params}`，不深度合并工作流原有组件的 `params`；省略参数后使用函数默认值或报必需参数缺失 |
| workflow `params` | 与装饰器默认参数按键合并；无 `param_model` 时拒绝未知键，但类型／范围由构造函数检查 |
| `param_model` | 调用其 `model_validate(values)`；没有统一传 `strict=True`，需要严格类型时在模型中显式配置 |
| YAML | 拒绝重复键、非字符串键、别名引用；配置模型拒绝未知字段 |
| 相对路径 | `plugins`、记录根目录、重放文件相对于配置文件目录解析 |

覆盖顺序从低到高为：代码默认值 → YAML → 兼容环境变量（如 `LLM_BACKEND`）→ `RTLAGENT_` 嵌套环境变量 → 已支持的命令行参数。嵌套形式示例为 `RTLAGENT_SERVICES__MODEL__BASE_URL`；命令行只覆盖入口已声明的字段，不能修改任意配置键。配置结构会校验，但不能笼统声称所有 YAML／环境值都不做类型转换。

核对 `run/config` 的有效配置及覆盖记录，不只读 YAML。示例和实验应避免继承其他任务的环境覆盖；密钥通过环境注入，不能提交到配置文件。

## 6. 插件与新领域模块

`plugins` 是现有 Python 文件路径列表。入口先导入内置节点／工作流，再逐个导入插件；相同绝对路径在同进程中只加载一次，没有热重载和目录自动发现。插件是普通受信任 Python 代码，没有安全沙箱；加载失败也不保证回滚之前已完成的装饰器注册，修正后应在新进程验证。

简单扩展可以放在一个插件文件中；生产模块增长后应按职责拆分，在显式注册文件中汇集装饰器。通用运行时继续只处理状态、配置和执行服务；领域层保存自己的类型、语义与验证，不将新领域规则塞入 `graph.py`。

若新增服务对象，明确它由谁装配、何时关闭、如何获取预算、记录哪些证据。新增依赖写入 `requirements.txt`，在运行前准备，不在求解时下载或安装。外部工具路径从配置、PATH 或环境取得，不硬编码本机地址与私有目录。

## 7. 模型与检查器扩展必须额外验证

模型请求统一经 `ctx.llm.chat()`／`ctx.llm.ask()`，不得直接在节点新建 httpx 客户端绕过预算和记录。修改后端时同步 `ModelConfig` 的允许值、协议适配、模型声明与必要服务说明。保持所有请求与 `manifest.json` 的生成策略一致；正文、思考、工具调用、截断、空正文、传输错误和未知用量不能混为一类。

`ask()` 在客户端严格解析 JSON，校验数据结构，并执行调用方提供的语义检查。关闭服务端约束不会关闭这些检查。不要自动补猜字段、截取 JSON、忽略未知枚举或把解析失败转成默认成功。协议测试应覆盖真实服务要求的分词请求；假模型（mock）的字符近似计数不证明真实分词器（tokenizer）正确。

新增检查器能力时，先定义支持的类型、位宽、时钟／复位、采样时机与未知值处理规则，再扩展数据结构、语义校验、求值及测试台。独立构造期望结果时不得读取候选 RTL 或实测输出，诊断反馈仍须有公开题面依据。检查结果应绑定新候选及检查器版本；零比较、未触发性质、未知值、工具不可用都不是通过。验证必须包含正确例和错误反例，并保存实际比较证据。

解题角色在一次 `revise` 回复中给出完整新稿。新稿回到结构检查，lint 和 synth 均通过且有有效检查表时才执行行为采样。复核修正或撤回测试点后，若仍有活动点且当前稿的 lint 和 synth 均通过，框架用新表重新仿真。预算或工具不足时保留已有交付记录，注明哪版实际完成了哪些检查。[工作流与交付规则](guided-verify.md)

## 8. 完整最小示例：计数工作流

这个示例只演示注册、参数、工具调用、状态和记录，不调用模型／Vivado，不生成 RTL 候选。即使 `status=completed`，也仅表示演示流程完成。

在要验证的方案目录确认源码版本和未提交改动。下面的命令将当前目录中的入口、模块、配置和资源复制到临时目录，后续示例文件也写在这份副本中。

```bash
demo_dir="$(mktemp -d /tmp/rtlagent-extension.XXXXXX)"
cp -a agent config knowledge skill baseline.py manifest.json requirements.txt run.sh "$demo_dir/"
mkdir -p "$demo_dir/plugins" "$demo_dir/input"
```

将下面 Python 内容保存为 `$demo_dir/plugins/counter_demo.py`：

```python
from agent.kit import Ctx, State, node, tool, workflow


@tool("counter_increment")
def increment(ctx: Ctx, value: int, *, amount: int = 1) -> int:
    """对计数值增加指定整数，仅用于扩展机制演示。"""
    return value + amount


@node("counter_advance", reads=["count"], writes=["count"])
def advance(ctx: Ctx, state: State, *, offset: int = 0) -> State:
    value = ctx.call("increment", value=state["count"] + offset)
    return state.update(count=value)


@node("counter_finish", reads=[], writes=["status", "stop_reason"])
def finish(ctx: Ctx, state: State) -> State:
    return state.update(status="completed", stop_reason="counter_demo_completed")


@workflow(
    "counter_demo",
    params={"start": 0},
    tools={"increment": {"use": "counter_increment"}},
    nodes={
        "advance": {"use": "counter_advance"},
        "finish": {"use": "counter_finish"},
    },
    state={"count": 0, "status": "stopped", "stop_reason": ""},
)
def build(g, p):
    if type(p.start) is not int:
        raise ValueError("start must be an integer")
    return (
        g.with_state(count=p.start)
        .with_transitions(("advance", "finish"))
        .with_entrypoint("advance")
    )
```

将下面 YAML 保存为 `$demo_dir/config/counter_demo.yaml`：

```yaml
workflow: counter_demo
plugins:
  - ../plugins/counter_demo.py
params:
  start: 3
nodes:
  advance:
    use: counter_advance
    params:
      offset: 1
tools:
  increment:
    use: counter_increment
    params:
      amount: 2
services:
  model:
    backend: mock
runtime:
  deadline_s: 30
  reserve_s: 5
  max_steps: 10
  recording:
    level: full
```

使用已经安装本仓库依赖的 Python 环境，在同一 shell 运行：

```bash
printf '%s\n' '开发接口演示，不生成 RTL。' > "$demo_dir/input/prompt.txt"
(
  cd "$demo_dir"
  demo_rc=0
  AGENT_CONFIG=config/counter_demo.yaml LLM_BACKEND=mock ./run.sh input output || demo_rc=$?
  test "$demo_rc" -eq 1
)
```

此示例不生成答案，所以 `run.sh` 应返回 1；上面的代码显式检查这一返回值，适用于启用了 `set -e` 的 shell。
示例要求没有其他 `RTLAGENT_` 或 `AGENT_` 环境覆盖改变上述工作流和预算。返回 1 也可能表示执行错误，必须在同一 shell 继续运行以下代码，核对实际节点、计数结果和结束状态：

```bash
(
  cd "$demo_dir"
  python3 - <<'PY'
import json
from pathlib import Path

rows = [json.loads(line) for line in Path("output/trace.jsonl").read_text().splitlines()]
finished = [r for r in rows if r["tool"] == "node" and r["event"] == "finished"]
assert [r["name"] for r in finished] == ["advance", "finish"]
assert finished[-1]["state"]["count"] == 6  # start 3 + offset 1 + amount 2
assert any(r["tool"] == "increment" and r["event"] == "result" for r in rows)
assert not any(r["tool"] == "llm" for r in rows)
end = next(r for r in reversed(rows) if r["tool"] == "run" and r["event"] == "end")
assert end["status"] == "completed"
assert end["stop_reason"] == "counter_demo_completed"
assert Path("output/solution.v").read_text() == ""
print("扩展示例通过；没有生成或验证 RTL 答案。")
PY
)
```

再把 YAML 的 `offset` 改成字符串，或新增未知参数；应在装配阶段报错，而不是静默使用默认值。把 `start` 改为布尔值也应被显式校验拒绝。上述负例必须使用不同输出目录，保留原通过记录。示例中的两步成功不证明新检查器、真实模型或比赛环境通过。

## 9. 验证与交付流程

1. **划定修改边界。** 写清问题、输入／输出、哪些层会变化、兼容范围以及验收证据。新增能力先打通从输入到结果的最小流程，不把框架改造和策略试验混成一次提交。
2. **检查装配。** 验证合法配置、未知别名、未知参数、错误类型、初始状态和必要终止分支。配置替换应检查最终展开值，而非仅验证 YAML 能解析。
3. **执行定向用例。** 节点检查状态更新，工具检查失败分类与预算，图检查正常／失败／有限重试／无下一步／最大步数。新增取消或进程逻辑需检查子进程组清理。
4. **逐步验证实际运行。** 先验证纯函数和自编测试数据，再使用 mock 或严格离线重放，最后按需要验证小样本真实服务与工具。重放必须按顺序精确匹配请求，并用完提供的响应记录；不能把任意历史日志当成可直接重放的请求集。
5. **核对产物与身份。** 记录实际导入源码路径、代码哈希、配置、模型／服务版本、候选及检查器身份。不能用前一版候选、旧检查结果或其他工作树结果证明当前实现。
6. **审查提交。** 检查差异、文件清单和不依赖开发区的运行入口；必要的打包检查不代替真实环境验收。推送后再查询远端提交哈希，确认与本地提交一致。

会创建临时模块、修改配置或注入测试组件的验证在隔离副本中执行，检查前后源文件差异。运行日志放本地开发区或临时目录，不提交方案；不依赖已移除的 `dev/tools/`、`dev/tests/`。已有工作区的主办方判定只消费已保存答案，判定反馈不得回到求解过程。

在方案仓库根目录执行 `LLM_BACKEND=mock ./run.sh <公开题目目录> <独立输出目录>` 可检查默认入口。假模型会选择 `structural`、不选技能，生成占位 RTL，收到解题决策请求时回复 `submit`。要测试选用 `table`、改稿或逐点复核，需要为相应阶段提供自编响应。

## 10. 文件、文档和提交约定

- 不修改 `baseline.py`、`run_baseline.sh`。方案仓库的 `README.md`、`REPORT.md` 和 `manifest.json` 按当前要求维护；工作区根 README 是主办方只读文档。新增提交文件用英文小写字母、数字、下划线或连字符命名，赛事固定文件名沿用原要求。
- 不提交 API key、Cookie、令牌、认证状态、模型权重和运行日志。题库、参考答案、官方测试台和判定反馈不进入方案、提示或 skill。文档示例也不能携带它们。
- `docs/` 保存可随仓库阅读的设计与开发接口，正文用中文，术语首次出现解释含义。本机路径、连接状态、原始实验证据和一次性进度仍放仓库外开发区。当前行为与未来计划分开写。
- 代码、配置、模型声明或日志契约变化时同步相应指南；文档示例应在所述版本的隔离副本运行，链接指向仓库内实际文件，避免依赖维护者机器布局。
- 提交信息只有一行英文 `<类型>(<范围>): <说明>`，动词原形开头，无正文与 Co-Authored-By。按独立问题拆分小提交，不顺带提交用户改动。
- 允许按任务要求使用独立分支或直接更新 main；不要未经要求合并、强制推送或删除历史分支。推送文档也要核对远端，不能只凭命令已发出声明完成。
