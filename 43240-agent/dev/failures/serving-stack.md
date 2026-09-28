# 服务栈起不来（量化格式、模型架构、词表）

| 项 | 内容 |
| --- | --- |
| 状态 | **部分解决**——已解决 5 条，待解决 2 条，已确认受限 2 条 |
| 影响 | 候选可用性：服务起不来在评测口径下等价于**全题 L0**，比任何一道题失败都严重；提交面还会直接决定评测当天能不能跑 |
| 最后更新 | 2026-09-28 |
| 相关决策 | [`../decisions/0001-inference-backend.md`](../decisions/0001-inference-backend.md) |
| 相关结果 | [`../notes/2026-09-25-screening-results.md`](../notes/2026-09-25-screening-results.md) |
| 关键运行 | `20260925-154115`（AWQ 首次跑通）、`20260925-194130`（新一代 Qwen 首次跑通）、`20260927-152225`（gpt-oss 跑通） |

## 问题

这一份记录「服务本身跑不起来」的全部问题。它们分三类来源：

1. **量化格式**：权重格式与这张卡（gfx1100，ROCm）上的内核不匹配；
2. **模型架构**：镜像里的 vLLM / transformers 太旧或不兼容，认不出模型；
3. **运行环境**：分词器、词表、启动参数这类与模型无关但与镜像强相关的东西。

用的两个镜像（本文件里区分标注）：

| 镜像 | 怎么用 | vLLM | transformers |
| --- | --- | --- | --- |
| 模板 `gh-rtl-agent`（id 4443） | 最早一批实验 | `0.16.1.dev0+g89a77b108.d20260317` | 4.57.6 |
| 模板 `qwen`（id 4477，平台标为 `Qwen3.8-27B`） | 2026-09-25 之后全部实验 | **0.27.0**（源码构建，见 S2 末尾的提醒） | **5.15.0** |

硬件：AMD Radeon Cloud 单实例，W7900（gfx1100，48 GiB），torch 2.9.1+ROCm 7.2。

## 已解决

### S1. AWQ 不加 `--dtype float16` 会找不到 WNA16 线性层

**现象**：`cyankiwi/Qwen3-30B-A3B-Instruct-2507-AWQ-4bit` 默认（bf16 激活）启动即失败：

```
ValueError: Failed to find a kernel that can implement the WNA16 linear layer. Reasons:
 ConchLinearKernel cannot implement due to: Group size (32) not supported by ConchLinearKernel,
   supported group sizes are: [-1, 128]
 ExllamaLinearKernel cannot implement due to: Exllama only supports float16 activations
```

**原因**：这份权重的分组是 group_size=32，而 Conch 内核只支持 -1/128；唯一剩下的
Exllama 路径要求 fp16 激活，而 vLLM 默认按模型 config 取 bf16。

**方案**：启动时加 `--dtype float16`（只改激活精度，不改权重格式）。加完选中
`ExllamaLinearKernel`，正常加载并跑完全题集 155 题（运行 `20260925-154115`）。

**注意适用范围**：这是**针对 WNA16 内核路径的补丁，不是 AWQ 的通用开关**——
MLA 类模型加了反而起不来，见 S5。

### S2. 旧镜像不认 `qwen3_5` 架构 → 换模板后解决

**现象**：Qwen3.5 / 3.6 / 3.8 三个系列（`Qwen3.6-35B-A3B`、`Qwen3.5-35B-A3B`、
`Qwen3.8-27B`、`Qwen3.5-9B`）在模板 `gh-rtl-agent` 上**无法服务**：
vLLM 架构注册表与 transformers 4.57.6 里都没有这两个架构名。

**原因**：模型比镜像新。那份 vLLM 构建于 2026-03-17，而 `qwen3_5_moe` 是之后才进入
transformers 与 vLLM 的。

**方案**：换用模板 `qwen`（id 4477）。它的 vLLM 是 0.27.0、transformers 5.15.0，
注册表 375 项里**有** `Qwen3_5ForCausalLM`、`Qwen3_5MoeForCausalLM`（以及
`…ForConditionalGeneration` 与 MTP 变体）。换完立刻测通：
`Qwen3.6-35B-A3B` 全题集 **0.610**（运行 `20260925-194130`）。

**当时查过但不必要的三条信息**（留作背景，不必再查）：

- vLLM 主库注册 text-only 架构的 [PR #48081](https://github.com/vllm-project/vllm/pull/48081)
  API 返回 `"merged": false`，2026-07-29 关闭——所以**光升级 vLLM 不一定能解锁**。
- 社区有一份纯 Python 补丁（`bjk110/…` 的 `vllm_patches/patch_qwen35_moe_text.py`）给
  `registry.py` 注册 text-only shim；它写死了 `/usr/local/lib/...` 路径，要用得先改。
- PyPI 上 vLLM 已到 0.30.0，但 wheel 是 CUDA 版；平台代理只放行 HF 与 PyPI 镜像，
  在实例上 pip 装新版「很可能走不通」。

**一条要记住的提醒**：模板 `qwen` 里的 vLLM 是**源码构建**（import 路径是
`/home/zihaomu/bigssd/Muse_Glimmer_30B/vllm_test/build/vllm-src/vllm`），不属于我们，
镜像一变就没了。它能说明「换个镜像确实能解决架构问题」，但**不能作为提交方案的一部分**。

### S3. gpt-oss 缺词表 → 已解决，断网可用

**现象**：`openai/gpt-oss-20b` 权重能加载（14.3 GiB，KV 池 284,400 token），但服务启动失败：

```
openai_harmony.HarmonyError: error downloading or loading vocab file
```

**原因**：`openai_harmony` 的 Rust 分词器（tiktoken-rs）在**运行时**要去
`https://openaipublic.blob.core.windows.net/encodings/o200k_base.tiktoken` 取词表
（sha256 `446a9538…b1a2d`），而平台出口代理对该域名返回 **403**（只放行 HF 与 PyPI 镜像）。
镜像里没有预置，HF 的 `openai/gpt-oss-20b` 仓库里也没有这个文件。

**方案（已实测可复现）**：从 `openai_harmony` 的编译产物里挖出它用的缓存约定：

```bash
strings /opt/venv/lib/python3.12/site-packages/openai_harmony/openai_harmony.abi3.so \
  | grep -iE 'tiktoken|blob\.core|CACHE_DIR'
# TIKTOKEN_RS_CACHE_DIR / tiktoken-rs-cache / https://openaipublic.blob.core.windows.net/encodings/
```

即在 `TIKTOKEN_RS_CACHE_DIR` 下**以词表 URL 的 sha1 为文件名**放词表
（`sha1(url)` = `fb374d419588a4632f3f557e76b4b70aebbca790`），它还会校验文件哈希。
HF 上有可达副本，完整步骤如下：

```bash
hf download baseten/o200k-base-tiktoken --local-dir /workspace/tiktoken
sha256sum /workspace/tiktoken/o200k_base.tiktoken
# 446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d
mkdir -p /workspace/tiktoken-cache
cp /workspace/tiktoken/o200k_base.tiktoken \
   /workspace/tiktoken-cache/fb374d419588a4632f3f557e76b4b70aebbca790
env -u http_proxy -u https_proxy TIKTOKEN_RS_CACHE_DIR=/workspace/tiktoken-cache \
    /opt/venv/bin/python -c "from openai_harmony import load_harmony_encoding, HarmonyEncodingName; \
        load_harmony_encoding(HarmonyEncodingName.HARMONY_GPT_OSS); print('ok')"
```

**验证**：清掉代理后仍能加载（说明不依赖网络）；随后 `gpt-oss-20b` 跑通全题集
**0.689**（运行 `20260927-152225`）。**文件名必须是 URL 的 sha1**，只放文件本身不够。

> 提交层面还有一步没做（把这段操作写进 `Dockerfile`），见未解决 **P2**。

### S4. 换到模板 `qwen` 后立刻踩到的两个坑

| 坑 | 现象 | 方案 |
| --- | --- | --- |
| `--disable-log-requests` 在 0.27 上被移除 | `api_server.py: error: unrecognized arguments: --disable-log-requests`（我们的 `serve/vllm.sh` 里写死了它，服务直接起不来） | 实验期只在**远端临时副本**上 sed 掉；规范做法见未解决 **P2** |
| 给 8B 调的 `GPU_UTIL=0.62` 装不下 35B 级权重 | `ValueError: No available memory for the cache blocks`（22.41 GiB 权重撞上 `0.62 × 47.98 = 29.7 GiB` 预算） | 改 `GPU_UTIL=0.85`，KV 池 474,273 token；`gpu_memory_utilization` 要按「权重 + KV + 开销」算 |

**顺带发现**：权重被解析成多模态包装（日志里 `Resolved architecture:
Qwen3_5MoeForConditionalGeneration`），vision 部分占了一部分显存。注册表里也有 text-only 的
`Qwen3_5MoeForCausalLM`，用 `--hf-overrides` 改 `architectures` 可能省下这块——
**没有验证**，对 32 GiB 单卡可能有用。

### S5. MLA 类模型不能强制 `--dtype float16`

**现象**：`cyankiwi/GLM-4.7-Flash-AWQ-4bit` 权重完整（19 GiB、4 个分片），加了
`--dtype float16` 起服务失败：

```
ValueError: No valid MLA prefill backend found with MLAPrefillSelectorConfig(
    dtype=torch.float16, mla_dimensions=(qk_nope_head_dim=192, qk_rope_head_dim=64, …))
```

**原因**：GLM-4.7-Flash 用 **MLA（多头潜在注意力）**，MLA 预填充内核在 fp16 下没有实现。
而我把 `--dtype float16` 从 S1 那条经验条件反射式带了过来——它只适用于 AWQ 的 WNA16 路径。

**方案（dtype 对照表）**：

| 模型类型 | dtype 怎么给 |
| --- | --- |
| 普通 AWQ（WNA16 路径，如 `Qwen3-30B-A3B-Instruct-2507` 的 AWQ） | 需要 `--dtype float16`，否则报 S1 的错 |
| **MLA 类（如 GLM-4.7-Flash）** | **不要强加 fp16**，用默认 |
| BF16 原版权重 | 不要加，保持 bf16 |

**教训**：`--dtype float16` 是针对特定内核路径的补丁，换模型族（尤其换注意力结构）
就要重新判断。这条只解决「参数给错」，GLM 本身仍不可服务，原因见 **P4**。

## 未解决

### P1（待解决）. WNA16 路径下 fp16 激活对分数的影响未做对照

- **现状**：S1 的解法只改激活精度、不改权重格式，但**没有做对照**——换一个 group_size=128
  的 AWQ 权重就能走 Conch 路径（原生支持），从而排除「fp16 激活是否影响分数」这个变量。
- **限制**：需要找到同模型、group_size=128 的 AWQ 权重；不一定存在。
- **下一步**：在「同一模型不同量化档」那组实验里补一个 group_size=128 的点。

### P2（待解决，提交层面）. 决赛断网要求把词表与启动参数打进镜像

还没做，必须在提交前完成：

1. 按 S3 的命令把词表**和它的 sha1 文件名**写进 `Dockerfile`，并设好 `TIKTOKEN_RS_CACHE_DIR`；
2. 处理 `serve/vllm.sh` 里 0.27 已移除的 `--disable-log-requests`（纯装饰性参数，去掉无损失；
   它是提交文件，需要团队确认后改）；
3. 确认 `serve/vllm.sh` 的其余启动参数与最终镜像的 vLLM 版本匹配——**这一步没做对，
   评测当天服务起不来就是全题 L0**。

### P3（已确认受限）. MoE + 不对称量化 / 组大小 16 → North-Mini-Code 系列不可服务

`cyankiwi/North-Mini-Code-1.0-AWQ-INT4` 能加载权重，但引擎初始化失败：

```
AssertionError: Only symmetric quantization is supported for MoE
```

**已得到的可判定规则**（实测对比，均取自各自仓库的 `config.json`）：

| 权重仓库 | 位宽 | 对称 | 组大小 | 结果 |
| --- | ---: | --- | ---: | --- |
| `cyankiwi/North-Mini-Code-1.0-AWQ-INT4` | 4-bit | **False** | 32 | 引擎初始化失败（MoE 拒绝） |
| `FenomAI/North-Mini-Code-1.0-AWQ-INT4` | 4-bit | **False** | 32 | 同上 |
| `cyankiwi/Qwen3-30B-A3B-Instruct-2507-AWQ-4bit` | 4-bit | **True** | 32 | 正常，跑完 155 题 |
| `CohereLabs/North-Mini-Code-1.0-w4a16`（官方） | 4-bit | **True** | 16 | 组大小 16 被判成 NVFP4：`NotImplementedError: No NvFp4 MoE backend supports the deployment configuration` |
| `thoratsr7/North-Mini-Code-1.0-w4a16` | 4-bit | True | 16 | 格式直接标着 `nvfp4-pack-quantized` |
| `LeaderboardModel1/…-AutoRound-W4A16-Tuning` | 4-bit | — | — | `quant_method: auto-round` 未注册；强制 `--quantization inc` 被拒：`inc quantization is currently not supported in rocm` |

**结论**：MoE 模型要**同时**满足「`symmetric: true`」且「组大小 ≠ 16」才可能在这张卡上跑起来。
North-Mini-Code 试过五个版本都不满足，**已确认受限、不再尝试**（换镜像或换服务栈才可能解除）。
官方 `-fp8` 版本是 30 GB 且 FP8 在 gfx1100 上不是原生支持，同样不可行。

**提前判断的方法**：起服务前看权重仓库 `config.json` 的 `quantization_config`——
`compressed-tensors` 看 `config_groups.*.weights.symmetric`，AWQ 看有没有 `zero_point`；
组大小 16 一律先怀疑是 NVFP4。

### P4（已确认受限）. 自带分词器代码与 transformers 5.15 不兼容 → 两个模型不可服务

**通用规则**：模板 `qwen` 里是 transformers **5.15**，而**凡是自带分词器实现、且那份实现按
transformers 4.x 写的模型，都会在加载阶段失败**。已确认命中两个：

| 模型 | 权重 | 根因 |
| --- | --- | --- |
| `GLM-4.7-Flash`（AWQ 4-bit） | 19 GiB、4 个分片，完整 | `ImportError: cannot import name 'bytes_to_unicode' from 'transformers.models.gpt2.tokenization_gpt2'` |
| `Kimi-Linear-48B-A3B-Instruct`（AWQ 4-bit） | 27 GiB、7 个分片，完整 | 同上，逐字相同 |

**影响**：`GLM-4.7-Flash` 是候选里唯一的「非 Qwen 家族 MoE」，`Kimi-Linear-48B` 是唯一的
「线性注意力」样本，这两个覆盖缺口暂时都补不上。

**提前判断**：下载前先看 HF 仓库文件列表里有没有 `.py`（尤其 `tokenization_*.py`、
`modeling_*.py`）。**有自定义代码的仓库都要先怀疑**——但不是所有自定义代码都有问题：
`Ministral-3-14B`、`Devstral-Small-2-24B`、`gemma-4-12B-it` 都能正常加载。

**若将来确要测，两条路都不轻**：① 给镜像装兼容的旧版 transformers（会牵连其它模型，不建议）；
② 在权重目录里替换那份自带代码（等于维护一个 fork，提交时要额外说明）。
**建议先换候选**——非 Qwen 家族的 dense 已有两个实测点（`Ministral-3-14B` 0.476、
`gemma-4-12B-it` 0.679）。

## 排查这类问题的方法（本次总结）

1. **看 traceback 末端，不要只看开头**：真正的异常行在最后，用
   `grep -nE '(Error|Exception|error):' vllm.log | tail -3`，而不是 `tail` 或只抓前几条 ERROR。
2. **先看日志里打印的实际值**：例如 `--gpu-memory-utilization=0.6200`——我们曾以为
   命令行前缀生效了，实际被配置文件覆盖（见 [`../remote/README.md`](../remote/README.md)）。
3. **架构与内核能力可以直接查源码**：vLLM 的注册表
   （`vllm/model_executor/models/registry.py`）与平台能力
   （`vllm/platforms/rocm.py` 里 `supports_fp8()` 只在 CDNA 或 gfx12x 为真）都能读，
   比反复试快得多。

## 证据

- 原始日志：各运行目录 `../runs/<运行编号>/`；远端 `~/fpgachina2026-remote/vllm.log`（实例已销毁）
- 数据与上下文：[`../notes/2026-09-25-screening-results.md`](../notes/2026-09-25-screening-results.md)
- 结论与计费：[`../decisions/0001-inference-backend.md`](../decisions/0001-inference-backend.md)
