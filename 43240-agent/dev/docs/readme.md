# 团队开发文档

当前指南按 2026-10-14 工作区实现核对。历史笔记、实验正文和测量值保留原样；历史结论不自动代表当前行为。

## 从这里开始

| 你要做什么 | 阅读入口 |
| --- | --- |
| 首次跑通单题 | [Quickstart](quickstart.md) |
| 配置模型、选择流程、跑实验或排查失败 | [User Manual](user-manual.md) |
| 了解提交方案和独立运行方式 | [方案 README](../../README.md)、[服务启动](../../serve/README.md) |
| 修改代码或文档 | [开发规范](conventions.md) |
| 选题、导入题库、检查参考答案 | [题集说明](design/datasets.md)、[题库索引](../../../tasks/index.md) |
| 阅读实验结果和比较模型 | [指标与比较范围](design/experiment-reading.md)、[实验索引](experiments/index.md) |
| 查设计原因、历史验证或未完成设想 | [笔记索引](notes/index.md) |

## 当前专题

| 文档 | 维护内容 |
| --- | --- |
| [注释配置](../../config/example.yaml) | 配置字段与示例；覆盖顺序见手册 |
| [运行契约](design/agent-runtime.md) | 上下文、诊断、候选搜索、token 预算、初始检查点重放 |
| [规格自测基础](design/spec-test-foundation.md) | 可选计划、时序、自建测试台和候选保护接口；由独立实验入口显式使用 |
| [可选实验工作流](design/experimental-workflows.md) | 显式选择工具反馈、规格自测或双候选分歧；默认入口不变 |
| [记录格式](design/trace-schema.md) | trace 事件与模型证据字段 |
| [日志查看器](design/log-viewer.md) | 浏览运行节点、请求与响应 |
| [远端管理](design/remote-tools.md) | 云端生命周期与远端实验操作；平台实测有日期限制 |
| [历史分析工具](design/historical-analysis.md) | 旧格式统计工具的适用范围 |

## 最近的验证与证据

- [第四批实验工作流接入验收](notes/2026-10-15-experimental-workflows-validation.md)：可选入口、候选保护与真实工具验证，含现有短截止失败对照。

- [本次文档整理验收](notes/2026-10-14-documentation-organization.md)：修改范围与离线检查结果。

- [PR #33 审查修复验收](notes/2026-10-14-pr33-review-validation.md)：近期运行契约和候选策略的验证范围。
- [题库目录验收](notes/2026-10-14-dataset-source-layout.md)：按来源存储、旧题号兼容和离线回归。
- [均衡题集验收](notes/2026-10-14-balanced-datasets-validation.md)、[筛选统计](notes/2026-10-14-balanced-datasets-selection.md)：全池检查与开发题集选择。
- [AutoDL Qwen3 实测](notes/2026-10-11-autodl-qwen3-results.md)、[输出额度补测](notes/2026-10-11-qwen3-output-budget.md)：该批硬件、模型与题集范围内的结果。
- [本地证据位置核对](notes/2026-10-14-evidence-locations.md)：哪些目录当前可查、哪些仍是历史机器或聊天路径。

新增笔记登记到笔记索引，新增实验登记到实验索引。长期用法更新对应专题，历史记录只在正文之外追加带日期的说明，不另建 archive 目录。
