# 服务栈起不来（量化格式、模型架构、词表）

这三条都不是「模型答得不好」，而是**服务本身跑不起来**。在评测口径下它们等价于全部 L0，
所以它们比任何一道题的失败都严重。三条都已在
[`../decisions/0001-inference-backend.md`](../decisions/0001-inference-backend.md) 里记了结论，
这里按失败分析的格式再记一遍，便于 `REPORT.md` 引用。

环境：AMD Radeon Cloud 实例，模板 `gh-rtl-agent`（id 4443），W7900（gfx1100），
vLLM `0.16.1.dev0+g89a77b108.d20260317`，torch 2.9.1+ROCm 7.2，transformers 4.57.6。

## 一、AWQ 不加 `--dtype float16` 就找不到 WNA16 线性层

**现象**：`cyankiwi/Qwen3-30B-A3B-Instruct-2507-AWQ-4bit` 默认（bf16 激活）启动即失败：

```
ValueError: Failed to find a kernel that can implement the WNA16 linear layer. Reasons:
 ConchLinearKernel cannot implement due to: Group size (32) not supported by ConchLinearKernel,
   supported group sizes are: [-1, 128]
 ExllamaLinearKernel cannot implement due to: Exllama only supports float16 activations
```

**原因**：这份量化权重的分组是 group_size=32，而 Conch 内核只支持 -1/128；
唯一剩下的 Exllama 路径要求 fp16 激活，而 vLLM 默认按模型 config 取 bf16。

**尝试过的办法**：加 `--dtype float16` 后选中 `ExllamaLinearKernel`，正常加载并跑完全题集。
**只改激活精度，不改权重格式**，但要在 `MODEL.md` 里写明。

**遗留风险**：换一个 group_size=128 的 AWQ 权重就能走 Conch 路径，**本批没有做这个对照**，
所以还不知道 fp16 激活本身对分数有多大影响。这是 `decisions/0002` 里「同一模型、
不同量化档」那一组要补的实验。

## 二、这份 vLLM 不认 `qwen3_5` / `qwen3_5_moe`

**现象**：Qwen3.5、Qwen3.6、Qwen3.8 三个系列（计划里的 A1、A2、A9，以及 Qwen3.5-9B）
在这份镜像上**无法服务**。vLLM 架构注册表与 transformers 4.57.6 里都没有这两个架构名。

**原因**：模型比镜像新。这份 vLLM 构建于 2026-03-17，而 `qwen3_5_moe` 是之后才进入
transformers 与 vLLM 的。

**可用的相关架构**：`Qwen3MoeForCausalLM`、`Qwen3ForCausalLM`、`Qwen2ForCausalLM`、
`GptOssForCausalLM`、`Glm4MoeLiteForCausalLM`。

**尝试过的办法**：只做了确认（查注册表与源码），**没有**尝试升级 vLLM。

### 后续查到的关键信息（2026-09-25 补）

1. **vLLM 主库里注册 text-only 架构的 PR 被关掉且没有合并。**
   [PR #48081](https://github.com/vllm-project/vllm/pull/48081)
   「Register Qwen3_5ForCausalLM and Qwen3_5MoeForCausalLM with IsHybrid support」
   的 API 返回值是 `"merged": false`、`"merged_at": null`，2026-07-29 关闭。
   也就是说 **光升级 vLLM 不一定能解锁这几个模型**——缺的正是把 text-only 权重
   接到推理路径上的那一步注册。
2. **但新一点的 vLLM 确实带了 `qwen3_5` 的模型代码**，只是走多模态包装
   （`Qwen3_5MoeForConditionalGeneration`）。社区为此发布了一个**纯 Python 的补丁**：
   [`bjk110/Qwen3.5-122B-A10B-abliterated-AWQ` 的 `vllm_patches/patch_qwen35_moe_text.py`](https://huggingface.co/bjk110/Qwen3.5-122B-A10B-abliterated-AWQ/raw/main/vllm_patches/patch_qwen35_moe_text.py)，
   它给 `registry.py` 注册 `Qwen3_5MoeForCausalLM -> Qwen3_5MoeTextOnlyShim`，
   再往 `qwen3_5.py` 里加一个跳过视觉编码器的子类。**HF 在实例上可达**，所以这份补丁能取到。
   注意它的路径写死成 `/usr/local/lib/python3.12/dist-packages/`，而本镜像的 vLLM 在
   `/opt/venv/lib/python3.12/site-packages/`，要用得先改路径。
3. PyPI 上 vLLM 已经到 **0.30.0**，而本镜像是 0.16.1.dev0（2026-03-17）。
   PyPI 的 `vllm` wheel 是 CUDA 版，ROCm 要用单独的 wheel 源；平台的代理只放行
   HF 与 PyPI 镜像，所以「在实例上 pip 装新版 vLLM」这条路**很可能走不通**，
   优先考虑换镜像／模板。

### 下一步（按性价比排序）

1. 找一个自带更新 vLLM 的镜像——平台列表里有一个 `Qwen3.8-27B` 的镜像，
   能跑 Qwen3.8 就说明它的 vLLM 至少带了 `qwen3_5`，先查它的版本与架构注册表。
2. 若该镜像只缺 text-only 注册，就把上面那份社区补丁按本镜像的路径改写后应用。
3. 若两条都不成，本批就只能在旧一代模型里选型，并在报告里如实写明原因。

**影响**：本批筛掉了四个 A 层候选，其中 A1（Qwen3.6-35B-A3B）按速度与代数是最有希望的一个。
在解决之前，选型只能在旧一代模型里做。

## 三、gpt-oss 系列缺一份必须在镜像里预置的词表

**现象**：`openai/gpt-oss-20b` 权重能加载（14.3 GiB，KV 池 284,400 token），但服务启动失败：

```
openai_harmony.HarmonyError: error downloading or loading vocab file
```

**原因**：`openai_harmony` 的 Rust 分词器（tiktoken-rs）在**运行时**要去
`https://openaipublic.blob.core.windows.net/encodings/o200k_base.tiktoken` 取词表
（sha256 `446a9538...`），而平台出口代理对该域名返回 **403**，只放行 HF 与 PyPI 镜像。
镜像里没有预置这份词表，HF 的 `openai/gpt-oss-20b` 仓库里也没有这个文件。

**尝试过的办法**：查过 `TIKTOKEN_CACHE_DIR`、`TIKTOKEN_RS_CACHE_DIR`、
`TIKTOKEN_ENCODINGS_BASE` 三个开关，并在实例上全盘搜索过该文件——都没有。本次没有解决。

**为什么这条必须优先处理**：决赛沙箱**断网**，这个下载在评测当天一定会失败。
必须在 `Dockerfile` 里把词表放进 `TIKTOKEN_RS_CACHE_DIR`（默认目录名 `tiktoken-rs-cache`），
否则 gpt-oss 系列一律按 L0 计。**这是提交层面的问题，不是「能不能测」的问题。**

## 参考

- 数据与上下文：`../notes/2026-09-25-screening-results.md`
- 结论与计费：`../decisions/0001-inference-backend.md`「实测进展（2026-09-25）」
- 原始日志：`../runs/20260925-*/`（远端 `~/fpgachina2026-remote/vllm.log`，实例已销毁）

## 四、换到模板 `qwen`（vLLM 0.27.0）之后新遇到的三件事

背景：旧镜像的 vLLM 是 `0.16.1.dev0`（2026-03-17），不认 `qwen3_5`。换成用户新建的模板
`qwen`（id 4477，镜像 `work@sha256:1c264b1f…`，平台里标为 `Qwen3.8-27B`）后，
vLLM 是 **0.27.0**、transformers **5.15.0**，架构注册表 375 项里**有**
`Qwen3_5ForCausalLM`、`Qwen3_5MoeForCausalLM`（还有 `…ForConditionalGeneration` 与 MTP 变体），
`qwen3_5.py` 也在。**架构这道坎过了。**

顺带三个新的坑：

### 1. `--disable-log-requests` 在 0.27 上不存在了

```
api_server.py: error: unrecognized arguments: --disable-log-requests
```

0.27 改成了 `--enable-log-requests | --no-enable-log-requests`。
**我们的 `serve/vllm.sh` 里写死了 `--disable-log-requests`**，所以在这份镜像上直接起不来。
本次实验的做法是只在远端的临时副本上 `sed` 掉这个参数，**没有改仓库里的 `serve/vllm.sh`**。

这条要记进 `decisions/0001`：`serve/vllm.sh` 的启动参数必须与最终镜像的 vLLM 版本匹配，
否则提交当天服务起不来就是全题 L0。纯装饰性的参数（这个就是）不如直接去掉。

### 2. 给 8B 模型定的 `GPU_UTIL=0.62` 对 35B 级模型不够

```
ValueError: No available memory for the cache blocks.
```

Qwen3.6-35B-A3B 的 AWQ 权重实测占 **22.41 GiB**，而 `0.62 × 47.98 GiB = 29.7 GiB` 的预算
减去权重与开销后没有 KV 块可用。改成 `GPU_UTIL=0.85` 后正常，KV 池 **474,273 token**
（32k 上下文下 14.47 倍并发）。

教训：`gpu_memory_utilization` 要按「权重 + KV + 开销」算，不能沿用为小模型调的 0.62。
按 32 GiB 单卡折算，这个模型需要 `0.9` 左右才装得下（权重 22.41 + 单序列 KV 约 0.64 GiB + 开销）。

### 3. 权重被解析成多模态包装，会白加载一个视觉塔

日志里是：

```
Resolved architecture: Qwen3_5MoeForConditionalGeneration
```

也就是说 checkpoint 的 config 声明的是多模态架构，vLLM 会连视觉部分一起加载
（22.41 GiB 里有一部分是它）。同一份注册表里其实**也有 text-only 的
`Qwen3_5MoeForCausalLM`**，用 `--hf-overrides` 把 `architectures` 改成它有可能省下这块显存——
**本次没有验证**，留作后续优化项（对 32 GiB 单卡很关键）。

另外注意：这个镜像的 vLLM 是**源码构建**（import 路径是
`/home/zihaomu/bigssd/Muse_Glimmer_30B/vllm_test/build/vllm-src/vllm`），不是 `/opt/venv` 里的
独立安装。`/opt/venv/bin/python3` 能 import 到它，但这条路径不属于我们，镜像一变就没了，
所以**不能把它当成提交方案的一部分**，只能用来说明「换个镜像确实能解决架构问题」。
