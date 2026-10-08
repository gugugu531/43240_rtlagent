# 配置与统一实验入口

本文是当前配置与实验的专题参考；总览见[User Manual](../user-manual.md)。流程、Node 及动作参数仍由 Python 定义；YAML 选择 Workflow、
外部服务、运行条件与开发实验。没有 YAML 流程图、bindings 或 Node 装配清单。

## 运行与配置

正式入口仍为 `run.sh <input_dir> <output_dir>`，默认加载 `config/example.yaml`。
使用 `AGENT_CONFIG` 或附加 `--config` 选择配置。附加的路径参数相对于调用者的当前目录；
YAML 中的路径相对于该 YAML 文件。正式代码不导入开发工具。

```bash
LLM_BACKEND=mock ./43240-agent/run.sh tasks/ex03_lfsr8 /tmp/out \
  --config 43240-agent/config/example.yaml

python3 43240-agent/dev/tools/run.py \
  --config 43240-agent/dev/configs/smoke.yaml --task ex03_lfsr8
```

以下示例保存为 `dev/configs/my-experiment.yaml` 时，其相对路径有效：

```yaml
schema_version: 1
imports: []
workflow:
  type: single_generate
services:
  model:
    backend: mock
    model: mock-model
    api_key_env: LLM_API_KEY
    timeout_s: 180
  tools:
    part: xczu3eg-sbva484-1-e
    temp_dir: /tmp
    keep_work: false
runtime:
  deadline_s: 360
  reserve_s: 20
  recording:
    level: full
experiment:
  tasks:
    root: ../../../tasks
    ids: [ex03_lfsr8]
  modes: [agent]
  samples: 1
  solve_jobs: 1
  metric_jobs: 1
  metrics: [runtime, model]
  tag: smoke
```

真实模型设置 `services.model.backend=openai`、`model` 和 `base_url`；API key 通过
`api_key_env` 引用指定环境变量，不写入 YAML。工具可用 `services.tools.bin_dir` 指定
Vivado 可执行文件目录。记录可用 `runtime.recording.root` 指定独立位置。

Workflow 只配置 `type`；采样、技能、修复次数和组件选择保留在 Python 构造函数中。
需要变化时注册另一个 Workflow，或通过已有 Python 构造接口传入参数。

框架拒绝未知字段、重复键、YAML 别名、错误类型和不支持的版本，不提供配置继承或表达式。
模型地址不能带 URL 凭据、查询参数或 fragment。扩展通过 `imports` 显式指定本地模块，
不得使用 `dev` 或 `selftest` 作为运行扩展；自定义代码也必须遵守不读取参考答案的规则。

覆盖顺序为内置默认、YAML、支持的环境变量、CLI。每个字段记录生效来源。
支持的环境变量见方案 README；`AGENT_TMP` 优先于 `EDA_TMP` 和 `TRACK_TMP`。
CLI 支持 Workflow、扩展模块、整题预算、清理预留、记录目录与级别、候选保存开关。
HTTP 另传 `hard_deadline_s`，只缩小总预算，不扩大配置预算。服务请求上限、Node 上限与
剩余求解窗口共同决定实际模型调用超时；清理预留大于预算时可以不启动求解。

```python
load_config(path: Path | None) -> ConfigDocument
resolve_config(document, *, env=None, overrides=RunOverrides()) -> ResolvedConfig
build_run_spec(task, config, *, output_dir, started_at, hard_deadline_s=None) -> RunSpec
```

`ResolvedConfig` 包含 `AgentConfig`、逐字段来源与原始配置；凭据只进入模型服务对象，
公开快照不包含凭据值。CLI、HTTP 的子进程和实验样本共用这些接口与原有 Supervisor。
`RunSpec` 向 Worker 传递明确的模型、工具配置与配置快照；Workflow 在 Worker 内构造。
生效配置及来源只保存在 trace 的 `run/metadata` 事件中。配置失败留下空答案和失败 trace。
Supervisor 已经开始执行后的异常不由入口清空已有答案。

## 开发实验

统一入口为 `dev/tools/run.py`，参数包括：

| 参数 | 作用 |
| --- | --- |
| `--config` | 必填，选择实验 YAML |
| `--task` | 只选指定题目，覆盖 YAML 的 ids/list，不取消排除规则 |
| `--workflow` | 覆盖已注册 Workflow 名称 |
| `--modes` | agent、baseline，可同时选；mock 不允许 baseline |
| `--metrics` | runtime、model、judge；不给值可关闭全部指标 |
| `--samples` | 每题每模式采样次数 |
| `--solve-jobs`、`--metric-jobs` | 求解与指标各自的并发上限 |
| `--tag` | 实验标签 |

任务配置可以选择 `ids` 或 `list`（每行一个题目名称，两者互斥）；都不设置时枚举题目。
`exclude` 指向排除清单，省略时使用 `dev/configs/exclude.txt`。指定缺失、重复题目、越出
任务根目录的路径或全部排除都报错，不退回全题集。
运行前冻结实际清单、顺序和题面/接口哈希，每次启动前核对输入是否变化。
Agent 收到题目目录后只读取题面和接口；判定器单独读取 task.json、测试台和参考实现。

```python
select_tasks(selection: TaskSelection) -> TaskManifest
build_sample_plan(manifest, config: ExperimentConfig) -> tuple[SampleSpec, ...]
ExperimentRunner.run(plan, config: ResolvedExperiment) -> ExperimentResult
```

每个 Agent 样本启动独立正式入口，间接使用现有 Supervisor，不在线程中共享 Supervisor。
baseline 调用原始入口，外围执行器提供进程组停止与输出日志。求解线程和指标线程只调度
独立进程或读取产物。TERM/INT 停止后续启动，取消活动求解与判定，并保存样本和汇总。
取消样本的指标可以标为 skipped，不伪造执行成功。

实验先解析并冻结生效配置，再生成内部 `resolved.yaml` 供各个正式入口读取；子进程移除
已处理的环境覆盖项，不二次覆盖配置。样本 trace 元数据中的 `parent_config` 指向实验
原配置、生效值及来源。显式独立记录根目录保持有效，默认记录在样本下。

## 指标

`agent/recording/metrics.py` 提供通用契约和 runtime/model 指标。
`dev/tools/metrics/judge.py` 调用官方判定器，参考答案和判定结果不返回求解上下文。
只执行选择的指标；未启用 judge 不启动 Vivado 判定。

```python
class MetricCollector(Protocol):
    name: str
    version: int
    def collect(self, sample: CompletedSample) -> MetricResult: ...

collect_metrics(sample, collectors) -> tuple[MetricResult, ...]
summarize_experiment(samples, *, planned=0, status='completed') -> dict
```

Python 可以直接传入自定义 collector；当前 YAML/CLI 的可选名称为三个内置指标。
`MetricResult` 保存名称、版本、状态、值与相对于样本目录的证据引用。
状态为 ok、partial、unavailable、error、skipped，不与代码通过状态混用。

- runtime：实际求解墙钟、停止原因、Node 与检查次数、检查复用、已知 Node 耗时、监督清理。
  Node 耗时为已结束节点的耗时相加；嵌套节点可能重叠，不能当作整题墙钟耗时。
- model：调用尝试、成功/失败/未完成、截断、明确重试决定、已知 token 合计和未知调用数量。
- judge：官方等级、系数、环境错误、原始结果和完整日志；等级零可以是正常判定结果。

mock 没有已知 token 时记为 null；已知零与未知分别表示。开始和结束事件只计一次调用，
被中断的开始事件单列未完成。基本记录下缺失的证据不通过推断补齐。
指标异常不修改答案，保存 error。环境错误、判定异常不能冒充代码零分。
官方等级聚合复用 `selftest/score.py`；不改其分母、环境失败和系数规则。
增益只在双方有效样本覆盖一致时给出，并记录请求上限差异。
默认 Agent 服务上限为 180 秒，baseline 固定 300 秒；remote-smoke 示例显式使用 300 秒。

## 产物与来源

```text
runs/<experiment_id>/
├── config.json                 # 原始配置、生效值及来源（脱敏）
├── resolved.yaml               # 内部正式运行配置，不含凭据值
├── experiment.json             # 状态、版本、模式、采样和并发
├── tasks.json                  # 实际清单、排除结果和输入哈希
├── source/                     # 明确范围内源码与快照清单
├── samples/<mode>/<task>/s<index>/
│   ├── solution.v、trace.jsonl、solve.json；baseline 样本另有 config.json
│   ├── records/                # 正式 Agent 完整证据；设置独立根目录时由 trace 的 record_dir 给出
│   ├── process_logs/、run.log
│   ├── judge/                  # 仅启用判定时生成
│   └── metrics.json
├── metrics.json                # 逐样本指标及来源
├── summary.json
└── summary.md                  # 可重新生成的摘要
```

源码快照只选 Agent、服务、技能、所用开发工具、入口与配置等文本；不复制任务参考答案、
模型、环境文件和运行日志。保存原文件及快照哈希，已知秘密和明显的凭据赋值被遮盖。
遮盖改变了源码、扩展来源未取得时标为不完整，不能声称完整复现。
当前不保存依赖安装包，也不锁定模型权重；Git 版本和源码快照不足以保证模型推理完全一致。
自动实验笔记放 `dev/docs/experiments/`，生成块与人工假设/结论分开。

开发工具与文档已集中迁移；旧实验产物保留，历史分析继续读取原格式。本框架没有旧内部路径兼容层；历史回复重放、选择重放和自动消融比较尚未实现。
