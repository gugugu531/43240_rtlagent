# MODEL.md

本文件与 `manifest.json`、`REPORT.md` 第 3 节共同声明当前默认部署。
以下当前运行事实取自 **2026-10-30 实例 31563** 的权重、进程、服务版本和显存采样，
公开来源核对也截至该日；不代表正式评测成绩、持续负载测量或其他同名模型实例。

## 1. 模型

| 项 | 内容 |
| --- | --- |
| 基座模型名称 | `Qwen/Qwen3.8-27B` |
| 基座来源 | https://huggingface.co/Qwen/Qwen3.8-27B |
| 实际量化权重来源 | https://huggingface.co/Abiray/Qwen3.8-27B-Q4_K_M-GGUF |
| 固定 revision | `f7a1cda580fe828415151042bf9f3dc5bb8b0d76` |
| 权重文件 | `Qwen3.8-27B-Q4_K_M.gguf` |
| 文件大小 | 16,810,714,400 bytes |
| 权重 SHA256 | `6a96cc760fc65cc6b9ea7f1922e3ff8b2a48c09f209456f23bbae9ef7032c867` |
| 参数量 | 27,320,697,856，约 27.32B |
| 许可证 | Apache-2.0（公开量化仓库声明 `apache-2.0`） |
| 服务模型别名 | `qwen38-27b-q4-k-m` |

固定版本的完整公开下载 URL：

https://huggingface.co/Abiray/Qwen3.8-27B-Q4_K_M-GGUF/resolve/f7a1cda580fe828415151042bf9f3dc5bb8b0d76/Qwen3.8-27B-Q4_K_M.gguf

实例 31563 实际加载文件为 `/root/models/qwen38-27b/Qwen3.8-27B-Q4_K_M.gguf`；
2026-10-30 对该文件实读计算的 SHA256 与上述固定 revision 的 Hugging Face LFS 哈希一致。
仅加载文本 GGUF，未加载多模态投影文件（mmproj）。权重须提前准备，正式断网运行时不下载，
不调用商用模型 API。仓库通用默认路径为 `/models/Qwen3.8-27B-Q4_K_M.gguf`，可用 `MODEL` 覆盖；
实例上的实际路径不是其他部署必须使用的路径。

## 2. 量化与显存

| 项 | 内容 |
| --- | --- |
| 量化格式 | GGUF Q4_K_M |
| 量化工具与版本 | 未核实；不能由当前推理后端版本反推量化工具版本 |
| 采样日期与实例 | 2026-10-30，实例 31563，服务已加载后的瞬时值 |
| 测量硬件与可见设备 | W7900 环境；可见 `/dev/dri/renderD131`、`/dev/dri/card4`，PCI `0000:63:00.0` |
| 设备总显存 | 47.984 GiB |
| 设备已用显存 | 22.457 GiB，sysfs 瞬时采样，包含已有 embedding 进程及其他设备开销 |
| 主模型进程显存 | 19.590 GiB，进程采样 |
| 已有 embedding 进程显存 | 2.412 GiB，进程采样；未参与默认求解流程 |
| 运行峰值显存 | 未测量 |

GiB 按 2^30 bytes 计。上述数值不是稳态或全程峰值，也不保证进程采样与设备采样完全同步；
不能用两项进程值之和替代设备总占用。`manifest.json` 的 `measured_vram_gb` 为 22.457，
其 `vram_measurement` 明确采用 GiB 及上述瞬时边界。health 接口中的显存 0 不作为测量证据。

赛事上限为单卡 32 GB，包含辅助模型和运行开销；不能按 W7900 的物理容量放宽预算。
当前采样不能代替正式负载下的峰值验收，也不是官方成绩。

## 3. 上下文与正式默认流程

| 项 | 值 |
| --- | --- |
| 服务上下文 `--ctx-size` / 配置 `max_model_len` | 65536 |
| 默认单次输出上限 | 16384 token |
| temperature / top_p | 0.0 / 1.0 |
| 单题时限 / 请求超时 | 900 / 840 秒 |
| 共享思考设置 | `manifest.json` 的 `generation.chat_template_kwargs.enable_thinking=true`，baseline 与方案共用 |
| 服务思考预算 | `--reasoning-budget -1` |
| 额外 RoPE 覆盖 | 无 |
| MTP / draft 模型 | 未加载，实际命令没有 draft 参数 |

`run.sh` 默认使用 `config/single_generate.yaml`，一次生成，不使用 Skill、RAG、工具或辅助模型。
`baseline.py`、`run_baseline.sh` 保持不变；基线与默认方案使用同一服务、权重、量化、上下文及
上述生成设置。此处声明配置一致，不代表已完成同批次正式基线与方案评测。
`LLM_BACKEND=mock` 仅用于显式选择假模型，不是默认真实服务，也不产生真实模型成绩。

`guided_verify` 和 RAG 配置仍是通过 `AGENT_CONFIG` 显式选择的研究配置，不能据其存在推断
正式默认流程启用了小模型、知识库或额外工具。辅助模型边界见第 6 节。

### 历史开发记录（不属于当前部署）

2026-10-28 云端开发验证（非正式成绩）：远端 llama.cpp
`Qwen3.8-27B-Q4_K_M` + MTP，`single_generate` 约 9.6 秒，但本次输出 `xvlog` 失败。
当时本文件与 manifest 仍声明示例模型 Qwen3-8B，因此当时记录指出该 27B 与声明不同。
该旧 A 机的同名 27B 使用不同权重，不是本文件 2026-10-30 实例 31563 的权重；
不将旧实验耗时、MTP 配置或失败结果归入当前部署，也不作为正式能力或成绩声明。

## 4. 推理栈与复现

| 项 | 内容 |
| --- | --- |
| 后端 | llama.cpp，OpenAI 兼容 API |
| 实测版本 | `0.4.0-dev (build 1, commit f114f91)`，Clang 23，Linux |
| 实例二进制 | `/opt/llamacpp/llama-server` |
| 二进制 SHA256 | `290708d22f8b495d36b8aedd0afb0cdc081c415548f855e6a950a75dd742ad97` |
| 常驻服务入口 | `./serve/start.sh` |
| 地址 | `http://127.0.0.1:8010/v1` |
| 并发 | 单服务，`--parallel 1` |

2026-10-30 实例 31563 的实际启动命令：

```bash
/opt/llamacpp/llama-server \
  -m /root/models/qwen38-27b/Qwen3.8-27B-Q4_K_M.gguf \
  --alias qwen38-27b-q4-k-m --host 127.0.0.1 --port 8010 \
  --ctx-size 65536 --parallel 1 --n-gpu-layers all \
  --threads 16 --threads-batch 16 --flash-attn on \
  --no-webui --metrics --reasoning-budget -1
```

通用复现入口如下，工作目录为方案仓库 `43240_rtlagent/`；先准备上述权重与匹配二进制。
`LLAMA_SERVER` 默认从 `PATH` 查找 `llama-server`，需要选择固定二进制时显式设置绝对路径。
以下命令用于复现，不表示已在其他机器执行或重启实例 31563：

```bash
export MODEL=/models/Qwen3.8-27B-Q4_K_M.gguf
export MODEL_NAME=qwen38-27b-q4-k-m LLM_MODEL=qwen38-27b-q4-k-m
export PORT=8010 MAX_LEN=65536
export LLM_BACKEND=openai LLM_BASE_URL=http://127.0.0.1:8010/v1
# 若二进制不在 PATH 中，显式指定实际安装路径：
# export LLAMA_SERVER=/absolute/path/to/llama-server
./serve/start.sh
```

`MODEL_NAME`、`LLM_MODEL` 与服务 `--alias` 必须一致。`MAX_LEN` 是服务上下文长度，
不是单次输出上限。旧 vLLM 显存比例配置不是本次 llama.cpp 实际启动参数。

## 5. 微调与来源边界

当前加载的是第 1 节公开固定 revision 的量化权重，未声明另行微调权重。
公开量化仓库将 `Qwen/Qwen3.8-27B` 列为 `base_model`；本次权重与运行核对不等于训练数据审计。
发布方量化工具版本、完整训练数据与训练过程未核实，不据文件名或服务版本补填训练声明。
`REPORT.md` 的公开数据与训练来源仍保留待核实项。

## 6. 辅助模型与研究配置

正式默认 `single_generate` 不使用辅助模型；`manifest.json` 的 `auxiliary_models`、
正式 agent 的 `tools` 与 `skills` 均为空列表。实例 31563 已有常驻 embedding 进程，
但未参与本流程；其 2026-10-30 瞬时显存 2.412 GiB 已包含在第 2 节设备总占用中，
不能因未参与求解而从设备采样中扣除。

仓库保留的 `guided_verify`、小模型 profile 和 RAG 是显式研究配置，不是当前默认部署：

- `small` 规划 profile 的研究候选为
  `Nellyw888/VeriReason-Qwen2.5-1.5b-RTLCoder-Verilog-GRPO-reasoning-tb`，
  旧记录 revision 为 `a171280d7f001fef819e90218e008a887f1292c7`，
  基座 `Qwen/Qwen2.5-Coder-1.5B-Instruct`，约 1.54B，规划用途；
  配置中的独立服务端口为 8011，`serve/start.sh` 默认不启动该服务，只有显式设置 `VERI_GGUF` 才启动。
  这些是既有研究记录，不是 2026-10-30 对该候选的重新验证或正式运行声明。
- 该候选既有记录的许可证为空（`license: null`），flat plan 格式与运行显存未完成验证。
  公开 safetensors 约 6.2 GB（F32）只是旧文件大小记录，不是运行显存。
  未补全许可、来源、权重和合计资源验证并更新正式 manifest 前，不得作为正式组件。
- RAG 卡片与 `config/rag_embedding.yaml` 仅用于显式研究路线。当前不以常驻 embedding
  进程或配置文件的存在宣称正式使用检索，也不将研究配置结果作为默认方案结果。

若后续采用辅助模型，须另行声明名称、基座、参数量、用途、运行位置、显存及训练来源，
并验证主模型、辅助模型和运行开销合计符合单卡限制。

## 7. 声明与未完成验证

- 当前权重的公开固定版本、文件字节数与实读 SHA256 已按 2026-10-30 实例 31563 核对。
- 模型与服务声明对应当前默认配置；不把同名旧权重、研究配置或 mock 当作当前运行证据。
- 尚未完成正式负载峰值显存测量、同批次基线对照与官方评分；瞬时采样不替代这些验收。
- 量化工具版本及发布方完整训练来源未核实；未完成项不填作已验证。
