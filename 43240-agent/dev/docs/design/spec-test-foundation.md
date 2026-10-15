# 可选规格自测基础

日期：2026-10-15。状态：基础接口已实现，已接入显式选择的实验工作流；无正式性能增益结论。

## 这一批做什么、不做什么

提供公共规格计划校验、受控刺激调度、Vivado 自建测试台仿真和候选保护函数。
基础模块不修改 `single_generate`、`repair_loop`、`evidence_repair`、E1/E2 的调度，
不改变这些入口的首稿提示、模型权重、默认采样或默认调用预算。不包含逐题难度自评。
独立的[可选实验工作流](experimental-workflows.md)负责显式启用自测，默认入口不变。
组合/时序分类仅选择计划提示，不是难度预测，也不自动增加思考预算。

## 支持范围

- 无符号 input/output 标量和 `[width-1:0]` 一维向量，位宽 1～4096；拒绝符号端口、数组、
  参数表达式、非 ANSI 等无法完整验证的声明。只有散文端口表时还需对实际候选做同样的端口限制检查。
- 组合逻辑使用 steps；唯一明确的完整二值真值表可直接枚举，限 1～5 个一位输入、1～16 个一位输出，
  不能有缺行、重复行、冲突、非二值、第二张表或例外说明。拒绝快车道不等于拒绝题目本身。
- 时序逻辑使用 cycles，或严格校验的旧 steps 格式。限单时钟、单一输出寄存器组、明确有效沿、
  复位极性、同步/异步类型与公开复位字面值；多输出时序、FSM、混合组合输出、锁存器和含糊规格回退。
- 周期调度器控制时钟/复位：初始化、有效复位沿、非有效相准备数据、有效沿、稳定后采样。
  模型只提供数据周期，不自行编写半周期。计划必须包含复位后的功能有效沿检查。

这些是保守词法与协议检查，不是完整 SystemVerilog 解析器或自然语言证明器。
引用原文只能证明有来源，不能证明模型从原文算出的期望值正确。
时序识别同时接受 posedge/negedge、rising/falling 和 positive/negative edge；
即使输入名不含 clk/clock，也不能把这些规格作为组合逻辑计划执行。缺少明确复位时仍回退。
复位证据可以来自非相邻段落；周期展开保留原始证据片段，首次与末次复位检查使用相同的逐段校验。

## 接口和接入方式

显式导入 `agent.nodes.behavior` 后，注册两个 Node，但不会自动运行：

- `TestPlanNode.run(ctx, task) -> PlanResult`：只接受当前公共任务。真值表可零模型调用；其他计划
  使用独立公开消息，temperature=0、top_p=1、最多一次请求。模型调用仍经既有服务的 token、上下文和时间限额。
  截断、无效计划或模型服务错误返回不可用原因，不重试；整题预算耗尽仍由调用工作流处理。
- `BehaviorNode.run(ctx, BehaviorInput(candidate, plan)) -> CheckResult`：通过 `ctx.tools.behavior()`
  使用受监督工具执行器。JSON 数据由程序生成自己的测试台，不执行模型提供的 HDL 测试代码、脚本或表达式。
- `parse_plan()`、`literal_truth_table_plan()`、`render_driver()`、`analyze_trace()`：分别负责计划校验、
  字面表枚举、受控 TB 生成和观察解释。端口数据之外只读公共规格，不读取官方 TB、参考答案或 judge。
- `choose_spec_candidate(state, *, plan_hash) -> SelectionDecision`：纯选择函数，位于
  `agent/workflows/spec_selection.py`。调用者负责通过 `ctx.apply_selection()` 应用，不恢复旧全局 policies 目录。

正式求解仍只经 `run.sh`、Supervisor 和 Python Workflow；这里没有第二套 Agent 求解循环。
“首稿→计划→自测→修复→再自测”由显式选择的 `spec_test_repair` 和 `behavior_divergence` 编排，
包括编译修复后补功能测试、早停和调用次数上限；仅使用基础接口不会自动运行这些流程。

## 结果和候选保护

`CheckResult(kind='behavior')` 沿用现有不可变证据契约，结构化 details 区分：

- 普通模型期望值：`hypothesis_assertions`、`hypothesis_mismatches`，不作为单独推翻可编译候选的依据。
  X/Z 单独记录为不确定观察，不计为失配；计数字段定义见[运行记录格式](trace-schema.md)。
- 受支持的公开真值表、明确复位字面值与已声明寄存器的观察保持关系：`property_checks`。
  这些检查仍依赖公开规格解析成立，不是完整功能正确性证明。
- `property_inconclusive`、`reset_kind_probes`：X/Z 或前态未知不得当作通过或确定失败；
  复位探针比较实际观察前态，不取模型预测末态。前态等于复位值时明确记为没有区分度。
- `plan_hash`、`oracle_protocol=2`、`valid_observation`、`official_verification=false`、首个失配及有界完整输入历史。
  人类摘要有长度上限；必要输入历史保留在结构化 details 中。

模型假设或公开属性存在不确定观察、且没有确定失配时，工具返回 `unavailable`；
不确定观察与确定失配并存时返回 `failed`，首个失配仅引用确定的采样，结构化结果同时保留不确定计数。

若旧候选已 lint 通过，替换必须有同一计划、相同受支持属性 ID 集合和完整观察，保住全部旧通过属性，
严格减少失败属性，不损失已有接口/lint/综合通过证据、端口声明语义或复位探针区分覆盖。
最新工具检查未知不能被更早的通过隐藏。普通模型分数更好、工具等级更高都不能绕过这层保护。

工具不可用、超时、TB 编译/展开失败、观察缺失或格式错误不是确定的 DUT 功能错误。
只有 DUT 编译阶段的既有明确源码诊断沿用代码归因。自测失配归为 behavior，不自动冒充编译代码错误。

## 预算、缓存和验证边界

工具结果统一记录开始、结束和日志引用。缓存键包含任务、源码、计划哈希和仿真工具身份，
包含 xsim 可执行文件身份；工具身份未知则不复用。复用显式记录 `executed=false` 和原检查 ID。
每一仿真阶段前检查整步剩余时间，耗尽不再启动后续阶段；正式入口继续接受 Supervisor 的硬截止监督。

组件回归和人工构造电路的真实 Vivado 用例验证基础协议，不能替代固定模型、共用首稿的正式题集实验。
不承诺“baseline 对的题绝不改坏”，不将自测通过等同官方 L2/L3，也不宣称性能增益。
