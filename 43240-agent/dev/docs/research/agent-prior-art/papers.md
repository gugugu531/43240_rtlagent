# 开源论文清单

引用量主要是 2026-10-06 的 OpenAlex `cited_by_count` 快照；第 3 天新增材料于 2026-10-09 补查，
第 5 天三篇论文于 2026-10-11 按正式发表记录更新。表中“首发/发表”同时写预印本首次公开年份和
正式发表年份，便于兼顾新旧；“代码”链接到公开仓库。引用量不能跨 Google Scholar、Semantic Scholar
和 OpenAlex 直接比较。

## 一、RTL、Verilog 与 EDA

| 优先级 | 论文 | 首发/发表 | 引用 | 代码 Star | 最值得借鉴 |
| --- | --- | --- | ---: | ---: | --- |
| A | [RTLLM](https://arxiv.org/abs/2308.05345) | 2023 / ASP-DAC 2024 | [159](https://openalex.org/W4393145520) | [236](https://github.com/hkust-zhiyao/RTLLM) | 语法、功能、综合质量分层；自然语言规格与测试台组织 |
| A | [ChatEDA](https://arxiv.org/abs/2308.10204) | 2023 / TCAD 2024 | [152](https://openalex.org/W4393305455) | [62](https://github.com/wuhy68/ChatEDA) | 把 EDA 流程封装为稳定 API，规划后生成可执行脚本 |
| A | [VerilogCoder](https://arxiv.org/abs/2408.08927) | 2024 / AAAI 2025 | [46](https://openalex.org/W4409369309) | [185](https://github.com/NVlabs/VerilogCoder) | 图式规划、AST 波形追踪、功能错误定位 |
| A | [OriGen](https://arxiv.org/abs/2407.16237) | 2024 / ICCAD 2024 | [31](https://openalex.org/W4409285487) | [35](https://github.com/pku-liang/OriGen) | 编译器反馈自反思、开放 RTL 数据增强与开源模型 |
| A | [Revisiting VerilogEval](https://arxiv.org/abs/2408.11053) | 2024 / 2025 | [27](https://openalex.org/W4407749900) | [478](https://github.com/NVlabs/verilog-eval) | spec-to-RTL、错误分类、不同模型下的 Prompt 敏感性 |
| A | [AutoChip](https://arxiv.org/abs/2311.04887) | 2023 | [20](https://openalex.org/W4388555899) | [64](https://github.com/shailja-thakur/AutoChip) | 编译/仿真反馈循环、跨轮上下文和成本—效果消融 |
| A | [MAGE](https://arxiv.org/abs/2412.07822) | 2024 / DAC 2025 | [20](https://openalex.org/W4414197266) | [140](https://github.com/stable-lab/MAGE) | 规格、规划、实现、验证角色拆分与多候选协作 |
| A | [VerilogEval](https://arxiv.org/abs/2309.07544) | ICCAD 2023 | [16](https://openalex.org/W4386794762) | [478](https://github.com/NVlabs/verilog-eval) | 自动功能判定、pass@k 和固定 benchmark 契约 |
| B | [RTL-Repo](https://arxiv.org/abs/2405.17378) | 2024 / LAD 2024 | [16](https://openalex.org/W4403023459) | [35](https://github.com/AUCOHL/RTL-Repo) | 多文件 RTL 仓库补全数据与上下文边界 |
| A | [RTLFixer](https://arxiv.org/abs/2311.16543) | 2023 | [10](https://openalex.org/W4389156677) | [57](https://github.com/NVlabs/RTLFixer) | RAG（检索增强生成）+ ReAct + 编译/仿真反馈 |
| B | [TuRTLe](https://arxiv.org/abs/2504.01986) | MLCAD 2025 | [2](https://openalex.org/W4415003693) | [49](https://github.com/HPAI-BSC/TuRTLe) | 统一 syntax/function/synthesis/PPA 评测和容器化工具链 |

### 1. AutoChip

AutoChip 与当前 `repair_loop` 最接近：先生成 RTL，再把编译或仿真错误带回下一轮。原始工作报告引入
Icarus Verilog 反馈后准确率提高；[后续更系统的实验](https://arxiv.org/abs/2411.11856)也指出，
工具反馈并非对每个模型都稳定有益，
较弱模型可能不会正确利用日志。因此应复现它的**反馈消融**，而不是默认“多修几轮一定更好”。

建议借鉴：保存每轮完整输入、只传结构化错误摘要、分别测 compile feedback、simulation feedback、
完整历史和仅上一轮反馈。

### 2. RTLFixer

RTLFixer先区分错误，再从人工修复指南检索相关片段，最后让模型在工具反馈上行动。它针对语法错误的
结论很强，但这不等于能修复状态机、时序边界或复位语义。对当前工程最有价值的是把
`diagnostic.code + source_location + guidance_id` 作为稳定反馈，而不是把 Vivado 尾部日志直接塞回模型。

### 3. VerilogCoder

VerilogCoder将任务关系建成规划图，并用 AST（抽象语法树）驱动的波形追踪定位功能差异。论文的高成功率
建立在可访问测试台和波形信息上；比赛正式求解时未必有同等 oracle（判定真值来源）。可迁移的是
“从失败周期反向缩小到相关信号和语句”的定位方法，而不是把隐藏判定反馈当成可用输入。

### 4. MAGE

MAGE把复杂任务分给不同角色，适合研究“先规划、再实现、再验证”。它提醒我们不要把多 Agent 简化成
多次独立聊天：角色之间应交换结构化规格、计划、候选和证据。风险是模型调用数和上下文快速增长，
必须先在固定总预算下与单 Agent 双候选做公平比较。

### 5. ChatEDA

ChatEDA覆盖 RTL 到 GDSII 的 EDA 流程自动化，重点不是直接提高 Verilog 功能正确率。它最值得学习的是
为 EDA 工具建立窄而稳定的 Python API、让模型先生成计划再调用确定性执行器。这与当前 Node、
`ToolResult` 和进程监督结构相容。

### 6. Benchmark 与训练工作

VerilogEval v2、RTLLM 和 TuRTLe 应作为开发评测参考：前两者提供成熟任务和测试台，TuRTLe把多套数据、
容器化 EDA 工具和 PPA 指标统一起来。OriGen更适合研究开放模型、数据增强和编译反馈微调，短期可先借鉴
其错误数据构造方法，不必立即训练新模型。

## 二、Coding Agent 与通用 Agent

| 优先级 | 论文 | 年份 | 引用 | 代码 Star | 可迁移点 |
| --- | --- | ---: | ---: | ---: | --- |
| A | [Reflexion](https://arxiv.org/abs/2303.11366) | 2023 | [586](https://openalex.org/W7133222210) | [3,295](https://github.com/noahshinn/reflexion) | 把外部反馈转成短期语言记忆，不更新模型权重 |
| A | [Tree of Thoughts](https://arxiv.org/abs/2305.10601) | 2023 | [567](https://openalex.org/W4377130677) | [6,076](https://github.com/princeton-nlp/tree-of-thought-llm) | 有界分支、评价、回溯，而非只修最新候选 |
| A | [RepoCoder](https://arxiv.org/abs/2303.12570) | 2023 | [156](https://openalex.org/W4389519225) | [677](https://github.com/microsoft/CodeT/tree/main/RepoCoder) | 用首轮生成改进第二轮仓库检索；部分函数级执行评测未公开 |
| A | [Self-Refine](https://arxiv.org/abs/2303.17651) | 2023 | [372](https://openalex.org/W7133236450) | [822](https://github.com/madaan/self-refine) | 同一模型生成—批评—改写；必须有可靠停止条件 |
| A | [AutoCodeRover](https://doi.org/10.1145/3650212.3680384) | 2024 / ISSTA 2024 | [190](https://openalex.org/W4402442868) | [3,102](https://github.com/AutoCodeRoverSG/auto-code-rover) | AST/测试驱动定位；源码公开但当前许可证非严格开源 |
| A | [LLMLingua](https://arxiv.org/abs/2310.05736) | 2023 | [142](https://openalex.org/W4389519226) | [6,729](https://github.com/microsoft/LLMLingua) | Prompt 预算控制和长日志压缩 |
| A | [DSPy](https://arxiv.org/abs/2310.03714) | 2023 | [60](https://openalex.org/W4387430850) | [38,510](https://github.com/stanfordnlp/dspy) | 用开发指标自动优化 Prompt/示例，而非手工猜模板 |
| A | [FrugalGPT](https://arxiv.org/abs/2305.05176) | 2023 | [51](https://openalex.org/W4376122773) | [289](https://github.com/stanford-futuredata/FrugalGPT) | 模型级联和预算感知选择 |
| A | [SWE-agent](https://papers.neurips.cc/paper_files/paper/2024/hash/5a7c947568c1b1328ccc5230172e1e7c-Abstract-Conference.html) | 2024 / NeurIPS 2024 | [41](https://openalex.org/W4399114781) | [20,518](https://github.com/SWE-agent/SWE-agent) | 为模型设计专用、受约束的 Agent-Computer Interface |
| B | [Mixture-of-Agents](https://arxiv.org/abs/2406.04692) | 2024 | [25](https://openalex.org/W4399511904) | [2,980](https://github.com/togethercomputer/MoA) | 多模型提议与聚合；成本较高，适合离线对照 |
| A | [Agentless](https://doi.org/10.1145/3715754) | 2024 / FSE 2025 | [107](https://openalex.org/W4411449940) | [2,124](https://github.com/OpenAutoCoder/Agentless) | 固定定位—修复—验证流程，低成本、易消融 |
| B | [OpenHands](https://arxiv.org/abs/2407.16741) | 2024 | [15](https://openalex.org/W4403885061) | [90,071](https://github.com/All-Hands-AI/OpenHands) | 沙箱、事件流、Agent 平台；框架很重，不宜直接移植 |
| A | [RouteLLM](https://arxiv.org/abs/2406.18665) | 2024 | [8](https://openalex.org/W4400141368) | [5,570](https://github.com/lm-sys/RouteLLM) | 按样本难度在强弱模型间路由 |
| B | [LLMCompiler](https://arxiv.org/abs/2312.04511) | 2023 | [3](https://openalex.org/W4389500120) | [1,891](https://github.com/SqueezeAILab/LLMCompiler) | 把无依赖工具调用并行调度，降低墙钟时间 |
| A | [ReAct](https://arxiv.org/abs/2210.03629) | 2022 | 本次未取到可靠值 | [4,201](https://github.com/ysymyth/ReAct) | 推理、行动、观察交替；必须限制动作空间和轮数 |

### 7. Reflexion、Self-Refine 与 ReAct

三者都支持迭代，但作用不同：ReAct定义“思考—调用工具—观察”的交替接口；Self-Refine让模型批评并
改写自身输出；Reflexion把失败总结保存为后续尝试可用的语言记忆。当前工程不应把三者都实现成同一种
“把上一段日志拼进 Prompt”。工具事实、模型批评和跨题经验应分别记录，并分别做消融。

### 8. Tree of Thoughts 与多候选

Tree of Thoughts说明搜索需要候选分支、评价和回溯。对 RTL 更稳妥的最小版本不是大规模树搜索，而是：
固定生成两份候选，独立检查，保留强证据候选，只在错误类别不同或证据改善时继续扩展。这样能复用现有
Candidate、SelectionPolicy、CheckCache 和 Budget。

### 9. AutoCodeRover 与 SWE-agent

AutoCodeRover强调先用程序结构和测试定位，再把小范围上下文交给模型；SWE-agent强调模型使用的工具接口
要专门设计。对应到 RTL，应优先提供模块/端口/信号/失败周期/源码位置级操作，而不是让模型反复接收整个
源码和完整 Vivado 日志。

AutoCodeRover 当前上游代码采用 Sonar Source-Available License v1.0，不是严格意义的开源许可证。可以把
论文和公开源码用于结构研究，但不能默认复制、修改或再分发到参赛方案。

### 10. SWE-agent

建议研究其 Agent-Computer Interface（面向 Agent 的计算机接口），重点看命令输出裁剪、动作约束、
文件浏览和测试反馈如何设计。当前工程已有 Node 和结构化结果，适合借鉴接口思想，不需要引入整个框架。

### 11. Agentless

Agentless的关键提醒是：复杂自治并不自动带来更高成绩。对当前项目，应先把固定流程的每个增量单独测清：
定位是否改善、修复是否改善、验证是否能避免退化。只有固定流程出现明确上限后，再增加自由规划或多 Agent。

### 12. DSPy

DSPy适合离线开发：把 Prompt、示例选择和模块组合当作可优化程序，用公开训练/开发题的官方指标搜索，
最后冻结结果进入提交。不能在正式求解中读取参考答案，也不能让开发判定信息进入 Agent 上下文。

### 13. LLMLingua

LLMLingua表明长 Prompt 可以按预算压缩。这里不应直接压缩 Verilog 源码或权威接口；优先压缩历史对话、
重复工具日志和说明文字，并以错误码、源码位置、失败周期等结构化字段作为不可删除锚点。

### 14. 效率方法

RouteLLM和 FrugalGPT研究强弱模型路由与级联；LLMCompiler研究独立工具并行。若最终规则允许多个本地模型，
可以先用小模型解决简单题或生成计划，仅在低置信度/失败时升级。若只能部署一个模型，也可把同一思想用于
“单次生成—短修复—完整重写”的动作路由。工具并行只适用于无依赖检查，并要避免并发 Vivado 抢占资源。

## 三、没有进入核心表的项目

- BetterV 论文很有价值，但本轮没有确认到与论文完整对应、许可证清晰的官方可运行仓库，因此不满足
  “论文必须开源便于复现”的严格条件。
- [RTLRepoCoder](https://arxiv.org/abs/2504.08862)（2025，OpenAlex 截至 2026-10-09 引用 1）适合选读
  仓库级 RTL 的微调与 RAG，但没有找到作者公开代码；曾引用的 `AUCOHL/RTLRepoCoder` 返回 404，故不进入
  “论文与实现均开源”的核心表，也不把 RepoCoder 或 RTL-Repo 冒充它的官方实现。
- 2026 年出现了若干 RTL Agent 项目和论文，时间很新但引用和独立复现尚少；其中活跃工程放在
  [项目观察表](projects.md#前沿和观察项目)，不与成熟论文混排。
- 只有 README 自报提升、没有论文或可核查实验产物的项目不作为结论依据，可用来发现工程点子。
