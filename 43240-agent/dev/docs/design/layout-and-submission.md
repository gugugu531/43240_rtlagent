# 目录组织与提交检查

本文是当前接口的专题参考；完整索引见[User Manual](../user-manual.md)。

## 运行结构

```text
agent/main.py → core.configuration → core.supervision → core.runner
                                                    → core.context
                                                    → workflows / nodes
                                                    → services / recording
```

core 包含候选、接口、运行状态、预算与注册表。services/tools.py 是统一检查服务，vivado.py
是实际工具实现。nodes/extraction.py 提供提取逻辑，prompts/builder.py 与 skills.py 提供提示和
技能选择，recording/artifacts.py 负责原子答案及恢复检查点。默认策略和已有接口语义保持不变。

```python
Runner.run(task, workflow, *, options, started_at=None) -> WorkflowResult
Supervisor.run(spec: RunSpec) -> WorkflowResult
RunContext.execute(node, input) -> output
RepairLoop.choose(state) -> SelectionDecision
```

本次没有旧路径兼容层。公开示例、测试、HTTP 服务和开发工具均使用新的模块位置。
每题仍独立构造 Workflow/Node；正式代码不导入 dev。

## 开发区

开发区收敛为 tools、configs、tests、runs、docs。云端工具在 tools/remote，历史统计在
 tools/analysis，参考答案链路验证直接使用未改动的官方 selftest/run_selftest.sh --reference。
Agent/baseline 新实验及联合远程脚本调用 tools/run.py，不再保留旧 run_eval.py 求解主流程。
官方 HTTP 投题与 selftest 的开发封装继续使用官方入口；它们不维护另一套 Agent 算法。

所有团队文档集中在 docs 的 design、notes、experiments。开发规范位于 docs/conventions.md，
AGENTS.md 与 dev/README.md 只提供必要入口。旧文件的身份、生成块、数字和来源保留，旧模型分析
不被宣称适配新实验格式。用户未提交笔记继续保留原位置，不参与本阶段提交。

remote.env、cloud.state 与 cloud_known_hosts 随工具迁移至 tools/remote，内容不变且由
 dev/.gitignore 排除。迁移期间不能保留活动云端任务：看门狗和旧进程可能仍引用旧路径。
本轮开始前云端已销毁，本轮只作离线验证。

## 提交检查接口

```python
check_submission_layout(root: Path) -> CheckReport
stage_submission(root: Path, destination: Path) -> SubmissionManifest
smoke_submission(staged_root: Path, task_dir: Path, output_dir: Path) -> SmokeResult
```

check_submission_layout 检查必需文件、名称、符号链接、明显的本地配置或日志、正式 Python 的
直接开发依赖，以及当前 Docker COPY 的源文件与目标路径。源目录旁存在 example 时核对 baseline
原文。此检查不推断动态导入，也不能自动证明提交文件不含参考答案或隐蔽凭据。

stage_submission 只复制明确清单：agent、config、skill、serve、model，以及两个入口、原始
baseline.py、依赖、声明和规定文档。目标必须不存在，且在源码目录外；清单与文件哈希写在目标
目录旁。缓存、开发区、任务和外置模型权重不复制，不能把它当作完整模型镜像。

smoke_submission 在暂存目录运行默认 mock 单题，清除继承的配置覆盖与 PYTHONPATH，强制选择
single_generate；输出写在暂存目录外。检查进程、非空答案、正式监督结果和未回收后代。
这是独立运行验证，不是 RTL 功能判定。单元测试还通过本地假 HTTP 服务验证暂存 baseline 入口。

```bash
python3 dev/tools/submission.py --stage /tmp/agent-submission \
  --task ../tasks/ex03_lfsr8 --output /tmp/agent-submission-smoke
```

Dockerfile 明确复制 config/ 和 baseline.py，构建上下文继续排除整个 dev/。
真实镜像构建仍需要可用的官方基础镜像及已准备的依赖、模型；目标 GPU 验证另行授权开展。
