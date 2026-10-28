# 设计与开发文档

这些文档描述本仓库当前的 Burr 实现，面向维护者和模块扩展者。当前已按层重排目录，包含模型 profile、Stage 描述、有界工具循环、提交网关、ContextBundle/PromptAssembly，以及自适应路由门禁与检查器/归因契约 v2；核对日期为 2026-10-28。后续变更应同步维护相关章节。方案根目录 README 保持为空，本文件是仓库内的设计文档入口。

| 需要了解的内容 | 阅读入口 |
| --- | --- |
| 系统如何分层，为什么采用显式工作流，哪些边界不能绕过 | [架构与设计原则](architecture.md) |
| 新节点、工具、工作流、模型协议和检查器如何接入；可运行示例与验证要求 | [模块扩展与开发规范](development.md) |
| 恢复条件、检查器补丁、比较覆盖、阶段预算及真实效果的验收边界 | [恢复链路与验证契约](recovery.md) |
| 固定 Skill、诊断检索、预算与资产边界 | [Skill 与诊断 RAG](knowledge.md) |
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
