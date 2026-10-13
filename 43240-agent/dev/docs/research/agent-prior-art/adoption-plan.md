# 对当前 Agent 的落地路线

状态：早期研究建议，保留当时的实验设想。后续方案 A 和生成参数对照已完成，最新顺序见
[2026-10-13 实验安排](../../notes/2026-10-13-after-generation-experiment-order.md)。
文中 Policy 已在现有实现中下放到 Workflow；“总 token 相同”是实验设想，累计 token 硬限尚未实现，
也不是比赛要求。下文不作为当前阶段必须先建设全部基础设施的清单。

当前框架已经有 Workflow、Node、Candidate、SelectionPolicy、FailurePolicy、CheckCache、Budget、
Supervisor 和统一实验入口。下一步不应重写基础设施，而应把论文想法实现为可替换的小组件，逐项消融。

## 一、优先做的四个实验

### E1：工具反馈是否真的有效

来源：AutoChip、RTLFixer、Agentless。

固定同一模型、温度、总 token 和总时间，比较：

1. `single_generate`；
2. 失败后只给错误类别和源码位置；
3. 给结构化错误摘要与一条检索到的修复指南；
4. 给完整原始日志；
5. 当前 `repair_loop`。

主要指标：最终得分、从 L0 到 L1/L2/L3 的迁移、被修坏题数、模型调用数、输入/输出 token、墙钟时间。
如果完整日志不优于结构化摘要，就不应继续增加上下文。

实现建议：新增独立的 `FeedbackBuilder` 或 Node，由 Workflow 选择；不要把反馈格式写死进模型服务。

### E2：两候选是否优于三轮重写

来源：Tree of Thoughts、MAGE、Agentless。

在同一总预算下比较：

- 一份候选 + 最多两次修复；
- 两份独立候选 + 确定性选择；
- 一份候选 + 一次模型审查 + 一次修复。

先只允许宽度为 2 的搜索，不实现通用树搜索。候选使用现有检查证据排序；同等证据保留早期候选，
避免新候选无条件覆盖。记录每个分支消耗的时间和 token，比较“多样性收益”与“修复收益”。

### E3：面向 RTL 的故障定位

来源：VerilogCoder、AutoCodeRover、SWE-agent。

按投入从低到高逐步做：

1. 从 Vivado/Icarus 日志提取错误码、文件、行列和涉及标识符；
2. 将错误映射到目标 module、always 块和相关端口；
3. 开发评测中有波形时，提取首个失败周期和少量相关信号；
4. 只有证据足够时，让模型局部修复；否则完整重写或停止。

正式 Agent 不得读取官方隐藏 testbench、参考答案或 judge 结果。开发期产生的错误模式可以整理成通用
修复指南，但不能把具体题目的答案或波形真值写入技能。

### E4：上下文与墙钟效率

来源：LLMLingua、RouteLLM、FrugalGPT、LLMCompiler。

- 对工具日志按字段和 token 预算压缩，权威接口与当前完整候选不压缩。
- 根据题型、首次生成完整性、接口结果和错误类别选择“停止、短修复、完整重写”，先做动作路由，
  最终部署允许时再做多模型路由。
- 并行化不同候选的轻量检查；Vivado 综合默认串行，除非实测资源允许。
- 每个动作声明最低启动预算和后续保留时间，不能让一次综合吃掉全部预算。

## 二、论文思想到当前模块的映射

| 外部思想 | 当前落点 | 最小改动 | 不建议做法 |
| --- | --- | --- | --- |
| AutoChip 工具反馈 | `repair_loop`、FailurePolicy | 可替换 FeedbackBuilder + 消融配置 | 默认把完整日志追加到所有轮次 |
| RTLFixer RAG | diagnostics、prompts/skills | 按稳定错误码检索短指南 | 用临时路径或整段日志做检索键 |
| VerilogCoder 波形定位 | 新的开发期 Node | 首错周期、相关信号、源码位置 | 把隐藏 judge/testbench 暴露给 Agent |
| MAGE 多角色 | Python Workflow | 先实现 planner + implementer 两阶段 | 无预算地增加多个聊天 Agent |
| Agentless 固定流程 | 新 Workflow | locate → generate/repair → validate | 让模型自由决定全部下一步 |
| SWE-agent 工具接口 | Node/ToolResult | 小动作、短输出、明确错误类别 | 暴露任意 shell 和无限输出 |
| Reflexion 语言记忆 | 开发期失败知识库 | 通用错误模式与修复结果 | 跨正式题保存题目答案 |
| Tree of Thoughts | Candidate/SelectionPolicy | 两候选、有界扩展、证据剪枝 | 大分支搜索耗尽墙钟预算 |
| DSPy Prompt 优化 | `dev/tools/run.py` 离线实验 | 在公开开发集优化后冻结 | 正式求解读取参考答案优化 |
| LLMLingua 压缩 | FeedbackBuilder | 压缩历史和重复日志 | 压缩端口契约或 Verilog 关键行 |
| RouteLLM/FrugalGPT | Workflow 路由 | 先做动作路由，再评估模型路由 | 不记成本地混用模型结果 |
| LLMCompiler 并行 | Runner/ProcessExecutor | 仅并行无依赖、资源允许的检查 | 并发多个 Vivado 抢显存/内存 |

## 三、建议的实施顺序

```text
冻结 single_generate 与 repair_loop 基线
              ↓
E1：反馈格式消融（最小、最容易解释）
              ↓
E2：两候选与修复路线比较
              ↓
E3：结构化定位；先编译错误，后开发期波形
              ↓
E4：上下文压缩、动作路由与有限并行
              ↓
只有证据显示固定流程到达上限，才试多 Agent 或更宽搜索
```

每一步使用独立 Workflow/Node 和 YAML 配置，不修改已有结果；至少报告以下内容：

- 同一任务集、模型、采样参数和总预算；
- `S_a`、L0/L1/L2/L3、相对 `single_generate` 的增益；
- 修好题数、修坏题数、未变化题数；
- 每题模型调用数、token、求解墙钟 p50/p90；
- 超时、环境失败和无有效候选数量；
- Git commit、配置、模型版本与原始运行目录。

## 四、三条停止规则

1. 连续两次得到相同代码哈希或相同稳定错误码且证据没有改善时停止当前修复分支。
2. 剩余预算不足以完成一次模型调用、必要检查和输出预留时，不启动新候选。
3. 工具报告环境错误、超时或未知失败时，不把它包装成 RTL 缺陷让模型盲修。

这三条分别对应论文中常见的重复反思、搜索爆炸和错误反馈污染问题，也能直接复用现有缓存、预算与
FailurePolicy。

## 五、第一轮建议产物

第一轮先不引入第三方运行时依赖，提交以下内容即可：

- `FeedbackBuilder` 契约与三种实现：错误码、结构化摘要、完整日志；
- 一组只用假模型/假工具的路由测试；
- `feedback-ablation.yaml` 实验配置；
- quick 任务集上的 Agent/baseline 对照记录；
- 结论只回答“哪种反馈在固定预算下更好”，不同时引入多 Agent、RAG、波形和模型路由。
