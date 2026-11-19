# 设计与开发文档

这些文档描述当前两条工作流、知识检索和接口。仓库保存方案源码、运行配置、当前设计文档和
可执行测试；题库、参考答案、官方测试台、判定反馈、运行日志和本机认证资料不属于提交内容。

| 需要了解的内容 | 阅读入口 |
| --- | --- |
| 系统分层与执行边界 | [架构与设计原则](architecture.md) |
| 新节点、工具、工作流和检查器如何接入 | [模块扩展与开发规范](development.md) |
| 策略选技能、RTL 生成与修改、逐点行为检查与复核、交付与兜底 | [guided_verify 工作流](guided-verify.md) |
| Agent 分层、角色、工具路径和提交策略 | [Agent 分层与编排设计](agent-layers.md) |
| 大语言模型、工具、状态、知识检索和答案提交的接口 | [Agent 接口契约](agent-interfaces.md) |
| 129 张知识卡片、词项检索、向量检索和文本嵌入配置 | [技能与知识检索](knowledge.md) |
| 工作流节点与分支连线 | [默认三角色流程](../agent/orchestration/workflows/guided_verify.py)、[单次生成流程](../agent/orchestration/workflows/single_generate.py) |
| 实时展示与新工作流接入 | [工作台操作](../serve/README.md#实时工作台)、[v1 事件格式与扩展示例](live-events.md) |
| 配置结构、环境覆盖与默认值 | [配置实现](../agent/config.py)、[默认配置](../config/guided_verify.yaml) |
| 模型声明与服务运行方式 | [模型声明](../model/MODEL.md)、[服务说明](../serve/README.md) |

默认入口为 `guided_verify`，规划与后续阶段使用同一 Qwen3.8-27B 服务，每个阶段分别构造请求上下文。默认关闭 RAG（检索增强生成）的知识卡片检索，技能选择仍启用。单次生成工作流 `single_generate` 和可选 RAG 配置通过 `AGENT_CONFIG` 选择，具体前提见对应文档。

本仓库不依赖 `dev/` 目录运行。Dockerfile 按清单复制源码、配置、知识资产、服务、声明、报告和许可文件。模型权重、推理服务和 EDA（电子设计自动化）工具需要另行准备。
