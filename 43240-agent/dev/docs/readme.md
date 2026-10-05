# 团队开发文档

所有团队文档统一存放在此处。[开发规范](conventions.md)定义目录、依赖、测试、文档和 Git 约定。
主办方原始文档、方案 README、模型声明和技能说明继续保留规定位置。

## 当前框架

默认 single_generate 近似 baseline；Python Workflow/Node、完整证据、候选保护、进程监督、
YAML 配置与统一实验已实现。历史重放和新的实验比较暂缓。各阶段实施与验证范围见下面的记录，
模型与服务尚未最终确定，单题验证不代表整体增益。

## 设计与工具

- [Python Workflow 与 Node 接口](design/python-workflows.md)
- [配置与统一实验](design/configuration-and-experiments.md)
- [运行记录格式](design/trace-schema.md)
- [候选、失败处理与监督](design/runtime-reliability.md)
- [目录组织与提交检查](design/layout-and-submission.md)
- [远端管理](design/remote-tools.md)
- [历史实验分析](design/historical-analysis.md)

## 阶段记录

- [第五阶段：目录与提交检查](notes/2026-10-05-stage5-progress.md)

- [2026-10-05-gpu-diagnosis-and-model-validation](notes/2026-10-05-gpu-diagnosis-and-model-validation.md)
- [2026-10-05-stage1-progress](notes/2026-10-05-stage1-progress.md)
- [2026-10-05-stage2-progress](notes/2026-10-05-stage2-progress.md)
- [2026-10-05-stage3-progress](notes/2026-10-05-stage3-progress.md)
- [2026-10-05-stage3-remote-validation](notes/2026-10-05-stage3-remote-validation.md)
- [2026-10-05-stage4-progress](notes/2026-10-05-stage4-progress.md)

## 模型决策与失败分析

历史模型选型和失败分析均保留，内容与实测来源见各篇；目录迁移不表示结论已重新验证。

| 文档 | 性质 |
| --- | --- |
| [0001：推理后端](notes/0001-inference-backend.md) | 决策，最终选择待定 |
| [0002：模型选择](notes/0002-model-choice.md) | 决策，建议与证据，待团队确定 |
| [服务栈](notes/serving-stack.md) | 服务与硬件限制分析 |
| [功能失配](notes/sim-mismatch.md) | 仿真失败分析 |
| [修复收益](notes/agent-repair.md) | 历史 Agent 策略分析 |
| [thinking 正文](notes/thinking-in-content.md) | 服务回复分析 |
| [L0 错误码](notes/l0-error-codes.md) | 工具报错分析 |

## 其他笔记

- [2026-09-23-plan-review](notes/2026-09-23-plan-review.md)
- [2026-09-24-baseline-sweep](notes/2026-09-24-baseline-sweep.md)
- [2026-09-25-candidate-tables](notes/2026-09-25-candidate-tables.md)
- [2026-09-25-joint-first-results](notes/2026-09-25-joint-first-results.md)
- [2026-09-25-model-fingerprints](notes/2026-09-25-model-fingerprints.md)
- [2026-09-25-model-screening-plan](notes/2026-09-25-model-screening-plan.md)
- [2026-09-25-screening-progress](notes/2026-09-25-screening-progress.md)
- [2026-09-25-screening-results](notes/2026-09-25-screening-results.md)
- [2026-10-05-agent-redesign-plan](notes/2026-10-05-agent-redesign-plan.md)
- [2026-10-05-agent-review](notes/2026-10-05-agent-review.md)

人工模型资源数据见 [model-metrics-manual.json](notes/model-metrics-manual.json)，每项保留来源。

## 实验记录

- [第五阶段迁移 smoke](experiments/20261005-201406-stage5-mock-9f5cfd91.md)

新旧实验笔记集中在 experiments/；原始数据仍在 dev/runs/，格式以各次记录为准。

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
