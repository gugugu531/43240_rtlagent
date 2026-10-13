# 团队开发文档

新增 Agent 运行契约见 [上下文、诊断与候选策略接口](design/agent-runtime.md)。

PR #33 的审查修复、运行编号和本地证据见
[审查修复验收记录](notes/2026-10-14-pr33-review-validation.md)。

当前框架的两个入口：

- **[Quickstart](quickstart.md)**：准备环境、运行单题、接入模型、选择配置和查看结果。
- **[User Manual](user-manual.md)**：输入来源、模块职责、完整配置、流程、接口、记录、实验、扩展与排障。

框架手册按 2026-10-09 工作区实现核对；逐项注释配置见 [example.yaml](../../config/example.yaml)。[开发规范](conventions.md)独立维护协作规则。
归档只调整文档状态与入口，所有实验、验证、决策和原始资源数据保留；历史结论不自动成为当前行为。

## 当前专题参考

当前模型实验依据见下方 AutoDL Qwen3 实测汇总。10 月 10 日的开发提案与资源分配检查已列入归档笔记；其当时的待办、资源条件和未测试状态不代表当前进展。

| 文档 | 内容 |
| --- | --- |
| [记录格式](design/trace-schema.md) | trace 与完整模型证据 |
| [日志查看器](design/log-viewer.md) | 在浏览器中查看执行流程、节点状态与响应 |
| [远端管理](design/remote-tools.md) | 脚本使用，平台细节带历史实测范围 |
| [历史分析工具](design/historical-analysis.md) | 保留的旧格式统计工具 |

最近云端实验（已完成、实例已释放）：[AutoDL Qwen3 实测汇总](notes/2026-10-11-autodl-qwen3-results.md)；[Qwen3 思考模式输出额度补测](notes/2026-10-11-qwen3-output-budget.md)。

已移除被新手册替代的旧指南和临时输入输出说明；此前文档维护记录见[2026-10-05 整理记录](notes/2026-10-05-documentation-progress.md)。

本次合并与测试整理见[清理清单及执行结果](notes/2026-10-09-cleanup-review.md)。

## 归档笔记与验证证据

以下是当时的审查、计划、决策与验证记录。查当前接口用上面的指南；查“为什么”和实验依据用这些记录。

| 记录 | 归档性质 |
| --- | --- |
| [2026-10-10-rtl-agent-proposal](notes/2026-10-10-rtl-agent-proposal.md) | 历史提案：部分前置工作已完成，候选路线尚未选定或实施 |
| [2026-10-10-cloud-allocation-check](notes/2026-10-10-cloud-allocation-check.md) | 历史环境检查：该次分配失败，后续 AutoDL 测试另有记录 |
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
旧格式与新格式以各次记录为准。10 月 4 日旧格式记录保留在原路径 `dev/experiments/`，已补充历史口径说明并纳入版本管理；历史测量值与原始日志保持不变。

- [20261007-221221-cloud-single-review-691f4b83](experiments/20261007-221221-cloud-single-review-691f4b83.md)：AMD 环境单题验证，不能外推完整题集或证明请求等价。
- [20261004-212040-joint-cur-qwen3-8b-quick](../experiments/20261004-212040-joint-cur-qwen3-8b-quick.md)：旧实现联合实验；保留原表，得分与因果解释见文件顶部说明。

- [20261011-162201-qwen3-4b-thinking-2507-think-full34-168e9695](experiments/20261011-162201-qwen3-4b-thinking-2507-think-full34-168e9695.md)
- [20261011-161532-qwen3-coder-30b-a3b-instruct-awq-nothink-full34-98a8eb93](experiments/20261011-161532-qwen3-coder-30b-a3b-instruct-awq-nothink-full34-98a8eb93.md)
- [20261011-161100-qwen3-4b-instruct-2507-nothink-full34-9ad508d8](experiments/20261011-161100-qwen3-4b-instruct-2507-nothink-full34-9ad508d8.md)
- [20261011-160821-qwen3-8b-nothink-full34-ccef6ff7](experiments/20261011-160821-qwen3-8b-nothink-full34-ccef6ff7.md)
- [20261011-160033-qwen3-30b-a3b-gptq-int4-nothink-full34-3bd85161](experiments/20261011-160033-qwen3-30b-a3b-gptq-int4-nothink-full34-3bd85161.md)
- [20261011-155728-qwen3-8b-fp8-nothink-full34-ac839aaa](experiments/20261011-155728-qwen3-8b-fp8-nothink-full34-ac839aaa.md)
- [20261011-155521-qwen3-1p7b-fp8-nothink-full34-9ebfce50](experiments/20261011-155521-qwen3-1p7b-fp8-nothink-full34-9ebfce50.md)
- [20261011-155349-qwen3-0p6b-fp8-nothink-full34-a233f01c](experiments/20261011-155349-qwen3-0p6b-fp8-nothink-full34-a233f01c.md)
- [20261011-155029-qwen3-32b-awq-nothink-full34-3b83cdee](experiments/20261011-155029-qwen3-32b-awq-nothink-full34-3b83cdee.md)
- [20261011-154546-qwen3-4b-nothink-full34-07c53ac0](experiments/20261011-154546-qwen3-4b-nothink-full34-07c53ac0.md)
- [20261011-154029-qwen3-14b-awq-nothink-full34-ad93ffc3](experiments/20261011-154029-qwen3-14b-awq-nothink-full34-ad93ffc3.md)
- [20261011-150418-qwen3-8b-awq-think-full34-6e6f79af](experiments/20261011-150418-qwen3-8b-awq-think-full34-6e6f79af.md)
- [20261011-142353-qwen3-4b-awq-think-full34-4f3ab9b5](experiments/20261011-142353-qwen3-4b-awq-think-full34-4f3ab9b5.md)
- [20261011-141910-qwen3-8b-awq-nothink-full34-9be62c55](experiments/20261011-141910-qwen3-8b-awq-nothink-full34-9be62c55.md)
- [20261011-141315-qwen3-4b-awq-nothink-full34-8422a6e7](experiments/20261011-141315-qwen3-4b-awq-nothink-full34-8422a6e7.md)
- [20261011-141021-qwen3-1p7b-nothink-full34-b48a6ffb](experiments/20261011-141021-qwen3-1p7b-nothink-full34-b48a6ffb.md)
- [20261011-140545-qwen3-0p6b-nothink-full34-d85dbf85](experiments/20261011-140545-qwen3-0p6b-nothink-full34-d85dbf85.md)
- [20261011-140418-qwen3-0p6b-nothink-smoke-96a7f52a](experiments/20261011-140418-qwen3-0p6b-nothink-smoke-96a7f52a.md)

- [20261011-165418-qwen3-4b-fp8-nothink-r165351-full34-7e39ace2](experiments/20261011-165418-qwen3-4b-fp8-nothink-r165351-full34-7e39ace2.md)

- [20261011-165850-qwen3-4b-awq-think-32k-truncated-9909d824](experiments/20261011-165850-qwen3-4b-awq-think-32k-truncated-9909d824.md)

- [20261011-182653-qwen3-8b-awq-think-32k-truncated-06fa26d5](experiments/20261011-182653-qwen3-8b-awq-think-32k-truncated-06fa26d5.md)

- [20261011-190449-qwen3-4b-thinking-2507-think-32k-truncated-f917d002](experiments/20261011-190449-qwen3-4b-thinking-2507-think-32k-truncated-f917d002.md)

- [20261011-192206-qwen3-14b-fp8-nothink-full34-b6d4a848](experiments/20261011-192206-qwen3-14b-fp8-nothink-full34-b6d4a848.md)

- [20261011-192507-qwen3-32b-awq-nothink-r192435-full155-f0548440](experiments/20261011-192507-qwen3-32b-awq-nothink-r192435-full155-f0548440.md)

- [20261011-193839-qwen3-8b-fp8-nothink-r193812-full155-706f2796](experiments/20261011-193839-qwen3-8b-fp8-nothink-r193812-full155-706f2796.md)

- [20261011-195619-qwen3-30b-a3b-gptq-int4-nothink-r195537-full155-c55acbe3](experiments/20261011-195619-qwen3-30b-a3b-gptq-int4-nothink-r195537-full155-c55acbe3.md)

- [20261011-201323-qwen3-coder-30b-a3b-instruct-awq-nothink-r201246-full155-60c897f6](experiments/20261011-201323-qwen3-coder-30b-a3b-instruct-awq-nothink-r201246-full155-60c897f6.md)

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
