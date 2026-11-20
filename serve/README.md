# 推理服务与投题接口

推理服务和投题接口运行在同一实例的不同进程中，共用设备资源。下文的默认配置对应当前三角色实现。Radeon Cloud 部署和实测记录对应 2026-10-31 的方案 `1615689`。投题字段依据[主办方接口契约固定版本 fc8e26a](https://gitee.com/Vickyiii/rtlagent2026/blob/fc8e26a/docs/API_CONTRACT.md)。

```
  8000   llamacpp.sh    推理服务   监听 127.0.0.1，仅供本机调用
  7860   serve_api.py   投题接口   监听 127.0.0.1，经 rc-tunnel 对外提供服务
```

---

## 开发期：不需要 GPU

在方案仓库根目录运行：

```bash
AGENT_CONFIG=config/single_generate.yaml LLM_BACKEND=mock \
  ./run.sh /absolute/path/to/task /var/tmp/rtl-mock-output
```

输入目录应包含公开题面 `prompt.txt`，输出目录每次使用新路径。此命令用假模型（mock）检查生成入口和日志，无需 Vivado；它不验证默认 `guided_verify` 的行为检查。假模型只返回占位 RTL（寄存器传输级代码），不代表功能正确。默认 `run.sh`、`agent/config.py` 和 HTTP 服务均使用 `config/guided_verify.yaml`，RAG（检索增强生成）关闭。
`single_generate` 与 RAG 研究路线通过显式 `AGENT_CONFIG` 选择。
方案内的模型请求经过 `agent/llm/client.py`。默认 `guided_verify` 通过 llama.cpp 的 `/apply-template` 和 `/tokenize` 核算上下文余量。`single_generate` 的默认基线节点跳过这一步，改用 `rtl_generate` 的研究预设则按配置分词。HTTP 的 `mode=baseline` 另行调用主办方的 `run_baseline.sh`。
当前 `guided_verify` 预设设置 `services.model.structured_outputs: false`。规划、检查表、逐点复核和解题决策的行式回复由框架按各自语法解析。

## 实时工作台

在本方案目录运行以下命令。已启动的 API 可直接使用 `ui on`。观众用浏览器打开同一个监听地址上的 `/ui`，例如本机的 [实时工作台](http://127.0.0.1:7860/ui)。

```bash
./serve/run_api.sh start
./serve/run_api.sh ui on
./serve/run_api.sh ui status
./serve/run_api.sh ui off
```

页面开启后，能访问该地址的人均可免登录查看两种题源的题面全文、各版 RTL、检查点说明、实测结果、决策理由和最终交付。赛事投题与本地选题使用同一套展示规则。角色正在生成时显示当前步骤和耗时，回复返回后展示新内容。实际执行图为每次重访单独绘制节点；工作流定义视图显示可能发生的转移。选中节点可展开这一次执行的记录。[事件接口与新工作流示例](../docs/live-events.md)

首次启动、已配置赛事令牌时，默认关闭页面并接受赛事投题。需要现场选题时，在**启动 API 前**设置题库和独立演示口令。口令用 Bash 隐藏输入，两个变量都要导出。下面的目录改为存放公开题面的绝对路径，各题目录下有 `prompt.txt`。

```bash
export RTLAGENT_UI_TASKS=/absolute/path/to/public-tasks
read -rs -p '请输入独立的演示者口令 ' RTLAGENT_UI_OPERATOR_TOKEN
export RTLAGENT_UI_OPERATOR_TOKEN
./serve/run_api.sh start
./serve/run_api.sh mode local
./serve/run_api.sh ui on
```

观众可以预览题目。演示者输入独立口令后才能开始求解。口令必须与赛事令牌不同。只做本地演示时，上述两个变量即可启动；首次未配置赛事令牌则进入选题模式。本机模拟可以在启动前另设 `LLM_BACKEND=mock`。正式投题入口只使用符合赛事要求的本机模型服务。

| 命令 | 运行效果 |
| --- | --- |
| `mode local` | 接受页面选题。带有效赛事令牌的新投题和就绪探测返回 HTTP 503。已有赛事作业仍可按编号查询。 |
| `mode submission` | 接受赛事投题，关闭页面选题入口。进入该模式需要赛事令牌。 |
| `ui on`、`ui off` | 立即开关页面及其数据接口。当前求解和投题 API 继续运行。 |
| `ui status` | 显示页面、题源和队列忙闲状态。 |

队列空闲时可切换题源。命令须在 API 所在主机以运行服务的用户执行，使用相同的 `AGENT_TMP` 和 `API_PORT`。监听地址为 `127.0.0.1`，`API_PORT` 默认 7860。页面与投题接口共用这个端口，开启页面后仍需单独建立隧道才能从公网访问。

页面自动跟随当前题，结束后停留在结果。刷新会重新读取该题事件，手动查看最近的题目可暂停跟随。内存保留正在处理的题目和最近两道已结束题的展示记录。API 重启后清空运行记录并关闭页面，同一临时目录和端口会恢复上一次选择的题源。基线入口沿用主办方脚本，可以查看题面、作业状态与交付源码。基线和未产生结束事件的中断任务只显示已有证据。

## 对外运行记录（trace）字段

投题 API 在返回结果时为 agent 与 baseline 的每条 trace 对象补齐 `ts`、`tool`、
`rc`、`excerpt`、`tokens_in`、`tokens_out`。已有字段和值原样保留；缺失的时间、
工具名、返回码或用量使用 `null`，缺失摘要使用空字符串，不将未知解释为零或成功。
例如官方 baseline 的元信息没有事件时间，其 `ts` 保持未知；不以返回时间冒充生成时间。
原始 `trace.jsonl` 和官方 baseline 文件不修改。无效 JSON 或非对象行返回显式
`api/invalid_trace_line` 诊断并保留 `raw_line`，该诊断时间是 API 发现错误的时间。
这项补齐仅用于 HTTP 响应，不改变独立 `run_baseline.sh` 的官方输出格式。

## 正式推理配置

正式路线使用 llama.cpp HIP（AMD GPU 计算后端），加载 GGUF 格式的文本模型权重，并启用 MTP（多 token 预测）头。每次最多预测 3 个 token，简称 MTP3。基座模型为 [Qwen/Qwen3.8-27B](https://huggingface.co/Qwen/Qwen3.8-27B)，
两份权重均来自 [ggml-org/Qwen3.8-27B-GGUF 固定版本](https://huggingface.co/ggml-org/Qwen3.8-27B-GGUF/tree/a316ea527fde32c12487be7574e2db5ac2ad2a7e)
（revision `a316ea527fde32c12487be7574e2db5ac2ad2a7e`）：

| 用途 | 文件 | 字节数 | SHA256 |
| --- | --- | ---: | --- |
| 主模型 | `Qwen3.8-27B-Q4_K_M.gguf` | 18,973,870,528 | `c600de0300ae8a0eb3a6c0b8b5561b8b96f16bd2c863c2a66c42de29d391a747` |
| MTP（多 token 预测）头 | `mtp-Qwen3.8-27B-Q4_0.gguf` | 1,680,271,776 | `c5be331f82fb61f5304adfa00ccd60c6743c8ce52255d66fa863446231d49ba4` |

2026-10-30 已读取两份实际文件，计算哈希并与公开来源核对。只加载文本权重，不加载多模态投影文件（mmproj）；
MTP 头直接生成推测 token，作为两模式共享的推理栈记入 `serving.speculative_decoding.draft_model`；
独立规划、文本向量（embedding）等智能体专用辅助模型另记 `auxiliary_models`。所有实际显存必须计入。
模型声明见 [MODEL.md](../model/MODEL.md)。
2026-10-30 已核对现有服务实际运行 HIP + MTP3，后端为 `llama-server 0.4.0-dev`
（build 1，源码 commit `f114f91f9ed6792cf402437e3874adad98902744`），
二进制 SHA256 为 `290708d22f8b495d36b8aedd0afb0cdc081c415548f855e6a950a75dd742ad97`。
实际加载 HIP、amdhip、hipblas 和 rocblas 运行库。换编译产物或运行库后须重新核对兼容性，
不能只依据版本字符串认定相同；脚本不编译后端，也不自动识别或选择 GPU 后端。

### 复用已有服务

以下命令均从方案仓库根目录运行。先人工核对已有服务的两份模型文件、哈希、版本及
实际启动参数与声明一致，不要仅凭模型别名（alias）判断权重；并检查 `/slots` 的
`speculative=true`，确认启用推测解码。`start.sh` 检查本机对应端口的 `/health` 和 `/v1/models` 中的模型别名；
已健康时复用，不会重复加载主模型，也不会替换、重启已有服务。
`/health` 成功不证明 HIP、权重或 MTP3 参数已匹配，不能跳过上述人工核对。

```bash
export LLM_BACKEND=openai LLM_BASE_URL=http://127.0.0.1:8000/v1
export LLM_API_KEY=dummy
export MODEL_NAME=qwen38-27b-q4-k-m LLM_MODEL=qwen38-27b-q4-k-m
PORT=8000 ./serve/start.sh
```

### 没有现有服务时启动

断网前从上述固定版本下载两份 GGUF，按表中大小与 SHA256 核对；在本地准备适用于
目标 AMD GPU、支持 `draft-mtp` 的 HIP 构建 `llama-server`，以及匹配的
HIP/amdhip、hipblas、rocblas 等运行库。权重和二进制不随方案提交，脚本不会下载。
默认使用官方镜像的 `/opt/llamacpp/llama-server`，主权重默认在 `/models/Qwen3.8-27B-Q4_K_M.gguf`，
MTP 权重默认在 `/models/mtp-Qwen3.8-27B-Q4_0.gguf`；可通过环境变量显式指定：

```bash
export LLM_BACKEND=openai LLM_BASE_URL=http://127.0.0.1:8000/v1
export LLM_API_KEY=dummy
export MODEL_NAME=qwen38-27b-q4-k-m LLM_MODEL=qwen38-27b-q4-k-m
MODEL=/local/models/Qwen3.8-27B-Q4_K_M.gguf \
MTP_MODEL=/local/models/mtp-Qwen3.8-27B-Q4_0.gguf \
LLAMA_SERVER=/local/bin/llama-server ./serve/start.sh
```

`/local` 是示例准备位置，须换为实际路径。任一权重缺失或不可读、找不到二进制时明确失败，不自动降级为无 MTP。
主模型日志在 `${SERVE_LOG_DIR:-${AGENT_TMP:-/var/tmp}/serve-logs}/llamacpp.log`；
就绪等待默认 `START_TIMEOUT_S=900`。启动使用 `setsid`，保持原有临时目录清理；只启动主模型及同进程 MTP，不因设置 `VERI_GGUF` 自动启动小模型。

`llamacpp.sh` 默认参数：`PORT=8000`、`MAX_LEN=65536`、`PARALLEL=1`、
`N_GPU_LAYERS=all`、`THREADS=16`、`THREADS_BATCH=16`、`FLASH_ATTN=on`、
`REASONING_BUDGET=6144`，固定绑定 `127.0.0.1` 并启用 `--jinja --no-webui --metrics`。
官方 FAQ Q7 要求 `--jinja`，否则请求中的思考设置可能不生效；若未显式设置
`ROCBLAS_TENSILE_LIBPATH`，脚本使用所选二进制旁的 `rocblas/library`（存在时）。
固定使用 `--cpu-strict 1`、FP16（16 位浮点）KV cache（注意力键值缓存，`--cache-type-k f16 --cache-type-v f16`），
以及 MTP3 参数 `--spec-type draft-mtp --model-draft "$MTP_MODEL" --spec-draft-ngl all --spec-draft-n-max 3`。
不覆盖 RoPE（旋转位置编码）设置，也不指定额外的 CPU 亲和性掩码。
覆盖端口时也要同步 `LLM_BASE_URL`；覆盖 `MODEL_NAME` 时同步 `LLM_MODEL`；
改变模型或服务参数须同步模型声明。
默认 `guided_verify` 与 baseline 共用此服务和 manifest 思考设置（`enable_thinking=true`、`reasoning_effort=medium`）。
策略、解题和独立检查三个角色共用端口 8000 的 Qwen3.8-27B。每次调用重建消息。策略角色选路线和技能。解题角色会在决策时看到当前 RTL、该稿的检查结果和此前决定的摘要。检查角色依据公开规格建表、解释测试点，并按请求复核指定点。角色隔离发生在消息上下文，服务进程和设备显存共享。MTP 预测头计入设备总显存。

默认单次请求上限为策略规划 90 秒 / 4096 token，首稿、结构修复和解题决策 300 秒 / 16384 token，检查表构造、格式修正和逐点复核 180 秒 / 8192 token。各角色共用单题 900 秒（含 60 秒收尾预留）、8 次实际生成调用和 65536 个输出 token。剩余时间、输出额度和上下文空间还会限制具体请求。

首稿或首次建表只返回空正文且终止原因为 `stop` 或 `length` 时，框架可在共享预算内恢复。用量未知会阻止可选恢复，尚未确认结束的生成调用会阻止后续生成。对重复且无进展的恢复，程序记录原因并退出恢复循环。[完整流程](../docs/guided-verify.md)

Dockerfile 不复制权重或开发区；使用固定官方镜像内 `/opt/llamacpp` 的 HIP 后端和配套 rocBLAS 库，
构建时检查这两项存在，再挂载提前准备的两份本地权重。自定义后端须在构建阶段准备并同步版本声明。
`1615689` 在 2026-10-31 完成了自编 AND/OR 两题的真实投题和独立判定；当前版本的容器重建、连续稳定性和完整题集对照仍未完成，详见 [REPORT.md](../REPORT.md)。
启动成功和单题响应不能代替官方评分。实例重启后须按下节恢复环境和隧道。

## Radeon Cloud 环境与启动顺序

以下命令对应 2026-10-31 已记录部署的目录约定，从方案仓库根目录执行。镜像已提供 Vivado、HIP 后端；Python 环境须在断网前安装
`requirements.txt`。该次部署使用 `/workspace/rtlagent/venv`，其他实例可换为自己的环境。
方案仓库直接克隆到 `/workspace/43240_rtlagent`，从该目录执行下列命令；不依赖嵌套的历史部署目录。
令牌及授权变量保存在持久盘 `/workspace/env.sh`，不得提交到仓库，也不要用覆盖写法丢失已有令牌。

```bash
cd /workspace/43240_rtlagent
source /workspace/env.sh
source /tools/Xilinx/setup.sh
export PATH="/workspace/rtlagent/venv/bin:$PATH"
export XILINXD_LICENSE_FILE="${XILINXD_LICENSE_FILE:-2100@vivado-lic.fpgachina.svc.cluster.local}"
export FLEXLM_TIMEOUT="${FLEXLM_TIMEOUT:-300000000}"
export AGENT_TMP=/var/tmp EDA_TMP=/var/tmp/eda SELFTEST_TMP=/var/tmp
export MODEL=/workspace/models/Qwen3.8-27B-Q4_K_M.gguf
export MTP_MODEL=/workspace/models/mtp-Qwen3.8-27B-Q4_0.gguf
./serve/start.sh
./serve/run_api.sh start
curl --noproxy '*' -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:7860/v1/health
# 未携带令牌应为 401，确认后再用 rc-tunnel expose 建立隧道。
```

仓库默认模型端口为 8000，默认工作流为 `guided_verify`，关闭 RAG，思考强度为 `medium`，无需依赖旧发布目录的
`AGENT_CONFIG` 或 `LLM_BASE_URL` 覆盖。若当前 shell 保留旧研究变量，应先移除对应覆盖再启动。
容器重建模式的权重挂载仍为 `/models`，不需要这些实例专用权重路径。

## 启动投题接口

先在受保护的运行环境中提供 `FPGACHINA_TOKEN`。已有该变量时直接启动；需要手工输入时可在 Bash 中使用以下命令，避免把令牌写入命令历史：

```bash
read -r -s -p '请输入赛事令牌：' FPGACHINA_TOKEN
export FPGACHINA_TOKEN
export MODEL_NAME=qwen38-27b-q4-k-m
./serve/run_api.sh start        # 后台运行，进程退出后等待 2 秒重启

# 建立公网隧道；平台只转发监听 127.0.0.1 的 HTTP 服务
/var/run/secrets/frp-self-service/install
env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
    "$HOME/.local/bin/rc-tunnel" expose --port 7860
```

`env -u` 让隧道客户端直接连接平台隧道服务器，避免使用实例的出网代理。

查看状态用 `./serve/run_api.sh status`，停止用 `./serve/run_api.sh stop`。
默认端口的日志在 `${AGENT_TMP:-/var/tmp}/run_api/serve_api.log`，其他端口使用 `run_api-<端口>/serve_api.log`。云端使用本地磁盘上的 `AGENT_TMP`。
先确认无令牌访问 `curl --noproxy '*' http://127.0.0.1:7860/v1/health` 返回 401，再建立隧道。
平台约 1 分钟探测不到服务就会收回隧道，恢复服务不能恢复旧网址，须重新 expose 并报送。
实例重启后须恢复环境与依赖、启动推理和投题服务、重新安装 rc-tunnel 并建立隧道。
守护脚本只重启退出的 API 进程，不检测卡死、不恢复进行中的任务，也不自动重建隧道。

自测：

```bash
curl --noproxy '*' -H "Authorization: Bearer $FPGACHINA_TOKEN" http://127.0.0.1:7860/v1/health
# 核对 ready、track="rtl" 和 model="Qwen/Qwen3.8-27B"；vram_gb 不是峰值测量。

# 将 prompt 替换为完整公开题面；返回 job_id 后查询任务状态
curl --noproxy '*' -X POST -H "Authorization: Bearer $FPGACHINA_TOKEN" -H "Content-Type: application/json" \
     -d '{"task_id":"t1","nonce":"n1","mode":"agent","prompt":"...","interface":"","deadline_s":900}' \
     http://127.0.0.1:7860/v1/solve
JOB_ID='替换为返回的任务编号'
curl --noproxy '*' -H "Authorization: Bearer $FPGACHINA_TOKEN" "http://127.0.0.1:7860/v1/jobs/$JOB_ID"
```

`track` 必须是 `"rtl"`，赛事方投题前会核对，不符即拒投。

正式 HTTP 启动从同一份有效 YAML/环境配置解析模型地址，并把同一个地址和模型别名传给
agent 与 baseline 子进程；仅接受本机回环地址的 HTTP 服务。命令行开发仍可显式使用假模型或其他后端。
两种 HTTP 模式均显式传入 `TRACK=rtl`，不继承运行环境中残留的其他赛道设置；官方 baseline 文件保持原样。
健康检查不运行解题；模型、入口、配置或实测显存不可用时返回 503。`mode` 仅接受 `agent`、`baseline`，
`deadline_s` 必须为正整数，排队时间计入两模式共同的时限；同一服务进程内使用相同的非空 `nonce`（请求去重标识）会返回同一任务。
API 守护脚本启动前检查依赖，并确认子进程在启动观察期内存活；随后仍须验证携带令牌的健康检查。任务状态 `done` 表示运行结束，不代表答案正确。

---

## 运行注意事项

**显存按单卡 32 GB 限制核对，包含 MTP 等辅助模型。** llama.cpp 的实际占用受权重、
上下文与运行参数影响，不能套用其他后端的预分配比例。2026-10-30 部署的显存快照见 [MODEL.md](../model/MODEL.md)；包含主模型、MTP 和设备其他开销，
不能将历史实例的常驻小模型视为当前依赖。瞬时读数不证明正式负载峰值符合限制。
投题健康接口读取可见 AMD 设备的 sysfs 字节数，按 GiB 报告；测量未知、模型未就绪、
别名与声明不一致或图无法装配时返回 503，不伪报零显存或 ready。这仍不替代峰值与权重核验。

**监听地址使用 `127.0.0.1`。** 根据上述固定版本接口契约，Radeon Cloud 的 `rc-tunnel` 只转发本机回环地址上的 HTTP 服务。监听 `0.0.0.0` 时，即使服务已启动，也无法通过平台隧道访问。

**只对外发布 7860 端口。** 平台限制一个 notebook 实例同时只能发布一个端口。llama.cpp 的 8000
由智能体经 `127.0.0.1` 内部调用。同时参加两个赛道时，按接口契约分别准备两台虚拟机。

**令牌检查不是可选项。** 平台给出的公网 app URL 不带业务层鉴权，没有令牌检查，任何人
拿到网址都能投题。

**中间文件写入本地磁盘。** HTTP 的 `AGENT_TMP` 和启动日志默认 `/var/tmp`；已记录实例上的 `/tmp` 是 4 GB 内存盘，其他入口也应显式使用 `/var/tmp`。云平台的 `/workspace` 是 NFS（网络文件系统），
适合保存持久文件；Vivado 产生大量小文件，临时工作目录使用本地磁盘，避免网络存储的访问开销。

**持续运行需要单独验证。** 服务应能连续处理数百次请求，并在每题后清理临时目录与子进程，避免磁盘或进程资源耗尽。正式评测中的请求失败不会自动重投；已有小题测试不能证明连续稳定性。

**投题是异步的。** `POST /v1/solve` 立即返回任务编号，题在后台解，赛事方每 2 秒查询一次。
平台入口会切断 60 秒内没有响应的请求，所以自己改写投题服务时，不能让请求挂着等解题完成。

**预留超时收尾时间。** `serve_api.py` 从总时限中扣除排队时间后，提前 10 秒向单题整个进程组发送 SIGTERM（终止信号），再给 5 秒收尾时间；仍未结束时发送 SIGKILL（强制结束信号），最后读取已保存答案。按进程组结束可避免智能体或 Vivado 子进程继续占用下一题的资源。若排队已用尽时限，接口直接返回空答案。默认三角色流程中，未显式提交就中断时，优先交付最近同时通过 lint 和 synth 的完整稿，其次是最近的完整稿，没有完整稿则为空。行为检查覆盖情况另查该稿记录。

**常驻进程统一由 `start.sh` 启动。** 推理服务与队伍自己的常驻引擎都在 `start.sh` 中使用
`setsid` 创建独立会话。采用备用的容器重建方式时，赛事方先运行 `start.sh`，再逐题调用 `run.sh`，不启动
`serve_api.py`；超时信号发给 `run.sh` 的进程组，由 `run.sh` 在后台带起的常驻进程会随之
被结束。因此常驻进程必须由 `start.sh` 用 `setsid` 启动，不能与单题进程组共享会话。

**回收已结束的子进程。** 按接口契约描述，平台实例的 1 号进程是 JupyterLab，不负责回收被其接管的孤儿进程。已结束却未回收的进程会成为僵尸进程，占用进程表资源。`serve_api.py` 启动时把自己设为子进程回收者
（`PR_SET_CHILD_SUBREAPER`），每题结束后回收该题的全部进程。换成自己的服务时这一段
要保留。

---

## W7900（gfx1100）上的已知问题

初赛与决赛均使用 W7900，显存仍按单卡 32 GB 限制，包含辅助模型。
该架构没有 FP8 矩阵指令；FP8 量化不能据此认定有吞吐加速，须以实测为准。
`Dockerfile` 已固定主办方镜像摘要。镜像仅平台内部可访问，实例无 Docker；
队伍无需在实例构建，赛事方在备用重建方式下使用它，安装步骤须与实例实际操作一致。

## 可选小模型（8011）

默认 `guided_verify.yaml` 已关闭 `small` 模型配置，规划使用端口 8000 的 Qwen3.8-27B。
`guided_verify_rag_bm25.yaml`、`guided_verify_rag_dense.yaml` 仍保留 8011 小模型研究配置。
`serve/start.sh` 不启动它，即使已设置 `VERI_GGUF`；研究需要时显式运行：

```bash
VERI_GGUF=/models/verireason-1.5b-f16.gguf ./serve/start_verireason.sh
```

该脚本通过端口上的 `/v1/models` 是否响应判断是否需要启动。已有响应时直接返回，模型别名需另行核对。需要新启动时，缺少可执行的 `llama-server` 或 GGUF 会报错。启动小模型不自动改变求解配置，研究时还需显式选择对应配置。
`guided_verify_large_v3.yaml` 保留主模型规划的研究预设。小模型仍未完成正式辅助模型声明及资源验收。
稠密向量 RAG 路线使用 `serve/embedding_service.py`，模型别名和维度来自
`config/rag_embedding.yaml`。
