# Agent Quickstart：从运行单题开始

本文用于第一次运行框架。完整的输入来源、模块职责、配置字段、扩展接口与排障见
[User Manual](user-manual.md)；可直接参照的配置见 [config/example.yaml](../../config/example.yaml)。

以下命令从仓库根目录进入 `43240-agent/` 后执行。每次运行使用独立输出目录，避免覆盖旧结果。

## 1. 准备环境

使用 Linux 和 Python 3.10 或以上版本，依赖见 [requirements.txt](../../requirements.txt)。
正式运行的硬监督使用 Linux 进程机制。已有依赖可跳过安装；联网开发环境可在自己的虚拟环境中安装：

```bash
cd 43240-agent
python3 -m venv /tmp/fpgachina-agent-venv
source /tmp/fpgachina-agent-venv/bin/activate
python3 -m pip install -r requirements.txt
```

正式评测环境需预先准备依赖和模型权重，运行时不能下载。第一步使用 mock 假模型，不需要 GPU、真实模型服务或 Vivado。

## 2. 跑通一道题

仓库示例题的输入文件是 `../tasks/ex03_lfsr8/prompt.txt`。接口约束已经在题面内，不要求另外准备 `interface.txt`。

```bash
LLM_BACKEND=mock ./run.sh ../tasks/ex03_lfsr8 /tmp/agent-quickstart \
  --config config/example.yaml --workflow single_generate
```

这条命令让框架读取题目，调用一次假模型，提取候选代码，选择并保存答案。
`example.yaml` 也是省略 `--config` 且未设置 `AGENT_CONFIG` 时自动读取的配置。

查看结果：

```bash
cat /tmp/agent-quickstart/solution.v
cat /tmp/agent-quickstart/run_locator.json
cat /tmp/agent-quickstart/trace.jsonl
```

| 文件 | 第一遍看什么 |
| --- | --- |
| `solution.v` | 是否生成了完整模块；mock 通常把输出置零，只验证流程 |
| `trace.jsonl` | 模型调用、候选选择、最后的状态与停止原因 |
| `config.json` | 实际使用了什么配置，以及每个字段来自 YAML、环境还是命令行 |
| `run_locator.json` | 本次详细记录所在目录 |

**有代码或退出码为 0 不代表功能正确。** 默认 `single_generate` 不进行接口、lint 或综合检查。

## 3. 换成真实模型

先启动一个 OpenAI 兼容的模型服务，再填入它的地址和实际模型名。例如本地服务使用 8000 端口：

```bash
export LLM_BACKEND=openai
export LLM_BASE_URL=http://127.0.0.1:8000/v1
export LLM_MODEL='替换为服务公布的模型名'
./run.sh ../tasks/ex03_lfsr8 /tmp/agent-real --config config/example.yaml
```

服务需要认证时，在启动前设置 `LLM_API_KEY`。YAML 中 `api_key_env: LLM_API_KEY` 是环境变量名称，
实际密钥不写入 YAML。框架不会自动读取 `.env`，也不会替你启动服务。
模型服务部署参数见 [User Manual 的输入来源](user-manual.md#2-输入内容来源与配置)。

## 4. 按示例建立自己的配置

将 [example.yaml](../../config/example.yaml) 复制到开发配置目录，修改后显式选择：

```bash
cp -n config/example.yaml dev/configs/my-agent.yaml
./run.sh ../tasks/ex03_lfsr8 /tmp/agent-custom --config dev/configs/my-agent.yaml
```

同一字段的覆盖顺序是：**内置默认值 → YAML → 支持的环境变量 → 命令行参数**。
如果接着前一步运行，`LLM_BACKEND=openai` 等环境变量仍会覆盖新 YAML，需按实际用途调整或取消设置。
YAML 的相对路径以配置文件所在目录为基准；移动文件后重新核对路径。

常用调整：

| 需要做什么 | 修改位置 |
| --- | --- |
| 切换模型、地址、单次调用超时 | YAML `services.model` 或对应的 `LLM_*` 环境变量 |
| 选择修复流程 | `workflow.type: repair_loop` 或命令行 `--workflow repair_loop` |
| 调整整题预算 | `runtime.deadline_s`、`runtime.reserve_s` |
| 保存详细请求、回复 | `runtime.recording.level: full`，默认开启 |
| 改温度、输出 token 上限或修复轮数 | 在 Python Workflow 中定义，见 [扩展说明](user-manual.md#10-python-组件与扩展) |

## 5. 尝试检查和修复

已连通真实模型，并初始化好 Vivado 的环境与授权后运行：

```bash
./run.sh ../tasks/ex03_lfsr8 /tmp/agent-repair \
  --config dev/configs/my-agent.yaml --workflow repair_loop
```

框架会依次做接口检查、lint（编译与展开设计）、综合，明确的代码错误可以反馈给模型修复。
默认最多生成 3 轮，模型调用总数最多 4 次，同时受整题预算约束。
没有 Vivado 或检查超时会留下相应状态；综合通过也不等于功能正确。

## 6. 查看一次模型调用

先从输出目录的 `run_locator.json` 读取 `record_dir`，再查看其中的 `calls/m001/`：

| 文件 | 内容 |
| --- | --- |
| `request.json` | 实际发送的提示和生成参数的脱敏副本 |
| `response.txt` / `response.json` | 模型服务返回的 HTTP 响应及可解析 JSON，包括服务返回的 reasoning 字段 |
| `content.txt` | 交给代码提取器的正文的脱敏副本 |
| `result.json` / `extraction.json` | 调用状态、错误或代码提取结论 |

mock 不制造 HTTP 响应，连接失败时也可能没有响应文件；`basic` 记录模式不保存这些详细文件。
可用浏览器打开 [日志查看器](../tools/log_viewer.html) 导入运行目录，使用方式见[查看器说明](design/log-viewer.md)。

## 7. 继续做实验或提供 HTTP 接口

对单题做 3 次独立采样，只收集运行和模型指标：

```bash
LLM_BACKEND=mock python3 dev/tools/run.py --config dev/configs/smoke.yaml \
  --task ex03_lfsr8 --samples 3 --tag quickstart
```

命令会打印实验目录，先读其中的 `summary.md`。结果位于 `dev/runs/`，实验笔记位于 `dev/docs/experiments/`。
正式功能判定需要另行启用 `judge` 指标和 Vivado，详见 [开发实验](user-manual.md#12-开发实验与指标)。

提供主办方投题接口时，在新终端进入方案目录，配置好模型，再设置投题令牌和记录目录：

```bash
export FPGACHINA_TOKEN='替换为主办方提供的令牌'
export AGENT_RECORD_ROOT=/tmp/agent-http-records
uvicorn serve.serve_api:app --host 127.0.0.1 --port 7860
```

请求需要携带 Bearer 令牌。该令牌与模型 API key 不同；HTTP 请求结束会清理临时目录，独立记录根目录可保留详细证据。
接口字段及请求示例见 [HTTP 与命令行](user-manual.md#8-命令行与-http-使用)。

## 8. 遇到问题先看哪里

| 现象 | 检查位置 |
| --- | --- |
| 改了 YAML 没生效 | `config.json` 中的 `effective` 和 `sources`，尤其环境变量覆盖 |
| 答案为空 | `trace.jsonl` 的模型错误、提取状态、预算和初始化错误 |
| 没有工具日志 | 确认使用 `repair_loop`；默认单次生成不调用工具 |
| 有答案却运行提前停止 | 候选可能已保存，后续验证因环境或预算停止；看停止原因 |
| 找不到完整回复 | 查看记录等级、`run_locator.json` 和 HTTP 外部记录目录 |

完整排障表见 [User Manual](user-manual.md#14-常见问题与排查顺序)。
