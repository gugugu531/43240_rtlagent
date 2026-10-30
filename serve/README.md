# serve/

推理服务与投题接口。两者跑在同一个实例里，互不干扰。

```
  8000   vllm.sh        推理服务   绑 127.0.0.1，不暴露
  7860   serve_api.py   投题接口   绑 127.0.0.1，经 rc-tunnel 对外
```

---

## 开发期：不需要 GPU

使用 `LLM_BACKEND=mock ./run.sh <输入目录> <输出目录>` 检查入口和日志。mock 仅给占位 RTL，
不代表功能正确。默认 `run.sh` 使用 `config/single_generate.yaml`；`guided_verify` 与 RAG
路线通过显式 `AGENT_CONFIG` 选择。`agent/config.py` 的代码默认仍是 `single_generate.yaml`。
模型传输统一经过 `agent/llm/client.py`；guided 与 RAG 生成流程使用服务端 `/tokenize`
计算上下文余量，`single_generate` 走 baseline 请求，不做该计算。结构化请求默认使用
`response_format: json_schema`，不支持时可在 YAML 显式设置
`services.model.structured_outputs: false`，保留严格校验和有限重问。

## 正式提交：必须是本地权重

```bash
MODEL=/models/Qwen3-8B ./serve/start.sh     # 后台拉起 vllm.sh，就绪后返回

export LLM_BACKEND=openai
export LLM_BASE_URL=http://localhost:8000/v1        # 换成本机
export LLM_API_KEY=dummy
export LLM_MODEL=Qwen3-8B
```

智能体代码无需改动，服务连接通过上述环境变量配置。但提示词与重试策略未必可以直接平移，商用
API 与本地小模型在输出长度、指令遵循、代码格式稳定性上差异明显，围绕前者调好的东西
换到后者常常直接失效。尽早跑一次本地模型。

## 起投题接口

```bash
export FPGACHINA_TOKEN=<赛事方发的令牌>
export MODEL_NAME=Qwen3-8B
./serve/run_api.sh start        # 后台运行，进程退出后等待 2 秒重启

# 让外面能访问到：平台只接管绑在 127.0.0.1 上的 HTTP 服务
/var/run/secrets/frp-self-service/install
env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
    "$HOME/.local/bin/rc-tunnel" expose --port 7860   # 去掉代理变量，否则隧道连不上
```

查看状态用 `./serve/run_api.sh status`，停止用 `./serve/run_api.sh stop`。
日志在 `${AGENT_TMP:-/tmp}/run_api/serve_api.log`；云端应设置 `AGENT_TMP=/var/tmp`。
`API_PORT` 默认 7860；同一实例只运行一个守护服务。
先确认无令牌访问 `curl --noproxy '*' http://127.0.0.1:7860/v1/health` 返回 401，再建立隧道。
平台约 1 分钟探测不到服务就会收回隧道，恢复服务不能恢复旧网址，须重新 expose 并报送。
实例重启后须恢复环境与依赖、启动推理和投题服务、重新安装 rc-tunnel 并建立隧道。
守护脚本只重启退出的 API 进程，不检测卡死、不恢复进行中的任务，也不自动重建隧道。

自测：

```bash
curl -H "Authorization: Bearer $FPGACHINA_TOKEN" http://localhost:7860/v1/health
# {"ready":true,"track":"rtl","model":"Qwen3-8B","vram_gb":21.4}

# 投一道题：立即返回 job_id，之后查询直到 status 为 done
curl -X POST -H "Authorization: Bearer $FPGACHINA_TOKEN" -H "Content-Type: application/json" \
     -d '{"task_id":"t1","nonce":"n1","mode":"agent","prompt":"...","interface":"","deadline_s":900}' \
     http://localhost:7860/v1/solve
curl -H "Authorization: Bearer $FPGACHINA_TOKEN" http://localhost:7860/v1/jobs/<job_id>
```

`track` 必须是 `"rtl"`，赛事方投题前会核对，不符即拒投。

---

## 几处容易踩的地方

**显存按 32 GB 预算，而不是按卡的容量。** vLLM 按 `--gpu-memory-utilization` 乘以整卡显存
预先分配，与模型大小无关。验证窗口的 W7900 有 48 GB，若取 0.90 将占用约 43 GB，超出单卡
32 GB 的上限。`vllm.sh` 因此按 `VRAM_BUDGET_GB`（默认 30）换算该比例，也可用 `GPU_UTIL`
直接指定；提交前须以 `rocm-smi --showmemuse` 实测稳态占用。

**绑 `127.0.0.1`，不是 `0.0.0.0`。** Radeon Cloud 的 `rc-tunnel` 只接管绑在环回口上的
HTTP 服务，绑 `0.0.0.0` 平台不接管。绑错了服务本身是活的，但外面永远打不进来，在赛事方
那边看起来和挂掉没有区别，而失败不重投。

**只暴露 7860 一个端口。** 平台限制一个 notebook 同时只能暴露一个端口。vLLM 的 8000
由智能体经 `127.0.0.1` 内部调用，不要去暴露。**同时参加两个赛道的队伍需要两台 VM。**

**令牌检查不是可选项。** 平台给出的公网 app URL 不带业务层鉴权，没有令牌检查，任何人
拿到网址都能投题。

**工程与中间文件落本地目录。** `AGENT_TMP` 默认 `/tmp`；实例上 `/tmp` 是 4 GB 内存盘，请设为 `/var/tmp`。云平台的 `/workspace` 是 NFS，
Vivado 综合产生的大量小文件写在上面极慢。这不是优化建议。

**服务要能连续跑数百次请求不重启。** 评测期间挂了就是 L0，赛事方不重投。注意每题之后
清理临时目录与子进程，别把磁盘写满。

**投题是异步的。** `POST /v1/solve` 立即返回任务编号，题在后台解，赛事方每 2 秒查询一次。
平台入口会切断 60 秒内没有响应的请求，所以自己改写投题服务时，不能让请求挂着等解题完成。

**自己先超时，别让赛事方超时。** `serve_api.py` 在 `deadline_s - 10` 秒时对 `run.sh`
整个进程组发 SIGTERM，5 秒后 SIGKILL，然后返回已保存的答案。赛事方侧超时一定是 L0，
自己先停至少还有 L1/L2 的可能。要按进程组结束，是因为只杀 `run.sh` 一个进程时，它启动的
智能体与 Vivado 会继续运行，和下一题争抢 GPU 与 CPU。超时后返回的是已保存的答案（没有候选时为空文件），不保证是“最好”结果。

**常驻进程只从 `start.sh` 起。** 推理服务与队伍自己的常驻引擎都写进 `start.sh`，用
`setsid` 拉起。容器重建这条退路下，赛事方只运行 `start.sh` 再逐题调用 `run.sh`，不启动
`serve_api.py`；超时信号发给 `run.sh` 的进程组，由 `run.sh` 在后台带起的常驻进程会随之
被结束。因此常驻进程必须由 `start.sh` 用 `setsid` 启动，不能与单题进程组共享会话。

**进程要自己回收。** 平台实例的 1 号进程是 JupyterLab，它不回收孤儿进程，被结束的子进程
会作为僵尸一直占着进程号，攒多了新进程就起不来。`serve_api.py` 启动时把自己设为回收者
（`PR_SET_CHILD_SUBREAPER`），每题结束后回收该题的全部进程。换成自己的服务时这一段
要保留。

---

## W7900（gfx1100）上的已知问题

初赛与决赛均使用 W7900，显存仍按单卡 32 GB 限制，包含辅助模型。
该架构没有 FP8 矩阵指令；FP8 量化不能据此认定有吞吐加速，须以实测为准。
`Dockerfile` 已固定主办方镜像摘要。镜像仅平台内部可访问，实例无 Docker；
队伍无需在实例构建，赛事方在备用重建方式下使用它，安装步骤须与实例实际操作一致。

## 可选小模型（8011）

`guided_verify` 的 small planner 使用 8011 的 llama.cpp 小模型。官方默认 `serve/start.sh`
不启动它；需要时显式运行：

```bash
VERI_GGUF=/models/verireason-1.5b-f16.gguf ./serve/start_verireason.sh
# 或让 start.sh 一并启动：
VERI_GGUF=/models/verireason-1.5b-f16.gguf ./serve/start.sh
```

脚本是幂等的，缺 `llama-server` 或 GGUF 时明确失败。`guided_verify` 使用完整题面的
分析请求仍应保持 `small.enabled: false`，因为 VeriReason 对完整题面倾向输出 Verilog。
RAG dense 路线使用 `serve/embedding_service.py`，模型别名和维度来自
`config/rag_embedding.yaml`。
