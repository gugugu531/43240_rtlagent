# 设计与开发文档

这些文档描述当前仓库的 Burr 实现，面向维护者和模块扩展者。仓库保存方案源码、运行配置、
当前设计文档和可执行测试；题库、参考答案、官方测试台、判定反馈、运行日志和本机认证资料
不属于提交内容。历史 RAG 实验记录已移到工作区 `dev/archives/20261029-rag-rc46/`，
不随参赛包分发。

| 需要了解的内容 | 阅读入口 |
| --- | --- |
| 系统如何分层，为什么采用显式工作流，哪些边界不能绕过 | [架构与设计原则](architecture.md) |
| 新节点、工具、工作流、模型协议和检查器如何接入；可运行示例与验证要求 | [模块扩展与开发规范](development.md) |
| 首稿优先、一次修复、路由门禁、复核/归因契约 v2、预算与中立采样 | [自适应工作流](adaptive.md) |
| 小模型路由、关键 case 行为检查、独立上下文与可配置循环 | [Guided Verify 工作流](guided-verify.md) |
| Agent 分层、角色、工具路径、模型 profile 与提交策略 | [Agent 分层与编排设计](agent-layers.md) |
| LLM/工具/上下文/阶段/提交的目标字段与兼容边界 | [Agent 接口契约](agent-interfaces.md) |
| Skill、RAG 目录、检索模式、可选启用方式与当前限制 | [Skill 与 RAG](knowledge.md) |
| 恢复条件、检查器补丁、比较覆盖、阶段预算及真实效果的验收边界 | [恢复链路与验证契约](recovery.md) |
| 已实现的工作流 | [工作流源码](../agent/orchestration/workflows/__init__.py) |
| 配置结构、环境覆盖与默认值 | [配置实现](../agent/config.py)、[代码默认配置](../config/single_generate.yaml)、[分支默认配置](../config/adaptive_verify.yaml) |
| 模型声明与服务运行方式 | [模型声明](../model/MODEL.md)、[服务说明](../serve/README.md) |

本仓库不依赖 `dev/` 目录运行。Dockerfile 只复制运行所需的源码、配置、知识资产、服务和
声明文件；开发归档不进入镜像。模型权重、推理服务和 EDA 工具需要另行准备。

RAG 的 rc4.6 研究路线是可显式启用的，`adaptive_verify` 默认关闭；`guided_verify`
仍使用既有 legacy `runtime-v1` bundle 的 BM25 与 planner knowledge 注入，新 rc4.6
路线尚未接入。启用方式、资产锁和失败关闭边界见 [Skill 与 RAG](knowledge.md)。

阅读示例前先准备好 [requirements.txt](../requirements.txt) 的依赖。mock 只验证流程，
不代表真实 RTL 功能、模型效果或官方成绩。
