# 0001 推理后端的选择

| 项 | 内容 |
| --- | --- |
| 状态 | 待定（已确认比赛不限定后端；vLLM 在验证阶段同代的 W7900 上已跑通，决赛硬件上尚未验证） |
| 记录日期 | 2026-09-22，2026-09-24 补充实测进展 |
| 相关文件 | `../../serve/vllm.sh`、`../../manifest.json`、`../../model/MODEL.md`、`../remote/remote_vllm.sh` |

## 背景

仓库中的示例方案和远端测试脚本都默认使用 vLLM。需要确认比赛是否规定必须使用 vLLM。

## 结论

**比赛没有规定推理后端，vLLM 只是示例方案的默认选择。** 推理后端由队伍自己决定，
但必须满足下面列出的硬性要求。目前团队还没有确定使用哪个后端。

## 官方文档中的依据

以下路径都相对于仓库根目录。

| 出处 | 内容 |
| --- | --- |
| `README.md` 第 42 行、`SCORING.md` 第 12 行 | 方案须包含「推理栈」（推理后端及其服务配置），没有指定用哪个后端 |
| `example/model/MODEL.md` 第 59 行 | 推理后端一栏为 `vLLM / llama.cpp / SGLang / ...` |
| `REPORT_TEMPLATE.md` 第 80 行 | 推理后端一栏为 `[vLLM / llama.cpp]` |
| `example/baseline.py` 第 11 行 | 「队伍决定模型、量化、推理后端与服务配置」 |
| `SCORING.md` 第 231 行、`docs/FAQ.md` 第 173 行 | 同一模型在不同推理后端下吞吐量可相差数倍，选择后端、调整服务配置本身就是考察的工程能力 |

仓库中出现的 `serve/vllm.sh`、`manifest.json` 里的 `"backend": "vllm"`、
`localhost:8000`，都只是示例方案的默认值，不是要求。

## 选择后端时的硬性要求

1. **接口：** 推理服务必须提供 OpenAI 兼容的 `/v1/chat/completions`
   （`example/baseline.py` 第 13 行）。`baseline.py` 还会调用 `/v1/models` 记录模型名，
   这个接口失败时会退回使用 `"default"`，但最好也提供。
2. **运行条件：** 单卡显存 32 GB 以内，断网运行，基于官方基础镜像构建。决赛硬件是
   AMD Radeon AI PRO R9700（gfx1201 架构，使用 ROCm 平台），所以后端必须能在
   ROCm 上运行（`SCORING.md` 第 1.1 节）。
3. **一致性：** 方案和基线必须使用同一个推理服务，且与 `MODEL.md` 中的声明一致
   （`SCORING.md` 第 3.2 节）。

vLLM、SGLang、llama.cpp 的 `llama-server` 都提供第 1 条要求的接口。第 2 条需要等
官方基础镜像发布后实际测试确认。`example/serve/README.md` 的「跨代架构的已知问题」
一节提到，部分框架在 gfx1201 上存在 FP8 被悄悄转换成 FP32、部分算子库无法使用等
问题，选型时需要留意。

## 实测进展（2026-09-24）

在 AMD Radeon Cloud 的实例上（W7900，gfx1100，镜像 `AMD-Stable-GH-Proxy` 自带 vLLM 0.16.1）：

- BF16（Qwen3-8B、Qwen2.5-Coder-7B）、AWQ（两个 32B 模型）、GPTQ 4 位 MoE（Qwen3-30B-A3B）
  都能加载运行
- 镜像自带的 `flash_attn` 已损坏，需要先卸载，否则 vLLM 加载 Qwen3 时报错
- **服务参数对基线影响很大**：Qwen3 不加 `--reasoning-parser qwen3` 时，思考内容混进回复
  正文，`baseline.py` 提取到思考中的草稿；同样 63 题上基线从 0.486 升到 0.695。是否关闭思考
  （`--default-chat-template-kwargs`）同样改变基线和速度。这些都是规则允许的服务配置，
  要写进 `model/MODEL.md`
- 速度：Qwen3-8B BF16 单路约 26 token/秒，MoE 4 位约 79 token/秒；AWQ 在这张卡上很慢
- 显存：`gpu_memory_utilization` 0.62 时，实际占用 32.2 到 34.1 GB，32B AWQ 模型超过 32 GB

尚未验证：决赛的 R9700（gfx1201）上这些量化格式是否可用，以及速度如何。数据见
`../notes/2026-09-24-baseline-sweep.md` 和 `../experiments/` 中 2026-09-24 的记录。

## 实测进展（2026-09-25）：量化格式的三条硬限制

本次会话在同一台云实例上（模板 4443，W7900，vLLM `0.16.1.dev0+g89a77b108.d20260317`，
torch 2.9.1+ROCm 7.2）实测了 7 个模型的 baseline，过程中撞到三条会影响选型的限制。
数据见 `../notes/2026-09-25-screening-results.md`。

### 1. AWQ 必须显式加 `--dtype float16`

`cyankiwi/Qwen3-30B-A3B-Instruct-2507-AWQ-4bit` 的量化分组是 group_size=32。默认 bf16 激活时
vLLM 找不到可用的 WNA16 线性层实现，直接启动失败：

```
ValueError: Failed to find a kernel that can implement the WNA16 linear layer. Reasons:
 ConchLinearKernel ... Group size (32) not supported ... supported group sizes are: [-1, 128]
 ExllamaLinearKernel ... Exllama only supports float16 activations
```

加 `--dtype float16` 后选中 `ExllamaLinearKernel`，正常加载。**只改激活精度，不改权重格式**，
但要写进 `MODEL.md`。这也解释了 `example/serve/README.md` 里说的「部分算子库在 RDNA 4 上
不工作，须显式关闭」是本赛道的现实问题，不是理论风险。

### 2. 这份 vLLM 不认 2026 年的新架构

vLLM 的架构注册表与 transformers 4.57.6 里都**没有 `qwen3_5` / `qwen3_5_moe`**，
所以 Qwen3.5／Qwen3.6／Qwen3.8 三个系列的模型在这份镜像上**无法服务**。
可用的相关架构是 `Qwen3MoeForCausalLM`、`Qwen3ForCausalLM`、`Qwen2ForCausalLM`、
`GptOssForCausalLM`、`Glm4MoeLiteForCausalLM`。

要测新一代模型，需要换镜像／模板，或在实例上另建环境装更新的 vLLM——两条路都还没验证。

### 3. gpt-oss 系列需要一份必须预置的词表

`openai_harmony` 的分词器（tiktoken-rs）运行时要去
`https://openaipublic.blob.core.windows.net/encodings/o200k_base.tiktoken` 取词表，
而平台的出口代理对该域名返回 **403**（只放行 HF 与 PyPI 镜像），导致服务启动即失败：

```
openai_harmony.HarmonyError: error downloading or loading vocab file
```

**这条是提交层面的硬约束**：决赛沙箱断网，必须在 Dockerfile 里预置该词表
（放进 `TIKTOKEN_RS_CACHE_DIR`，默认 `tiktoken-rs-cache`），否则 gpt-oss 系列一律按 L0 计。

### 4. 量化精度的收益不是单调的（同一模型的三个精度实测）

| 精度 | 题集得分 | 权重显存 | tps（并发 1） |
| --- | ---: | ---: | ---: |
| BF16 | 0.3935 | 7.67 GiB | 52.0 |
| AWQ 8-bit | 0.3923 | 5.41 GiB | **99.3** |
| AWQ 4-bit | 0.3432 | 3.45 GiB | 34.7 |

8-bit 质量与 BF16 在噪声内相同且快近一倍；**4-bit 既掉分又更慢**（走的是 fp16 的
Exllama 路径）。所以 4-bit 只应作为「装不下时的妥协」，不能当默认选择。

### 5. 启动参数必须与镜像里的 vLLM 版本匹配（**提交前必须处理**）

换到 vLLM 0.27.0 的镜像后，`serve/vllm.sh` 里的 `--disable-log-requests` 直接报：

```
api_server.py: error: unrecognized arguments: --disable-log-requests
```

0.27 把它改成了 `--enable-log-requests | --no-enable-log-requests`。**这个参数纯粹是日志装饰，
去掉它没有任何功能损失**，但留着会让服务在决赛镜像上起不来——那是全题 L0。
本次实验只在远端临时副本上 sed 掉，**没有改仓库里的 `serve/vllm.sh`**；
改与不改要团队定，因为它属于提交文件（改的话要同步 `MODEL.md` 与 README 第 5 节）。

顺带两条从第二批得到的服务参数经验：

- `gpu_memory_utilization` 要按「权重 + KV + 开销」定：给 8B 模型调的 0.62 用不了 22.41 GiB 的
  35B MoE，会报 `No available memory for the cache blocks`，实测 0.85 可用。
- 混合思考模型必须显式关思考：`--default-chat-template-kwargs '{"enable_thinking":false}'`，
  否则思考内容写进 `content` 并吃掉 `baseline.py` 的 8192 上限，基线会被截断主导
  （见 [`../failures/thinking-in-content.md`](../failures/thinking-in-content.md)）。

细节见 [`../failures/serving-stack.md`](../failures/serving-stack.md) 第四节。

### 另外：平台计费

1 credit = 1 GPU 小时。本次会话约 3 小时用掉 3 credits（11 → 8）。


## 对现有远端测试脚本的影响

`../remote/remote_vllm.sh` 目前默认使用 vLLM：同步并启动的是 `serve/vllm.sh`，传入
的是 vLLM 专用参数（如 `GPU_UTIL`），提示文字也都写着「vLLM」。换用其他后端后，这个
脚本需要修改。其余脚本（`tunnel.sh`、`remote_selftest.sh`、`serve_local.sh`、
`submit_client.py`）只依赖 OpenAI 兼容接口，与后端无关，只有变量名和提示文字带有
「vLLM」字样。

## 待办：把远端脚本改成与后端无关

计划把 `remote_vllm.sh` 改为 `remote_serve.sh`：

- 要同步和启动的脚本由 `remote.env` 中的 `REMOTE_SERVE_SCRIPT` 指定，默认值取
  `manifest.json` 中的 `serving.start_command`，保证远端运行的就是方案声明的启动脚本
- 只统一传入 `MODEL`、`PORT` 等通用参数；各后端专用的参数放在 `REMOTE_SERVE_ENV`
  中原样传入
- 变量名、提示文字和文档中的「vLLM」改为「推理服务」，并在文档中写明对任何后端的
  要求：只监听 `127.0.0.1`，提供 `/v1/chat/completions` 与 `/v1/models`

`example/serve/vllm.sh` 是官方文件，不修改。`43240-agent/serve/vllm.sh` 暂时保留，
确定后端之后再换成对应的启动脚本，并同步更新 `manifest.json`、`model/MODEL.md`。

## 做出决定时需要更新

- 本文的「状态」一栏，并写明选择理由（可以附上 `../experiments/` 中的对比记录）
- `../../serve/` 中的启动脚本、`../../manifest.json` 的 `serving` 部分、`../../model/MODEL.md` 第 4 节
- `../../README.md` 第 5 节
