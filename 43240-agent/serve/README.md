# 推理服务与投题接口

以下命令在 `43240-agent/` 下运行，按 2026-10-14 实现核对。
推理服务使用本机 8000 端口，投题接口使用 7860 端口；启动参数最终须与 `model/MODEL.md`、`REPORT.md` 的声明一致。
完整方案入口见 [README](../README.md)。

## 不需要 GPU 的流程检查

```bash
LLM_BACKEND=mock ./run.sh ../tasks/example/example_ex03_lfsr8 /tmp/agent-smoke
```

这是开发工作区示例，题库不随方案打包。假模型只验证流程，不能证明 RTL 功能正确。

## 启动本地模型

准备本地权重、依赖和工具后，在一个终端启动服务：

```bash
MODEL=/models/Qwen3-8B ./serve/vllm.sh
```

在另一个终端配置 Agent：

```bash
export LLM_BACKEND=openai
export LLM_BASE_URL=http://127.0.0.1:8000/v1
export MODEL_NAME=Qwen3-8B
export LLM_MODEL=Qwen3-8B
```

`vllm.sh` 以权重目录的最后一级名称作为服务模型名。`MODEL_NAME` 用于 baseline 和默认
`single_generate` 路径；其他模型路径使用 `LLM_MODEL`。这里同时设置，避免更换流程时请求不同模型。
`MAX_LEN`、`GPU_UTIL`、`VLLM_EXTRA_ARGS` 会改变服务行为，必须记录实际值；默认值不代表最终选型。
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

响应的 `track` 为 `rtl`。`ready: true` 只表明接口完成配置读取，不证明模型、Vivado 或整个求解链路已就绪；
还应运行单题检查。`vram_gb` 是接口查询时的值，不是完整评测期间的峰值。

Radeon Cloud 环境的既有部署方式是将投题接口绑定到环回地址，再通过平台隧道暴露：

```bash
/var/run/secrets/frp-self-service/install
"$HOME/.local/bin/rc-tunnel" expose --port 7860
```

仅暴露投题接口，8000 端口用于内部模型调用。平台差异与历史环境验证见开发区的
[远端管理](../dev/docs/design/remote-tools.md)；独立提交包不包含开发区。

## 时间、文件与运行维护

- `AGENT_TMP` 默认 `/tmp`，中间工程应使用本地盘，避免网络文件系统拖慢 Vivado。
- 接口从收到请求起计算剩余时间，扣除准备时间，并预留 `min(0.25, deadline_s × 0.1)` 秒用于返回。
  子进程接收剩余硬期限；内部运行预算还受配置的清理预留和单次调用超时约束。超时后恢复已保存的选择，不能保证一定得到可用答案。
- 投题接口和模型端点分别管理鉴权。公网地址不能代替业务令牌检查。
- 持续运行时检查临时文件、记录目录和子进程回收，先完成连续请求验证。云端实例用完立即释放。
- 不同 GPU 架构、量化内核和服务版本必须分别验证；历史机器上可启动或测得的速度不直接外推到比赛环境。
