# 模型与推理服务声明

本文件与 `manifest.json`、`REPORT.md` 第 3 节共同声明当前默认配置。
规则按主办方固定版本 [`fc8e26a`](https://gitee.com/Vickyiii/rtlagent2026/tree/fc8e26a/)（2026-10-30 核对）。
第 3 节列出当前三角色工作流的配置。权重与后端信息依据 **2026-10-30 的 Radeon Cloud 实例核查记录**，当时读取了两份实际权重及后端二进制并计算 SHA256 校验值。
推理后端采用 **llama.cpp HIP**（AMD GPU 计算后端），启用 MTP（多 token 预测）头，每次最多预测 3 个 token，下文简称 MTP3。推理端口为 8000，投题端口为 7860。`1615689` 在 2026-10-31 完成了自编 AND/OR 两道小题的真实投题与独立判定，详见 [报告第 6 节](../REPORT.md#6-实测结果)；这不代表正式成绩或持续负载测量。

## 1. 模型

| 项 | 内容 |
| --- | --- |
| 基座模型名称 | `Qwen/Qwen3.8-27B` |
| 基座来源 | [Qwen/Qwen3.8-27B](https://huggingface.co/Qwen/Qwen3.8-27B) |
| 实际量化权重来源 | [ggml-org/Qwen3.8-27B-GGUF](https://huggingface.co/ggml-org/Qwen3.8-27B-GGUF) |
| 固定版本（revision） | `a316ea527fde32c12487be7574e2db5ac2ad2a7e` |
| 权重文件 | `Qwen3.8-27B-Q4_K_M.gguf` |
| 文件大小 | 18,973,870,528 bytes |
| 权重 SHA256 | `c600de0300ae8a0eb3a6c0b8b5561b8b96f16bd2c863c2a66c42de29d391a747` |
| 参数量 | 名称标示 27B；该 GGUF 的精确参数量未核实，不沿用旧 Abiray 权重的参数统计 |
| 许可证 | Apache-2.0（固定 revision 的公开模型卡声明 `apache-2.0`） |
| 服务模型别名 | `qwen38-27b-q4-k-m` |

下载：[固定版本主权重](https://huggingface.co/ggml-org/Qwen3.8-27B-GGUF/resolve/a316ea527fde32c12487be7574e2db5ac2ad2a7e/Qwen3.8-27B-Q4_K_M.gguf)。GGUF 是 llama.cpp 使用的模型文件格式，Q4_K_M 是本文件采用的量化类型。

核查时实例实际加载文件为 `/workspace/models/Qwen3.8-27B-Q4_K_M.gguf`；
2026-10-30 对主权重及第 6 节 MTP 权重计算的 SHA256 均与固定版本的
[Hugging Face 文件 API](https://huggingface.co/api/models/ggml-org/Qwen3.8-27B-GGUF/tree/a316ea527fde32c12487be7574e2db5ac2ad2a7e) 一致。
仅加载文本 GGUF，未加载多模态投影文件（mmproj）。权重须提前准备，正式断网运行时不下载，
不调用商用模型 API。仓库通用默认路径为 `/models/Qwen3.8-27B-Q4_K_M.gguf`，可用 `MODEL` 覆盖；
实例上的实际路径不是其他部署必须使用的路径。

## 2. 量化与显存

| 项 | 内容 |
| --- | --- |
| 主权重量化格式 | GGUF Q4_K_M；MTP 预测头为 GGUF Q4_0 |
| 量化工具与版本 | 模型卡称由 `ggml-org/convert` 自动转换；具体工具版本与量化命令未核实 |
| 采样日期与实例 | 2026-10-30，SSH 32535 实例，服务空闲时瞬时值 |
| 测量硬件与可见设备 | W7900 环境；可见 `/dev/dri/renderD128`、`/dev/dri/card1`，PCI `0000:03:00.0` |
| 设备总显存 | 51,522,830,336 bytes，47.984 GiB |
| 设备已用显存 | 25,415,020,544 bytes，23.67 GiB；包含主模型、MTP 及设备其他开销 |
| 主模型与 MTP 同进程显存 | `drm-total-vram` 24,566,664 KiB，23.429 GiB；未单独测量预测头占用 |
| 运行峰值显存 | 未测量 |

GiB 按 2^30 bytes 计，KiB 按 2^10 bytes 计。上述数值不是稳态或全程峰值，
也不保证进程采样与设备采样完全同步；不能扣除未参与求解的常驻进程。
`manifest.json` 的 `measured_vram_gb` 为 23.67，`vram_measurement` 明确采用
GiB，并注明这是单次采样。健康检查接口的运行时显存采样与本表历史采样分别记录；未取得有效采样不能用 0 代替。

赛事上限为单卡 32 GB，包含辅助模型和运行开销；不能按 W7900 的物理容量放宽预算。
当前采样不能代替正式负载下的峰值验收，也不是官方成绩。

## 3. 上下文与源码默认流程

| 项 | 值 |
| --- | --- |
| 服务上下文 `--ctx-size` / 配置 `max_model_len` | 65536 |
| `guided_verify` 单次请求输出上限 | 策略选择 4096、解题 16384、检查器 8192 token。总输出预算 65536 token |
| temperature / top_p | 0.0 / 1.0 |
| 单题时限 / 单次请求上限 | 900 秒含 60 秒收尾。策略选择 90 秒、解题 300 秒、检查器 180 秒。实际时限还受剩余预算约束 |
| 共享思考设置 | `manifest.json` 的 `generation.chat_template_kwargs` 中 `enable_thinking=true`、`reasoning_effort=medium`，baseline 与方案共用 |
| 服务思考预算 | `--reasoning-budget 6144` |
| RoPE（旋转位置编码）的额外设置 | 无 |
| KV cache（注意力键值缓存） | FP16（16 位浮点数） |
| MTP / draft 模型 | 同进程加载 Q4_0 MTP 预测头，`draft-mtp`，最多预测 3 token |

`run.sh` 与 HTTP 服务默认使用 `config/guided_verify.yaml`。策略、解题、检查三个角色均调用端口 8000 的 Qwen3.8-27B。各请求分别构造 `messages`。`small` 与 `large` 两个可选模型配置组均关闭，`retrieval_mode: off` 关闭 RAG（检索增强生成）知识卡片。

策略角色根据公开题面、接口和检查器能力，决定检查方式并选择求解技能。解题角色收到选中技能，生成和修复完整 RTL，并依据逐点检查结果决定是否提交、改稿或请求复核。下一轮收到的是当前稿及历轮的简短决定。检查角色根据公开规格构造带说明的测试点，复核时另收当前表和指定点编号。模型私有思考、候选 RTL 和实测输出都不会进入检查器请求。[工作流实现与上下文](../docs/guided-verify.md)

默认每题的 8 次调用只计生成请求，三个角色共用 65536 个输出 token。服务端的模型查询、模板展开和分词另行记录。复核、修复和格式纠正使用各自角色的单次上限。程序为所需后续步骤预留时间，按余额缩短请求时限，低于 `minimum_request_s` 和该阶段上限中的较短时间时记录未发送。默认 `minimum_request_s` 为 20 秒。2026-10-31 的三题恢复实验使用检查器 150 秒的旧候选，当日另有两道自编题使用 180 秒配置。11 月 18 日的三角色入口验收使用固定 HTTP 回复与真实 Vivado，真实模型收益仍待对照。[实验条件与结果](../REPORT.md#6-实测结果)
推理后端使用第 6 节声明的 MTP 预测头，不是独立求解模型。
基线与默认方案共用推理服务、权重、量化、上下文长度、采样温度、top_p 和 manifest 的思考设置。主办方基线每题生成一次，单次上限为 16384 个输出 token，生成请求超时为 840 秒。三角色版本与该基线的同批正式对照仍待验证。[主办方基线实现](../baseline.py)
`LLM_BACKEND=mock` 仅用于显式选择假模型，不是默认真实服务，也不产生真实模型成绩。

`AGENT_CONFIG` 可显式选择 `single_generate`、带 RAG 或小模型的配置。研究配置 `guided_verify_deadline_only.yaml` 共用 900 秒，额外预留时间为 0，生成次数和输出 token 总数均无单独上限，每次请求仍受模型上下文容量约束。辅助模型边界见第 6 节。[限时研究配置](../config/guided_verify_deadline_only.yaml)

### 历史开发记录（不属于当前部署）

2026-10-28 云端开发验证（非正式成绩）：远端 llama.cpp
`Qwen3.8-27B-Q4_K_M` + MTP，`single_generate` 约 9.6 秒，但本次输出 `xvlog` 失败。
当时本文件与 manifest 仍声明示例模型 Qwen3-8B，因此当时记录指出该 27B 与声明不同。
该历史记录不证明当前权重、运行性能或正式能力；本文件的权重声明以 2026-10-30 实例核查记录为准，
不将旧实验耗时或失败结果归入当前部署。实例 31563 的 Abiray 无 MTP 路线和旧公网测试
也仅属于旧验收历史，不作为所选 HIP + MTP3 路线的证明。

## 4. 推理栈与复现

| 项 | 内容 |
| --- | --- |
| 后端 | llama.cpp HIP，OpenAI 兼容 API；进程已加载 `libggml-hip`、`libamdhip`、hipBLAS、rocBLAS |
| 实测版本 | `0.4.0-dev (build 1, commit f114f91)`；完整源码 revision `f114f91f9ed6792cf402437e3874adad98902744` |
| 实例二进制 | `/opt/llamacpp/llama-server` |
| 二进制 SHA256 | `290708d22f8b495d36b8aedd0afb0cdc081c415548f855e6a950a75dd742ad97` |
| 常驻服务入口 | `./serve/start.sh` |
| 地址 | `http://127.0.0.1:8000/v1` |
| 并发 | 单服务，`--parallel 1` |

以下参数在 2026-10-30 的实例上核对，路径为当次实际安装位置。

```bash
/opt/llamacpp/llama-server \
  -m /workspace/models/Qwen3.8-27B-Q4_K_M.gguf \
  --alias qwen38-27b-q4-k-m --host 127.0.0.1 --port 8000 \
  --ctx-size 65536 --parallel 1 --n-gpu-layers all \
  --threads 16 --threads-batch 16 --cpu-strict 1 --flash-attn on \
  --cache-type-k f16 --cache-type-v f16 --jinja \
  --no-webui --metrics --reasoning-budget 6144 \
  --spec-type draft-mtp \
  --model-draft /workspace/models/mtp-Qwen3.8-27B-Q4_0.gguf \
  --spec-draft-ngl all --spec-draft-n-max 3
```

采样时推理槽位（slots）为空闲状态（`idle`），`speculative=true`；这不是吞吐、峰值或新版本发布验收。
通用复现入口如下，工作目录为方案仓库 `43240_rtlagent/`；先准备两份权重与匹配的 HIP 二进制。
`LLAMA_SERVER` 默认使用官方镜像 `/opt/llamacpp/llama-server`，需要选择其他固定二进制时显式设置绝对路径。
实例授权、Python 环境与投题启动顺序见 [服务说明](../serve/README.md)。

```bash
export MODEL=/models/Qwen3.8-27B-Q4_K_M.gguf
export MTP_MODEL=/models/mtp-Qwen3.8-27B-Q4_0.gguf
export MODEL_NAME=qwen38-27b-q4-k-m LLM_MODEL=qwen38-27b-q4-k-m
export PORT=8000 MAX_LEN=65536
export LLM_BACKEND=openai LLM_BASE_URL=http://127.0.0.1:8000/v1
# 使用其他安装位置时，显式指定二进制路径
# export LLAMA_SERVER=/absolute/path/to/llama-server
./serve/start.sh
```

`MODEL_NAME`、`LLM_MODEL` 与服务 `--alias` 必须一致。`MAX_LEN` 是服务上下文长度，
不是单次输出上限。旧 vLLM 显存比例配置不是本次 llama.cpp 实际启动参数。

## 5. 微调与来源边界

当前加载的是第 1 节公开固定 revision 的量化权重，未声明另行微调权重。
[固定版本模型卡](https://huggingface.co/ggml-org/Qwen3.8-27B-GGUF/blob/a316ea527fde32c12487be7574e2db5ac2ad2a7e/README.md)
将 `Qwen/Qwen3.8-27B` 列为 `base_model`，来源链接还列有 `incoai/Qwen3.8-27B-DFlash2`；
卡片没有逐文件说明该链接与本次两份 GGUF 的关系，不能据此断言使用 DFlash2。
本次权重与运行核对不等于训练数据审计；转换工具版本、完整训练数据与训练过程未核实。
`REPORT.md` 的公开数据与训练来源仍保留待核实项。

## 6. 辅助模型与研究配置

正式默认服务加载 MTP（多 token 预测）头，用于 MTP3 推测解码，不独立解题、规划或检索。
它与主模型在同一 `llama-server` 进程、同一 GPU 上运行，baseline 与方案共用；
`manifest.json` 的 `serving.speculative_decoding.draft_model` 声明该预测头，正式 agent 的工具和技能在 `agent` 字段列明，`auxiliary_models` 为空列表。

这里按 API 契约第 8 节的同一推理服务、同一配置，将直接生成推测 token 的 MTP 归入方案和 baseline 共享推理栈；SCORING 第 2.13 节的独立规划、判别和 embedding 等辅助模型则只属于 Agent，baseline 不包含。该分类说明实现和申报依据，不表示主办方已对 MTP 作出专项认定；预测头的权重、未知参数量和显存均完整保留，不从总显存中扣除。

| 项 | 内容 |
| --- | --- |
| 名称 / 基座 | Qwen3.8-27B MTP 预测头 / `Qwen/Qwen3.8-27B` |
| 来源 / revision | `ggml-org/Qwen3.8-27B-GGUF` / `a316ea527fde32c12487be7574e2db5ac2ad2a7e` |
| 文件 / 量化 | `mtp-Qwen3.8-27B-Q4_0.gguf` / GGUF Q4_0 |
| 文件大小 | 1,680,271,776 bytes |
| SHA256 | `c5be331f82fb61f5304adfa00ccd60c6743c8ce52255d66fa863446231d49ba4` |
| 许可证 / 精确参数量 | 模型卡声明 Apache-2.0 / 未核实 |
| 显存 | 已计入第 2 节主进程和设备采样；没有独立预测头显存测量 |
| 通用路径 | `/models/mtp-Qwen3.8-27B-Q4_0.gguf`，由 `MTP_MODEL` 覆盖 |

下载：[固定版本 MTP 权重](https://huggingface.co/ggml-org/Qwen3.8-27B-GGUF/resolve/a316ea527fde32c12487be7574e2db5ac2ad2a7e/mtp-Qwen3.8-27B-Q4_0.gguf)。

2026-10-30 核查时，实例未加载独立规划或文本向量模型；主模型与 MTP 的显存均计入设备采样。

默认 `guided_verify` 的三个角色都使用主模型。下列小模型和 RAG 配置供显式选择的研究路线使用。

- `small` 规划 profile 的研究候选为
  `Nellyw888/VeriReason-Qwen2.5-1.5b-RTLCoder-Verilog-GRPO-reasoning-tb`，
  旧记录 revision 为 `a171280d7f001fef819e90218e008a887f1292c7`，
  基座 `Qwen/Qwen2.5-Coder-1.5B-Instruct`，约 1.54B，规划用途；
  研究配置 `guided_verify_rag_bm25.yaml`、`guided_verify_rag_dense.yaml` 的独立服务端口为 8011；`serve/start.sh` 不启动该服务，研究需要时须显式运行 `VERI_GGUF=... ./serve/start_verireason.sh`。
  这些是既有研究记录，不是 2026-10-30 对该候选的重新验证或正式运行声明。
- 该候选既有记录的许可证为空（`license: null`），合计运行显存未完成验证。2026-10-28 的 `3e1efcc` 单题与 `333f32e` 四题记录已有真实扁平规划输出，但会混淆技能与知识卡片标识；这些局部结果不能证明当前配置的规划可靠性或正式可用性。
  公开 safetensors 约 6.2 GB（F32）只是旧文件大小记录，不是运行显存。
  未补全许可、来源、权重和合计资源验证并更新正式 manifest 前，不得作为正式组件。
- RAG 卡片与 `config/rag_embedding.yaml` 仅用于显式研究路线。当前不以常驻 embedding
  进程或配置文件的存在宣称正式使用检索，也不将研究配置结果作为默认方案结果。

若后续正式采用独立 planner、embedding 或其他辅助模型，须另行声明名称、基座、参数量、
用途、运行位置、显存及训练来源，并验证主模型、MTP、其他辅助模型和运行开销的合计限制。

## 7. 声明与未完成验证

- 两份权重的公开固定版本、文件字节数与 SHA256 已按 2026-10-30 实例记录核对。
- 模型与服务声明对应 HIP + MTP3 正式路线；不把旧权重、研究配置或 mock 当作当前运行证据。
- 尚未完成正式负载峰值、单卡 32 GB 限制、容器复现、完整题集基线对照与官方评分验收。
- 真实单题验证与服务启动记录保留在开发区，瞬时采样不替代完整验收。
- 精确参数量、量化工具版本及发布方完整训练来源未核实；未完成项不填作已验证。

启动脚本启用 `--jinja` 以落实 manifest 的思考设置。如果二进制旁有 `rocblas/library` 且环境中尚未设置 `ROCBLAS_TENSILE_LIBPATH`，脚本会将其指向该目录。第 4 节参数对应 2026-10-30 的实例记录。断网容器重建仍须单独验收。[推理服务启动脚本](../serve/llamacpp.sh)
