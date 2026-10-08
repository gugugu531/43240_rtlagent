# 团队开发文档

当前框架的两个入口：

- **[Quickstart](quickstart.md)**：准备环境、运行单题、接入模型、选择配置和查看结果。
- **[User Manual](user-manual.md)**：输入来源、模块职责、完整配置、流程、接口、记录、实验、扩展与排障。

框架手册按 2026-10-08 工作区实现核对；逐项注释配置见 [example.yaml](../../config/example.yaml)。[开发规范](conventions.md)独立维护协作规则。
归档只调整文档状态与入口，所有实验、验证、决策和原始资源数据保留；历史结论不自动成为当前行为。

## 当前专题参考

| 文档 | 内容 |
| --- | --- |
| [Python Workflow](design/python-workflows.md) | 注册、组件和上下文 |
| [配置与实验](design/configuration-and-experiments.md) | YAML、统一入口与指标 |
| [记录格式](design/trace-schema.md) | trace 与完整模型证据 |
| [日志查看器](design/log-viewer.md) | 在浏览器中查看执行流程、节点状态与响应 |
| [可靠运行](design/runtime-reliability.md) | 选择、诊断、缓存、预算与监督 |
| [目录与提交](design/layout-and-submission.md) | 文件组织和独立打包检查 |
| [远端管理](design/remote-tools.md) | 脚本使用，平台细节带历史实测范围 |
| [历史分析工具](design/historical-analysis.md) | 保留的旧格式统计工具 |

已移除被新手册替代的旧指南和临时输入输出说明；此前文档维护记录见[2026-10-05 整理记录](notes/2026-10-05-documentation-progress.md)。

## 归档笔记与验证证据

以下是当时的审查、计划、决策与验证记录。查当前接口用上面的指南；查“为什么”和实验依据用这些记录。

| 记录 | 归档性质 |
| --- | --- |
| [0001-inference-backend](notes/0001-inference-backend.md) | 历史选型决策：尚未定稿，不作为当前服务配置 |
| [0002-model-choice](notes/0002-model-choice.md) | 历史选型决策：尚未定稿，不作为当前服务配置 |
| [2026-09-23-plan-review](notes/2026-09-23-plan-review.md) | 归档笔记：结论、路径与命令反映当时实验或设计 |
| [2026-09-24-baseline-sweep](notes/2026-09-24-baseline-sweep.md) | 归档笔记：结论、路径与命令反映当时实验或设计 |
| [2026-09-25-candidate-tables](notes/2026-09-25-candidate-tables.md) | 历史生成表：保留原文与测量值 |
| [2026-09-25-joint-first-results](notes/2026-09-25-joint-first-results.md) | 归档笔记：结论、路径与命令反映当时实验或设计 |
| [2026-09-25-model-fingerprints](notes/2026-09-25-model-fingerprints.md) | 归档笔记：结论、路径与命令反映当时实验或设计 |
| [2026-09-25-model-screening-plan](notes/2026-09-25-model-screening-plan.md) | 归档笔记：结论、路径与命令反映当时实验或设计 |
| [2026-09-25-screening-progress](notes/2026-09-25-screening-progress.md) | 归档笔记：结论、路径与命令反映当时实验或设计 |
| [2026-09-25-screening-results](notes/2026-09-25-screening-results.md) | 归档笔记：结论、路径与命令反映当时实验或设计 |
| [2026-10-05-agent-redesign-plan](notes/2026-10-05-agent-redesign-plan.md) | 归档设计讨论：含已实施和未实施设想 |
| [2026-10-05-agent-review](notes/2026-10-05-agent-review.md) | 归档审查：问题针对表中历史源码版本 |
| [2026-10-05-gpu-diagnosis-and-model-validation](notes/2026-10-05-gpu-diagnosis-and-model-validation.md) | 归档验证记录：只说明该次版本和测试范围 |
| [2026-10-05-stage1-progress](notes/2026-10-05-stage1-progress.md) | 归档验证记录：只说明该次版本和测试范围 |
| [2026-10-05-stage2-progress](notes/2026-10-05-stage2-progress.md) | 归档验证记录：只说明该次版本和测试范围 |
| [2026-10-05-stage3-progress](notes/2026-10-05-stage3-progress.md) | 归档验证记录：只说明该次版本和测试范围 |
| [2026-10-05-stage3-remote-validation](notes/2026-10-05-stage3-remote-validation.md) | 归档验证记录：只说明该次版本和测试范围 |
| [2026-10-05-stage4-progress](notes/2026-10-05-stage4-progress.md) | 归档验证记录：只说明该次版本和测试范围 |
| [2026-10-05-stage5-progress](notes/2026-10-05-stage5-progress.md) | 归档验证记录：只说明该次版本和测试范围 |
| [agent-repair](notes/agent-repair.md) | 归档笔记：结论、路径与命令反映当时实验或设计 |
| [l0-error-codes](notes/l0-error-codes.md) | 归档笔记：结论、路径与命令反映当时实验或设计 |
| [serving-stack](notes/serving-stack.md) | 归档笔记：结论、路径与命令反映当时实验或设计 |
| [sim-mismatch](notes/sim-mismatch.md) | 归档笔记：结论、路径与命令反映当时实验或设计 |
| [thinking-in-content](notes/thinking-in-content.md) | 归档笔记：结论、路径与命令反映当时实验或设计 |

[模型资源人工数据](notes/model-metrics-manual.json)保留每项来源，不因归档改变值。

## 实验记录（全部保留）

笔记保存于 experiments/，原始数据仍在 dev/runs/；生成块不手改，人工假设与结论在块外。
旧格式与新格式以各次记录为准。用户已有的一份未提交笔记仍在原路径，未修改、未移动：
`dev/experiments/20261004-212040-joint-cur-qwen3-8b-quick.md`（仅本地存在，不在 Git 中）。

- [20261005-201406-stage5-mock-9f5cfd91](experiments/20261005-201406-stage5-mock-9f5cfd91.md)
- [20261005-193024-stage4-real-single-ff1050ad](experiments/20261005-193024-stage4-real-single-ff1050ad.md)
- [20261005-191812-stage4-vivado-smoke-1b9df732](experiments/20261005-191812-stage4-vivado-smoke-1b9df732.md)
- [20261005-191114-stage4-mock-6e70ebfb](experiments/20261005-191114-stage4-mock-6e70ebfb.md)
- [20261005-184136-stage3-real-repair-single](experiments/20261005-184136-stage3-real-repair-single.md)
- [20261005-184027-stage3-real-nothink-smoke](experiments/20261005-184027-stage3-real-nothink-smoke.md)
- [20261005-183124-stage3-real-default-smoke](experiments/20261005-183124-stage3-real-default-smoke.md)
- [20261005-175329-stage3-reference-smoke](experiments/20261005-175329-stage3-reference-smoke.md)
- [20260928-091940-quant-gptq4-qwen3-30b-2507](experiments/20260928-091940-quant-gptq4-qwen3-30b-2507.md)
- [20260928-091939-quant-gptq4-qwen3-30b-2507](experiments/20260928-091939-quant-gptq4-qwen3-30b-2507.md)
- [20260928-085636-b-layer-devstral-small-2-24b-awq4](experiments/20260928-085636-b-layer-devstral-small-2-24b-awq4.md)
- [20260928-081128-b-layer-gemma4-12b-bf16](experiments/20260928-081128-b-layer-gemma4-12b-bf16.md)
- [20260928-073818-b-layer-ministral3-14b-awq4](experiments/20260928-073818-b-layer-ministral3-14b-awq4.md)
- [20260928-010839-b-layer-seed-oss-36b-awq4](experiments/20260928-010839-b-layer-seed-oss-36b-awq4.md)
- [20260928-003043-b-layer-qwen2.5-coder-7b-bf16](experiments/20260928-003043-b-layer-qwen2.5-coder-7b-bf16.md)
- [20260927-174638-repeat-quick-qwen3.6-35b-a3b-s3](experiments/20260927-174638-repeat-quick-qwen3.6-35b-a3b-s3.md)
- [20260927-152225-screen-gpt-oss-20b-default](experiments/20260927-152225-screen-gpt-oss-20b-default.md)
- [20260927-144737-screen-qwen3.5-9b-bf16](experiments/20260927-144737-screen-qwen3.5-9b-bf16.md)
- [20260925-204950-screen-A9sub-qwen3.6-27b-awq](experiments/20260925-204950-screen-A9sub-qwen3.6-27b-awq.md)
- [20260925-201330-screen-A2-qwen3.5-35b-a3b-awq](experiments/20260925-201330-screen-A2-qwen3.5-35b-a3b-awq.md)
- [20260925-194130-screen-A1-qwen3.6-35b-a3b-awq](experiments/20260925-194130-screen-A1-qwen3.6-35b-a3b-awq.md)
- [20260925-190435-mock-joint](experiments/20260925-190435-mock-joint.md)
- [20260925-184802-joint-A7-codev-r1-7b-quick](experiments/20260925-184802-joint-A7-codev-r1-7b-quick.md)
- [20260925-183849-joint-A5-30b-2507-awq4-quick](experiments/20260925-183849-joint-A5-30b-2507-awq4-quick.md)
- [20260925-182514-joint-A6-4b-bf16-quick](experiments/20260925-182514-joint-A6-4b-bf16-quick.md)
- [20260925-181040-joint-Q1a-4b-awq4-quick](experiments/20260925-181040-joint-Q1a-4b-awq4-quick.md)
- [20260925-174008-quant-Q1-qwen3-4b-awq8](experiments/20260925-174008-quant-Q1-qwen3-4b-awq8.md)
- [20260925-170706-quant-Q1-qwen3-4b-awq4](experiments/20260925-170706-quant-Q1-qwen3-4b-awq4.md)
- [20260925-164737-screen-A6-qwen3-4b-instruct-2507-bf16](experiments/20260925-164737-screen-A6-qwen3-4b-instruct-2507-bf16.md)
- [20260925-161426-screen-A4-qwen3-coder-30b-a3b-awq](experiments/20260925-161426-screen-A4-qwen3-coder-30b-a3b-awq.md)
- [20260925-155654-screen-A7-codev-r1-7b](experiments/20260925-155654-screen-A7-codev-r1-7b.md)
- [20260925-154115-screen-A5-qwen3-30b-2507-awq](experiments/20260925-154115-screen-A5-qwen3-30b-2507-awq.md)
- [20260925-150906-mock-metrics](experiments/20260925-150906-mock-metrics.md)
- [20260924-210547-full-qwen3-30b-a3b-gptq-nothink](experiments/20260924-210547-full-qwen3-30b-a3b-gptq-nothink.md)
- [20260924-210230-q-qwen3-30b-a3b-gptq-nothink](experiments/20260924-210230-q-qwen3-30b-a3b-gptq-nothink.md)
- [20260924-204635-full-qwen3-8b-nothink](experiments/20260924-204635-full-qwen3-8b-nothink.md)
- [20260924-203451-q-qwen25-coder-7b](experiments/20260924-203451-q-qwen25-coder-7b.md)
- [20260924-202620-q-qwen3-32b-awq-nothink](experiments/20260924-202620-q-qwen3-32b-awq-nothink.md)
- [20260924-201123-q-qwen25-coder-32b-awq](experiments/20260924-201123-q-qwen25-coder-32b-awq.md)
- [20260924-200443-q-qwen3-8b-nothink](experiments/20260924-200443-q-qwen3-8b-nothink.md)
- [20260924-120512-baseline-qwen3-8b-parser-merged](experiments/20260924-120512-baseline-qwen3-8b-parser-merged.md)
- [20260924-113712-baseline-qwen3-8b-think](experiments/20260924-113712-baseline-qwen3-8b-think.md)
- [20260924-110334-cloud-qwen3-8b-smoke](experiments/20260924-110334-cloud-qwen3-8b-smoke.md)
- [20260923-203605-ref-full](experiments/20260923-203605-ref-full.md)
