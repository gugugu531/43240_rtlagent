# Agent 框架使用手册

适用于当前代码；核对版本：`6700ded`（2026-10-05）。[详细参考](reference.md) · [开发规范](conventions.md)。
以下命令先从仓库根目录执行 `cd 43240-agent`。依赖见 requirements.txt；只跑 mock 不需要 GPU 或 Vivado。

## 1. 跑一道题

```bash
LLM_BACKEND=mock ./run.sh ../tasks/ex03_lfsr8 /tmp/agent-out
```

看 `/tmp/agent-out/solution.v` 和 `trace.jsonl`。默认 `single_generate` 只生成一次，不注入技能或执行检查。
mock 只验证流程，答案不保证正确；进程返回零也不表示题目通过，要看答案、trace 和判定。

已经启动本地模型服务时，设置服务实际返回的模型名：

```bash
export LLM_BACKEND=openai
export LLM_BASE_URL=http://127.0.0.1:8000/v1
export LLM_MODEL=你的服务模型名
./run.sh ../tasks/ex03_lfsr8 /tmp/agent-real
```

如需认证，设置 `LLM_API_KEY`。正式运行使用预先准备的本地开源模型，不能临时联网下载。

## 2. 选择 Workflow 和配置

```bash
# 可选修复循环，需要 Vivado；没有工具时不会获得检查通过结论
./run.sh ../tasks/ex03_lfsr8 /tmp/agent-repair --workflow repair_loop

# 指定配置；默认是 config/default.yaml
./run.sh ../tasks/ex03_lfsr8 /tmp/agent-config --config config/default.yaml
```

**Python 定义流程与组件参数，YAML 选择 Workflow、服务和运行条件。**
覆盖顺序：默认值 → YAML → 支持的环境变量 → CLI；HTTP 截止时间只能缩小预算。
YAML 路径相对于配置文件，命令行路径相对于当前目录。模型服务默认上限 180 秒，整题 360 秒，清理预留 20 秒。

## 3. 单题实验和重复采样

```bash
# 一道题采样三次，只统计运行和模型信息
LLM_BACKEND=mock python3 dev/tools/run.py --config dev/configs/smoke.yaml \
  --task ex03_lfsr8 --samples 3 --tag my-test

# 连通真实服务后，Agent 与原始 baseline 各跑一次，并进行官方判定
python3 dev/tools/run.py --config dev/configs/remote-smoke.yaml --tag real-test

# 不启用任何指标
LLM_BACKEND=mock python3 dev/tools/run.py --config dev/configs/smoke.yaml --metrics --tag solve-only
```

remote-smoke.yaml 示例指向 `127.0.0.1:18000`；使用前调整到你的服务地址、模型名，或通过环境变量覆盖。
指标选项为 `runtime model judge`，选择 judge 才运行官方 Vivado 判定。mock 不能同时跑 baseline。
`--task` 仍遵守排除清单；`--solve-jobs` 和 `--metric-jobs` 分别控制求解与指标并发。

命令输出实验目录：先看 `summary.md`，再看 `samples/<模式>/<题目>/s1/`。
原始产物在 `dev/runs/`，笔记在 `dev/docs/experiments/`；在笔记的生成块外补写假设与结论。

## 4. 编写自己的 Workflow

例如创建 `agent/workflows/my_workflow.py`，在 Python 中显式改变生成参数：

```python
from agent.core.registry import WORKFLOW_REGISTRY
from agent.workflows.single_generate import SingleGenerate


@WORKFLOW_REGISTRY.register("my_generate")
class MyGenerate(SingleGenerate):
    def __init__(self):
        super().__init__(max_tokens=4096, temperature=0.1)
```

```bash
./run.sh ../tasks/ex03_lfsr8 /tmp/my-out \
  --import-module agent.workflows.my_workflow --workflow my_generate
```

实验 YAML 可写 `imports: [agent.workflows.my_workflow]`，再选择 `workflow.type: my_generate`。
自定义 Node、自由 Python 分支和组件测试见[详细参考的扩展说明](reference.md#3-python-组件与扩展)。
每题创建新实例；不读取参考答案，不导入 dev。不要给 YAML 增加组件参数或 bindings 字段。

## 5. 查模型原始回复

在样本输出目录读取 `run_locator.json`，找到详细记录目录。一次调用位于 `calls/m001/`：

| 文件 | 内容 |
| --- | --- |
| request.json | 实际消息与请求参数 |
| response.txt / response.json | 脱敏后的原始 HTTP 响应，包含服务返回的 reasoning 等字段 |
| content.txt | 提取器实际使用的标准正文的脱敏副本 |
| result.json / extraction.json | 调用状态与提取结论 |

默认 full 保存详细记录；basic 不保存这些文件。连接失败可能没有响应，mock 不伪造原始 HTTP 响应。
HTTP 开发测试设 `AGENT_RECORD_ROOT=/tmp/agent-records`，否则默认详细记录会随请求临时目录删除。

## 6. HTTP 与提交检查

```bash
export FPGACHINA_TOKEN=本地测试令牌
export AGENT_RECORD_ROOT=/tmp/agent-records
uvicorn serve.serve_api:app --host 127.0.0.1 --port 7860
```

通过 `/v1/health` 和 `/v1/solve` 访问，携带 `Authorization: Bearer <令牌>`。
Agent 可以使用 `AGENT_CONFIG`；HTTP baseline 使用 `LLM_BASE_URL`、`LLM_MODEL`，不读取 Agent YAML。

```bash
python3 dev/tools/submission.py --stage /tmp/agent-submission \
  --task ../tasks/ex03_lfsr8 --output /tmp/agent-submission-smoke
```

暂存目标必须不存在。该检查不包含模型权重，也不代替真实镜像构建或比赛 GPU 验证。
远端管理用法见[远端工具说明](design/remote-tools.md)，凭据位于 `dev/tools/remote/remote.env`。

## 常见问题

| 现象 | 先检查 |
| --- | --- |
| 改了 YAML 却没有生效 | output/config.json 的 effective 与 sources，是否有环境变量覆盖 |
| 答案为空 | trace 的模型错误、提取结果、预算或初始化错误，再读对应详细证据 |
| 默认没有工具日志 | single_generate 不运行工具；judge 是独立实验指标 |
| token 为 null / 指标 partial | 该调用没有可用用量，或记录不完整，不能当作零 |
| baseline 连接失败 | 实际服务地址和模型名；原始 baseline 不携带认证头 |
| HTTP 返回后找不到原始回复 | 是否设置独立 AGENT_RECORD_ROOT；查看详细目录是否可写 |
