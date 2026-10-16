# 推理服务与投题接口

以下命令在 `43240-agent/` 下运行，按 2026-10-16 实现核对。
推理服务使用本机 8000 端口，投题接口使用 7860 端口；启动参数最终须与 `model/MODEL.md`、`REPORT.md` 的声明一致。
完整方案入口见 [README](../README.md)。

## 不需要 GPU 的流程检查

```bash
LLM_BACKEND=mock ./run.sh ../tasks/example/example_ex03_lfsr8 /tmp/agent-smoke
```

这是开发工作区示例，题库不随方案打包。假模型只验证流程，不能证明 RTL 功能正确。

## 启动本地模型

准备本地权重、依赖和工具后，先配置 Agent 和 baseline 共用的服务：

```bash
export MODEL=/models/Qwen3-8B
export LLM_BACKEND=openai
export LLM_BASE_URL=http://127.0.0.1:8000/v1
export MODEL_NAME=Qwen3-8B
export LLM_MODEL=Qwen3-8B
./serve/start.sh
```

`start.sh` 是常驻服务的统一入口，在服务就绪后返回 0，失败返回非 0；可重复执行，
通过 `setsid` 将推理服务与单题进程组分开。它也补充基础镜像的 EDA 临时目录清理循环，
只清理整棵目录两小时未更新的工程；默认根目录为 `EDA_TMP=/tmp/eda`。
日志在 `SERVE_LOG_DIR`（默认 `$AGENT_TMP/serve-logs`），启动等待上限由 `START_TIMEOUT_S` 设置，默认 900 秒。
容器重建时先执行一次 `start.sh`，随后直接逐题调用 `run.sh` 或 `run_baseline.sh`，无需启动 HTTP 接口。

`vllm.sh` 优先以 `MODEL_NAME`、否则以权重目录最后一级名称作为服务模型名。`MODEL_NAME` 用于 baseline 和默认
`single_generate` 路径；其他模型路径使用 `LLM_MODEL`。这里同时设置，避免更换流程时请求不同模型。
`MAX_LEN`、`VRAM_BUDGET_GB`、`GPU_UTIL`、`VLLM_EXTRA_ARGS` 会改变服务行为，必须记录实际值。
默认按 30 GB 预算和实际卡容量计算显存比例，向下取整，避免 48 GB 卡使用固定 90% 时超出 32 GB；
显式 `GPU_UTIL` 优先，实际峰值仍须在目标 GPU 上测量。脚本根据已安装 vLLM 的帮助信息选择新旧日志参数。
Agent 与 baseline 必须连接同一服务。正式运行使用预先准备的本地权重，不能依赖外部模型 API。

## 开发期连接带鉴权的模型端点

默认 `single_generate` 的 baseline 兼容路径不发送 Authorization 头。需要模型端点鉴权时，
开发实验可显式选择 `evidence_repair` 或 `repair_loop`，再配置 `LLM_API_KEY` 和 `LLM_MODEL`：

```bash
export AGENT_WORKFLOW=evidence_repair
export LLM_BACKEND=openai
export LLM_BASE_URL='https://your-model-endpoint.example/v1'
export LLM_API_KEY='替换为开发端点密钥'
export LLM_MODEL='替换为服务实际模型名'
```

这些是需替换的配置示例。模型端点鉴权与下面的投题令牌是两件事；不要把密钥写入 Git。
外部模型上的结果不能替代本地目标模型与 GPU 验证。

## 启动投题接口

设置好模型后启动接口。默认流程可显式设回 `single_generate`；选择其他流程时按其预算和工具要求配置。

```bash
export AGENT_WORKFLOW=single_generate
export FPGACHINA_TOKEN='替换为赛事投题令牌'
export AGENT_RECORD_ROOT=/tmp/agent-records
uvicorn serve.serve_api:app --host 127.0.0.1 --port 7860
```

检查接口：

```bash
curl -H "Authorization: Bearer $FPGACHINA_TOKEN" http://127.0.0.1:7860/v1/health
```

响应的 `track` 为 `rtl`。`ready: true` 表示配置可读取、任务 Worker 正在运行，且模型列表含有所配置的模型
（mock 后端不查询模型服务）；配置、模型查询或名称核对失败返回 503。它不证明 RTL 功能或 Vivado 授权正常，
还应运行单题检查。`vram_gb` 是接口查询时的值，不是完整评测期间的峰值。

接口按[上游契约](https://gitee.com/Vickyiii/rtlagent2026/blob/master/docs/API_CONTRACT.md)提供异步投题：

```bash
curl -X POST http://127.0.0.1:7860/v1/solve \
  -H "Authorization: Bearer $FPGACHINA_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"task_id":"t1","nonce":"unique-nonce-1","mode":"agent","prompt":"Implement a module named TopModule with input a and output q, assign q=a.","deadline_s":60}'
# 202 返回 job_id、task_id、status；将下面的 <job_id> 换成返回值。
curl -H "Authorization: Bearer $FPGACHINA_TOKEN" \
  http://127.0.0.1:7860/v1/jobs/<job_id>
```

查询状态为 `queued`、`running` 或 `done`，仅 `done` 含 `solution`、`trace`、`elapsed_s`；
失败返回空答案，并保留可用的 trace 和服务错误类别。非空 nonce 重复投递始终返回原任务，
空 nonce 每次新建任务；`mode` 只接受 `agent` 或 `baseline`，`deadline_s` 必须为正整数。
结果和 nonce 映射保存在 HTTP 进程内，重启后清空。部署使用一个 uvicorn Worker，不能加 `--workers` 或 `--reload`。
本地只读主办方文档保留原快照，本文对应上游提交 `9df1767`。

Radeon Cloud 环境的既有部署方式是将投题接口绑定到环回地址，再通过平台隧道暴露：

```bash
/var/run/secrets/frp-self-service/install
env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
  "$HOME/.local/bin/rc-tunnel" expose --port 7860
```

仅暴露投题接口，8000 端口用于内部模型调用。平台差异与历史环境验证见开发区的
[远端管理](../dev/docs/design/remote-tools.md)；独立提交包不包含开发区。

## 时间、文件与运行维护

- `AGENT_TMP` 默认 `/tmp`，中间工程应使用本地盘，避免网络文件系统拖慢 Vivado。
- 接口串行执行任务，从投题起计算剩余时间，扣除排队和准备时间，并预留 `min(0.25, deadline_s × 0.1)` 秒用于返回。
  排队耗尽时间时不启动求解，直接返回空结果；子进程接收剩余硬期限；内部运行预算还受配置的清理预留和单次调用超时约束。超时后恢复已保存的选择，不能保证一定得到可用答案。
- 投题接口和模型端点分别管理鉴权。公网地址不能代替业务令牌检查。
- HTTP 服务在 Linux 下接管孤儿进程，只回收本题进程组；服务退出时停止当前求解并结束排队任务。
- 持续运行时检查临时文件、记录目录和子进程回收。完整模型记录需配置 `AGENT_RECORD_ROOT` 到请求临时目录之外。云端实例用完立即释放。
- 不同 GPU 架构、量化内核和服务版本必须分别验证；历史机器上可启动或测得的速度不直接外推到比赛环境。
