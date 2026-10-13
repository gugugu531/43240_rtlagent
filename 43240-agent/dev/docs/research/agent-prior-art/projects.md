# 开源工程清单

2026-10-13 新增：[AMD Ross 本地研究入口](ross-ai-study.md)。用户 fork 已浅克隆到
`/home/cloudia/FPGACHINA/ross-ai-assistant`；固定提交与许可证见该文，未安装插件或接入实验。

Star、最近 push、归档状态和许可证主要是 2026-10-06 的 GitHub API 快照；第 3 天新增工程于
2026-10-09 补查，第 5 天工程于 2026-10-11 更新。核心表保存上游链接；一周教程
第 1～5 天另有被 Git 忽略的本地只读浅克隆或只读链接，固定版本见各日材料清单。“优先读”表示与当前工程的接口
最接近，不表示仓库质量的最终排名。

## RTL、Verilog 与 EDA 工程

| 优先级 | 仓库 | Star | 最近 push | 许可证 | 建议先看 | 备注 |
| --- | --- | ---: | --- | --- | --- | --- |
| A | [NVlabs/verilog-eval](https://github.com/NVlabs/verilog-eval) | 478 | 2025-07-14 | 需人工核对 | v2 spec-to-RTL 数据、分类脚本、评测入口 | 最成熟的直接 benchmark 之一 |
| A | [hkust-zhiyao/RTLLM](https://github.com/hkust-zhiyao/RTLLM) | 236 | 2026-08-15 | MIT | 任务描述、testbench、syntax/function/PPA 层次 | v2.1 仍在更新 |
| A | [NVlabs/VerilogCoder](https://github.com/NVlabs/VerilogCoder) | 185 | 2025-03-10 | Apache-2.0 | graph planner、AST waveform tracer | 复现时核对测试台可见性 |
| A | [stable-lab/MAGE](https://github.com/stable-lab/MAGE) | 140 | 2025-04-11 | MIT | 多角色消息、候选验证和 benchmark 配置 | 控制模型调用成本 |
| A | [shailja-thakur/AutoChip](https://github.com/shailja-thakur/AutoChip) | 64 | 2025-03-10 | 未检测到 | feedback loop、实验脚本、消融参数 | API 显示仓库约 560 MiB，不建议直接完整克隆 |
| A | [wuhy68/ChatEDA](https://github.com/wuhy68/ChatEDA) | 62 | 2025-05-21 | Apache-2.0 | API 文档、训练样例、ChatEDA-Bench | 更偏 EDA 流程编排 |
| A | [NVlabs/RTLFixer](https://github.com/NVlabs/RTLFixer) | 57 | 2024-05-23 | MIT | feedback/rag/nofeedback 三种模式 | 代码小，适合先做只读复现 |
| B | [AUCOHL/RTL-Repo](https://github.com/AUCOHL/RTL-Repo) | 35 | 2024-06-05 | Apache-2.0 | 仓库级 RTL 数据字段、生成与文本评分脚本 | 数据另存 Hugging Face；文本分数不等于功能正确 |
| B | [HPAI-BSC/TuRTLe](https://github.com/HPAI-BSC/TuRTLe) | 49 | 2026-07-22 | Apache-2.0 | 容器化评测、多 benchmark 适配、PPA | 新但活跃，适合统一评测参考 |
| B | [pku-liang/OriGen](https://github.com/pku-liang/OriGen) | 35 | 2024-10-20 | 未检测到 | 数据增强、自反思评测、模型入口 | 复用代码前先核对许可证 |
| B | [NVlabs/CraftRTL](https://github.com/NVlabs/CraftRTL) | 21 | 2024-10-17 | 需人工核对 | 正确构造的中间表示、定向代码修复数据 | 更偏数据生成与训练 |
| C | [masc-ucsc/hdlagent](https://github.com/masc-ucsc/hdlagent) | 24 | 2025-06-07 | Apache-2.0 | Verilog/Chisel/PyRTL/DSLX 统一 Agent 接口 | 2025-06-08 已归档，只读学习 |

## Coding Agent 与通用效率工程

| 优先级 | 仓库 | Star | 最近 push | 许可证 | 借鉴重点 |
| --- | --- | ---: | --- | --- | --- |
| A | [All-Hands-AI/OpenHands](https://github.com/All-Hands-AI/OpenHands) | 90,071 | 2026-10-06 | MIT | 沙箱、事件流、评测适配；只读架构，不直接引入重框架 |
| A | [Aider-AI/aider](https://github.com/Aider-AI/aider) | 49,387 | 2026-05-22 | Apache-2.0 | 代码编辑协议、仓库上下文选择、提交与测试循环 |
| A | [stanfordnlp/dspy](https://github.com/stanfordnlp/dspy) | 38,510 | 2026-10-05 | MIT | 用指标编译/优化 Prompt 和 Pipeline |
| A | [SWE-agent/SWE-agent](https://github.com/SWE-agent/SWE-agent) | 20,518 | 2026-10-06 | MIT | Agent-Computer Interface、命令约束、输出整理 |
| A | [microsoft/LLMLingua](https://github.com/microsoft/LLMLingua) | 6,729 | 2026-09-10 | MIT | 长上下文和日志压缩、token 预算控制 |
| A | [princeton-nlp/tree-of-thought-llm](https://github.com/princeton-nlp/tree-of-thought-llm) | 6,076 | 2025-01-16 | MIT | 有界候选搜索、评价和回溯 |
| A | [lm-sys/RouteLLM](https://github.com/lm-sys/RouteLLM) | 5,570 | 2024-08-10 | Apache-2.0 | 强弱模型路由和离线训练数据 |
| A | [ysymyth/ReAct](https://github.com/ysymyth/ReAct) | 4,201 | 2024-02-06 | MIT | 推理—行动—观察 Prompt 与轨迹 |
| A | [noahshinn/reflexion](https://github.com/noahshinn/reflexion) | 3,295 | 2025-01-14 | MIT | 语言反思、外部评价、短期记忆 |
| A | [microsoft/CodeT/RepoCoder](https://github.com/microsoft/CodeT/tree/main/RepoCoder) | 677 | 2024-11-01 | MIT | 仓库切片、相似检索、首轮生成驱动第二轮检索 |
| 只读 | [AutoCodeRoverSG/auto-code-rover](https://github.com/AutoCodeRoverSG/auto-code-rover) | 3,102 | 2025-04-24 | Sonar Source-Available v1.0（非严格开源） | AST 搜索、故障定位；不复制代码进入方案 |
| B | [togethercomputer/MoA](https://github.com/togethercomputer/MoA) | 2,980 | 2025-01-07 | Apache-2.0 | 多模型提议—聚合；适合做成本上界对照 |
| A | [OpenAutoCoder/Agentless](https://github.com/OpenAutoCoder/Agentless) | 2,124 | 2024-12-22 | MIT | 固定三阶段、候选过滤和低成本验证 |
| B | [SqueezeAILab/LLMCompiler](https://github.com/SqueezeAILab/LLMCompiler) | 1,891 | 2024-07-10 | MIT | 依赖图、并行工具执行和延迟统计 |
| A | [madaan/self-refine](https://github.com/madaan/self-refine) | 822 | 2024-10-04 | Apache-2.0 | 生成、批评、改写的最小实现 |
| B | [stanford-futuredata/FrugalGPT](https://github.com/stanford-futuredata/FrugalGPT) | 289 | 2025-02-10 | Apache-2.0 | 模型级联、预算约束和质量—成本曲线 |

## 前沿和观察项目

这些项目很新，Star 只能反映早期关注度，不足以证明实验可信度：

| 仓库 | Star | 最近 push | 为什么观察 | 风险 |
| --- | ---: | --- | --- | --- |
| [huawei-csl/RTLScout](https://github.com/huawei-csl/RTLScout) | 58 | 2026-10-05 | 正确性优先、PPA 成本、elite pool、多种 RTL 表示 | 2026 新项目，尚缺长期引用与独立复现 |
| [chateda-ichip/Awesome-AI-for-Chip-Design](https://github.com/chateda-ichip/Awesome-AI-for-Chip-Design) | 26 | 2026-08-04 | 持续更新的 AI-for-chip 文献入口 | 是索引，不是实验依据 |

没有把 ChipMind、RTL-Agent 等仅凭 README 自报提升的新仓库放入核心表；后续若能找到正式论文、固定
commit、完整配置和可重跑产物，再提升优先级。

## 建议的最小复现顺序

1. 只读对照 RTLFixer 的错误分类、RAG 文档格式和三种 feedback 模式。
2. 只读对照 AutoChip 的消息历史与停止条件；仓库较大，先用 GitHub 浏览，不完整克隆。
3. 在隔离目录 shallow clone VerilogCoder，检查规划和波形追踪能否脱离其 benchmark 使用。
4. 用 Agentless/SWE-agent 对照当前 Workflow：确认哪些自由动作可以替换成固定 Node 或结构化接口。
5. 最后才评估 MAGE、MoA 或 OpenHands；它们适合作为设计参考，不适合未经消融直接成为依赖。
