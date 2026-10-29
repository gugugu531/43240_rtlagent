# 设计与开发文档

这些文档描述本仓库当前的 Burr 实现，面向维护者和模块扩展者。当前已按层重排目录，包含模型 profile、Stage 描述、有界工具循环、提交网关、ContextBundle/PromptAssembly、自适应路由门禁与检查器/归因契约 v2，以及可选 Skill 与诊断 RAG；核对日期为 2026-10-29。后续变更应同步维护相关章节。方案根目录 README 保持为空，本文件是仓库内的设计文档入口。

| 需要了解的内容 | 阅读入口 |
| --- | --- |
| 当前完整交付状态、RAG／路由／embedding、全部卡片分布、Skill 缺陷与实验归档规则 | [最终交接报告](2026-10-29-final-rag-skill-handoff.md) |
| rc4.6、第四批十张 restricted、当前版本模型配对与启用条件 | [rc4.6运行入口](2026-10-29-rag-rc46-runbook.md) |
| restricted 到默认生产批准、混合 canary 与回退要求 | [生产化路径](2026-10-29-rag-restricted-to-production-plan.md) |
| 当前rc4.3、首批十卡中的三张受限晋升、双路由验证与上传检查点 | [rc4.3交付入口](2026-10-29-rag-rc43-runbook.md) |
| 第49批完成审计、97卡本地修订、机械r2包与正在运行的v52十卡批次 | [当前审计与实验交接](2026-10-29-rag-v49-audit-v51-package.md) |
| 97张研究卡逐卡证据、剩余工作与第49批进度 | [97张卡准备情况](2026-10-29-rag-97-readiness.md) |
| 第45批16次完成、mixed-sign回归、四类扩展及真实首次路由 | [本批审计与处置](2026-10-29-rag-batch45-results.md) |
| 历史rc4.2、十五类题面谓词、五类受限候选与收紧发布沿 | [rc4.2运行入口](2026-10-29-rag-rc42-runbook.md) |
| 新四类候选、mixed-sign修订和packer真实首次路由 | [第45批安排](2026-10-29-rag-batch45-plan.md) |
| 历史rc3.2候选、十二类谓词、四类受限注入与回退 | [rc3.2运行入口](2026-10-29-rag-rc32-runbook.md) |
| 第42批20次真实生成完成、六类新版筛选、跨方法准入修复 | [本批完成报告](2026-10-29-rag-batch42-results.md) |
| 六类新方法扩展、四张修订卡独立确认、双机20次预算 | [第42批扩展](2026-10-29-rag-batch42-expansion.md) |
| 六小时工作已完成、28次调用独立审计、最终候选包与剩余边界 | [完成报告与交付](2026-10-29-rag-six-hour-results.md) |
| 统一目录rc2部署、shadow入口、embedding身份和回退 | [运行说明](2026-10-29-rag-catalog-v3-runbook.md) |
| 六小时计划实际实施、发布候选、启动修正和实时证据 | [执行记录](2026-10-29-rag-six-hour-execution.md) |
| 剩余六小时：并库缺口、题面路由、embedding 与双机预算 | [六小时执行计划](2026-10-29-rag-final-six-hour-plan.md) |
| 2026-10-29 夜间完成结果、98 次调用、准入误判和逐卡处置 | [v35 完整审计](2026-10-29-rag-night35-audit.md) |
| 2026-10-29 夜间 97 卡冻结、修订、独立预算和双机接手 | [夜间执行与交接](2026-10-29-rag-night35-plan-and-handoff.md) |
| v29 原始证据复核、二十卡双机新批次和压缩反馈 embedding 测试 | [v32 审计与执行](2026-10-28-rag-v32-audit-and-execution.md) |
| 2026-10-28 本地与双机环境、已完成实验、冻结包和接手步骤 | [RAG 完整交接](2026-10-28-rag-handoff.md) |
| 剩余不足一天：新卡批量验证、embedding 对照和统一调用预算 | [最新执行计划](2026-10-28-rag-final-day-batch-and-embedding-plan.md) |
| 系统如何分层，为什么采用显式工作流，哪些边界不能绕过 | [架构与设计原则](architecture.md) |
| 新节点、工具、工作流、模型协议和检查器如何接入；可运行示例与验证要求 | [模块扩展与开发规范](development.md) |
| 恢复条件、检查器补丁、比较覆盖、阶段预算及真实效果的验收边界 | [恢复链路与验证契约](recovery.md) |
| 固定 Skill、诊断检索、预算与资产边界 | [Skill 与诊断 RAG](knowledge.md) |
| 2026-10-27 三天全量处置与加速筛选计划、136 卡覆盖口径、验证分层与停止边界 | [知识工作安排](knowledge.md#2026-10-27-三天全量卡片处置与加速筛选v17) |
| 候选资产、shadow、受限 exact 与默认自动注入的分级门槛；首批十卡机械计划 | [知识分级与机械冻结](knowledge.md#2026-10-27-宽松收录机械冻结与保守注入v18) |
| 首稿优先、一次修复、路由门禁、复核/归因契约 v2、预算与中立采样 | [自适应工作流](adaptive.md) |
| 小模型路由、关键 case 行为检查、独立上下文与可配置循环 | [guided_verify 设计](guided-verify.md) |
| 小模型选法、行式向量表检查器、单一修复上限与独立归因 | [Guided Verify 工作流设计](guided-verify.md) |
| Agent 分层、角色、工具路径、模型 profile 与提交策略 | [Agent 分层与编排设计](agent-layers.md) |
| LLM/工具/上下文/阶段/提交的目标字段与兼容边界 | [Agent 接口契约](agent-interfaces.md) |
| 已实现的四条工作流 | [工作流源码](../agent/orchestration/workflows/__init__.py) |
| 配置结构、环境覆盖与默认值 | [配置实现](../agent/config.py)、[代码默认配置](../config/single_generate.yaml)、[分支默认配置](../config/adaptive_verify.yaml) |
| 模型声明与服务运行方式 | [模型声明](../model/MODEL.md)、[服务说明](../serve/README.md) |

本仓库保存方案源码、配置及这组维护文档。题库、参考答案、官方测试台、判定反馈、运行日志和本机认证资料不属于提交内容；本地 HTML 日志查看器与实验档案也不在仓库中。运行时不依赖这些开发资料，Dockerfile 当前也不会复制本目录进入运行镜像。

阅读示例前先准备好 [requirements.txt](../requirements.txt) 的依赖。模型权重、推理服务和 EDA 工具需要另行准备；示例中的 mock 只验证流程，不代表真实 RTL 功能、模型效果或官方成绩。
# 2026-10-29 RAG batch 49

- [20-card shadow screening plan](2026-10-29-rag-batch49-plan.md)
