# serve/

推理服务与投题接口。两者跑在同一个实例里，互不干扰。

```
  8010   llamacpp.sh    推理服务   绑 127.0.0.1，不暴露
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

## 正式提交：HIP + MTP3 本地文本 GGUF

正式路线使用 [Qwen/Qwen3.8-27B](https://huggingface.co/Qwen/Qwen3.8-27B)，
两份权重均来自 [ggml-org/Qwen3.8-27B-GGUF 固定版本](https://huggingface.co/ggml-org/Qwen3.8-27B-GGUF/tree/a316ea527fde32c12487be7574e2db5ac2ad2a7e)
（revision `a316ea527fde32c12487be7574e2db5ac2ad2a7e`）：

| 用途 | 文件 | 字节数 | SHA256 |
| --- | --- | ---: | --- |
| 主模型 | `Qwen3.8-27B-Q4_K_M.gguf` | 18,973,870,528 | `c600de0300ae8a0eb3a6c0b8b5561b8b96f16bd2c863c2a66c42de29d391a747` |
| MTP（多 token 预测）头 | `mtp-Qwen3.8-27B-Q4_0.gguf` | 1,680,271,776 | `c5be331f82fb61f5304adfa00ccd60c6743c8ce52255d66fa863446231d49ba4` |

两文件均已实读核对哈希并与公开来源匹配。只加载文本权重，不加载 mmproj；
MTP 头不是独立求解模型，但属于 `auxiliary_models`，显存必须计入。
模型声明见 [MODEL.md](../model/MODEL.md)。
2026-10-30 已核对现有服务实际运行 HIP + MTP3，后端为 `llama-server 0.4.0-dev`
（build 1，源码 commit `f114f91f9ed6792cf402437e3874adad98902744`），
二进制 SHA256 为 `290708d22f8b495d36b8aedd0afb0cdc081c415548f855e6a950a75dd742ad97`。
实际加载 HIP、amdhip、hipblas 和 rocblas 运行库。换编译产物或运行库后须重新核对兼容性，
不能只依据版本字符串认定相同；脚本不编译后端，也不自动识别或选择 GPU 后端。

### 复用已有服务

以下命令均从方案仓库根目录运行。先人工核对已有服务的两份模型文件、哈希、版本及
实际启动参数与声明一致，不要仅凭 alias 判断权重；并检查 `/slots` 的
`speculative=true`，确认启用推测解码。`start.sh` 只检查本机对应端口的 `/health`；
已健康时复用，不会重复加载主模型，也不会替换、重启已有服务。
`/health` 成功不证明 HIP、权重或 MTP3 参数已匹配，不能跳过上述人工核对。

```bash
export LLM_BACKEND=openai LLM_BASE_URL=http://127.0.0.1:8010/v1
export LLM_API_KEY=dummy
export MODEL_NAME=qwen38-27b-q4-k-m LLM_MODEL=qwen38-27b-q4-k-m
PORT=8010 ./serve/start.sh
```

### 没有现有服务时启动

断网前从上述固定版本下载两份 GGUF，按表中大小与 SHA256 核对；在本地准备适用于
目标 AMD GPU、支持 `draft-mtp` 的 HIP 构建 `llama-server`，以及匹配的
HIP/amdhip、hipblas、rocblas 等运行库。权重和二进制不随方案提交，脚本不会下载。
默认从 `PATH` 找 `llama-server`，主权重默认在 `/models/Qwen3.8-27B-Q4_K_M.gguf`，
MTP 权重默认在 `/models/mtp-Qwen3.8-27B-Q4_0.gguf`；可通过环境变量显式指定：

```bash
export LLM_BACKEND=openai LLM_BASE_URL=http://127.0.0.1:8010/v1
export LLM_API_KEY=dummy
export MODEL_NAME=qwen38-27b-q4-k-m LLM_MODEL=qwen38-27b-q4-k-m
MODEL=/local/models/Qwen3.8-27B-Q4_K_M.gguf \
MTP_MODEL=/local/models/mtp-Qwen3.8-27B-Q4_0.gguf \
LLAMA_SERVER=/local/bin/llama-server ./serve/start.sh
```

`/local` 是示例准备位置，须换为实际路径。任一权重缺失或不可读、找不到二进制时明确失败，不自动降级为无 MTP。
主模型日志在 `${SERVE_LOG_DIR:-${AGENT_TMP:-/tmp}/serve-logs}/llamacpp.log`；
就绪等待默认 `START_TIMEOUT_S=900`。启动使用 `setsid`，保持原有临时目录清理及可选小模型机制。

`llamacpp.sh` 默认参数：`PORT=8010`、`MAX_LEN=65536`、`PARALLEL=1`、
`N_GPU_LAYERS=all`、`THREADS=16`、`THREADS_BATCH=16`、`FLASH_ATTN=on`、
`REASONING_BUDGET=-1`，固定绑定 `127.0.0.1` 并启用 `--no-webui --metrics`。
固定使用 `--cpu-strict 1`、FP16 KV cache（`--cache-type-k f16 --cache-type-v f16`），
以及 MTP3 参数 `--spec-type draft-mtp --model-draft "$MTP_MODEL" --spec-draft-ngl all --spec-draft-n-max 3`。
无额外 RoPE 覆盖；已核对的现有服务 CPU affinity 为 0–15，脚本不据此自动绑定 CPU。
覆盖端口时也要同步 `LLM_BASE_URL`；覆盖 `MODEL_NAME` 时同步 `LLM_MODEL`；
改变模型或服务参数须同步模型声明。
默认 `single_generate` 与 baseline 共用此服务和 manifest 思考设置（`enable_thinking=true`），
不启用 Skill、RAG、独立 planner 或 embedding；MTP 预测头仍随主模型加载并计入辅助模型。

Dockerfile 不复制权重或开发区；使用前须在基础镜像或挂载目录中准备兼容的 HIP 后端及运行库，
再挂载两份本地权重，必要时覆盖 `LLAMA_SERVER`。这些部署说明不代表已完成容器构建、
冷启动或目标 GPU 的完整验收。本轮只修仓库，未发布新版本或切换云端服务；
实例重启和公网网址配置由用户自行完成。旧无 MTP 服务和旧公网测试仅为历史记录，
不能作为当前 HIP + MTP3 路线的验收证据。

## 起投题接口

```bash
export FPGACHINA_TOKEN=<赛事方发的令牌>
export MODEL_NAME=qwen38-27b-q4-k-m
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
# 核对 ready、track="rtl" 和 model="qwen38-27b-q4-k-m"；vram_gb 不是峰值测量。

# 投一道题：立即返回 job_id，之后查询直到 status 为 done
curl -X POST -H "Authorization: Bearer $FPGACHINA_TOKEN" -H "Content-Type: application/json" \
     -d '{"task_id":"t1","nonce":"n1","mode":"agent","prompt":"...","interface":"","deadline_s":900}' \
     http://localhost:7860/v1/solve
curl -H "Authorization: Bearer $FPGACHINA_TOKEN" http://localhost:7860/v1/jobs/<job_id>
```

`track` 必须是 `"rtl"`，赛事方投题前会核对，不符即拒投。

---

## 几处容易踩的地方

**显存按单卡 32 GB 限制核对，包含 MTP 等辅助模型。** llama.cpp 的实际占用受权重、
上下文与运行参数影响，不能套用其他后端的预分配比例。2026-10-30 已核对 HIP + MTP3
现有服务的快照：可见设备为 `renderD128/card1`、PCI `0000:03:00.0`；
sysfs 总容量 51,522,830,336 字节（47.984 GiB），瞬时已用 30,044,221,440 字节
（27.981 GiB）；主模型进程（含 MTP）的 `drm-total-vram` 为 25,288,804 KiB
（24.117 GiB）。设备读数包含本流程未使用但仍常驻的 planner 和 embedding，
不能扣除它们后声称整卡占用更低。设备容量也不改变赛事的单卡 32 GB 限制。
这些瞬时读数不是请求期或启动期峰值；32 GB 限制、峰值、冷启动及容器重建仍未完成验收。
投题健康接口的 `vram_gb=0` 也不代表没有显存占用，须独立测量。

**绑 `127.0.0.1`，不是 `0.0.0.0`。** Radeon Cloud 的 `rc-tunnel` 只接管绑在环回口上的
HTTP 服务，绑 `0.0.0.0` 平台不接管。绑错了服务本身是活的，但外面永远打不进来，在赛事方
那边看起来和挂掉没有区别，而失败不重投。

**只暴露 7860 一个端口。** 平台限制一个 notebook 同时只能暴露一个端口。llama.cpp 的 8010
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
