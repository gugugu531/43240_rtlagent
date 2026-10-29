# 设计与开发文档

这些文档描述当前两条工作流、知识检索和接口。仓库保存方案源码、运行配置、当前设计文档和
可执行测试；题库、参考答案、官方测试台、判定反馈、运行日志和本机认证资料不属于提交内容。

| 需要了解的内容 | 阅读入口 |
| --- | --- |
| 系统分层与执行边界 | [架构与设计原则](architecture.md) |
| 新节点、工具、工作流和检查器如何接入 | [模块扩展与开发规范](development.md) |
| 小模型规划、结构检查、key-case checker、归因与修复 | [Guided Verify 工作流](guided-verify.md) |
| Agent 分层、角色、工具路径和提交策略 | [Agent 分层与编排设计](agent-layers.md) |
| LLM/工具/状态/知识检索/提交接口 | [Agent 接口契约](agent-interfaces.md) |
| 129 张知识卡片、BM25/dense 检索和 embedding 配置 | [Skill 与知识检索](knowledge.md) |
| 已实现的工作流注册 | [工作流源码](../agent/orchestration/workflows/__init__.py) |
| 配置结构、环境覆盖与默认值 | [配置实现](../agent/config.py)、[默认配置](../config/single_generate.yaml) |
| 模型声明与服务运行方式 | [模型声明](../model/MODEL.md)、[服务说明](../serve/README.md) |

默认入口为 `single_generate`。`guided_verify` 和 RAG 路线通过显式 `AGENT_CONFIG` 选择。
RAG 不是默认行为；guided 默认保留 legacy 卡片检索。

本仓库不依赖 `dev/` 目录运行。Dockerfile 只复制运行所需的源码、配置、知识资产、服务和
声明文件；开发归档不进入镜像。模型权重、推理服务和 EDA 工具需要另行准备。
