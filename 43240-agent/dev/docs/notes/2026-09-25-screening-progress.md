> **文档状态：归档笔记：结论、路径与命令反映当时实验或设计。** 历史证据保留，当前框架用法与限制以[详细参考](../reference.md)为准。

# 模型筛选的执行进展与待办

| 项 | 内容 |
| --- | --- |
| 状态 | 滚动更新中 |
| 最后更新 | 2026-09-28 |
| 设计口径 | [`2026-09-25-model-screening-plan.md`](2026-09-25-model-screening-plan.md)（第 1–9 节：取舍标准、硬门槛、候选清单、量化实验设计、指标、协议、预算） |
| 结果数据 | [`2026-09-25-screening-results.md`](2026-09-25-screening-results.md)、[`2026-09-25-joint-first-results.md`](2026-09-25-joint-first-results.md) |

这份文档只回答两件事：**现在做到哪了**、**接下来要做什么**。按日期追加，做完的项就地标注结果。

## 10. 执行进展（2026-09-25 补记）

### 第 0 步已完成

指标采集补齐了，并且验证过：`dev/tools/analysis/metrics.py`（`run` / `joint` / `probe` / `scrape` /
`kv` / `vram`）、`dev/tools/remote/vram_watch.sh`（远端显存采样）、
`dev/tools/remote/joint_run.sh`（一个模型一条命令跑完联合跑分）。
`run_eval.py` 在同时跑 `agent,baseline` 时会自动生成 `joint.json` / `joint.md`，
`record.py` 会把它写进实验记录。

### 第 1–5 步的执行情况

| 候选 | 筛选（全题集 baseline） | 联合（quick 34，agent+baseline） |
| --- | --- | --- |
| `Qwen3-Coder-30B-A3B`（AWQ-4bit） | ✅ `S_b` 0.564 | 未测（备选） |
| `Qwen3-30B-A3B-Instruct-2507`（AWQ-4bit） | ✅ `S_b` 0.588 | ✅ `S_a` 0.700，增益 1.178 |
| `Qwen3-4B-Instruct-2507`（BF16） | ✅ `S_b` 0.394 | ✅ `S_a` 0.518，增益 1.397 |
| `CodeV-R1-RL-Qwen-7B`（BF16） | ✅ `S_b` 0.665 | ✅ `S_a` 0.765，增益 1.066 |
| 同上模型的 AWQ-4bit / AWQ-8bit 两档 | ✅ 0.343 / 0.392 | `Qwen3-4B-Instruct-2507`（AWQ-4bit） ✅ 增益 1.143；`Qwen3-4B-Instruct-2507`（AWQ-8bit） 未测 |
| `Qwen3.6-35B-A3B`（AWQ-4bit） | ✅ `S_b` **0.610**（换镜像后） | 未测（按团队要求先只跑 baseline） |
| `Qwen3.5-35B-A3B`（AWQ-4bit） | ✅ `S_b` **0.605**（换镜像后） | 未测（同上） |
| `Qwen3.6-27B`（AWQ-4bit，dense） | ✅ `S_b` 0.610，但单路仅 4.9 token/s | 未测（dense 已判死） |
| `Qwen3.8-27B` `Qwen3.8-27B` | ❌ HF 上没有 4-bit 量化，FP8 放不进 32 GiB | ❌ 不可候选 |
| `Qwen3.5-9B` | ✅ `S_b` **0.542**（2026-09-27，官方 BF16） | 未测（本阶段只做 baseline） |
| `gpt-oss-20b`（原生 MXFP4） | ✅ **词表已解决**（2026-09-27，从 HF 取到并放进缓存，断网可用），跑分进行中 | 未测（本阶段只做 baseline） |
| `North-Mini-Code-1.0` | ❌ **测得但服务栈不支持**：五个量化版本逐一排除（不对称 AWQ、组大小 16 被当 NVFP4、`auto-round` 未注册、`inc` 在 ROCm 上被拒） | ❌ 不可测 |

数据在 `2026-09-25-screening-results.md` 与 `2026-09-25-joint-first-results.md`；
横向对照表由 `dev/tools/analysis/overview.py` 生成，见 `generated/2026-09-25-candidate-tables.md`。

### 三条与计划预期不符、需要记住的结论

1. **§1.3 那张「低基线 → 高增益」的估算过于乐观。** 实测里 L0 修好后只有 25%–67% 真正到 L3，
   其余停在 L1（系数 0.2），所以小模型的增益没有算出来的那么高。详见
   [`../failures/sim-mismatch.md`](sim-mismatch.md)。
2. **agent 会把本来做对的题改坏**（每个候选 2–3 道），这是纯粹的净损失，而且与模型无关。
   详见 [`../failures/agent-repair.md`](agent-repair.md)。
3. **4-bit 伤的是修复能力而不是生成能力**，所以 §4.1 的 H2 成立、H1 与 H3 不成立。

### 目前的选择：未定

**模型选型不做结论，由团队评判。** 我的建议与定量依据写在
[`../decisions/0002-model-choice.md`](0002-model-choice.md) 的「结论（最新）」一节，
要点是：首选 `Qwen3-4B-Instruct-2507`（BF16）（低基线、BF16、风险最小），唯一值得花一次实验验证的挑战者是 `Qwen3.6-35B-A3B`（AWQ-4bit）
（它需要在 `S_a` 上比 `Qwen3-4B-Instruct-2507`（BF16） 高约 0.21–0.26 才能反超，而同类 30B MoE 已知高出 0.18，正好在临界点上）。

### 卡住的地方（已解决一个）

- ~~**`Qwen3.6-35B-A3B` 与 `Qwen3.5-35B-A3B` 受镜像限制**~~ **已解决**：用户新建模板 `qwen`（id 4477），
  里面的 vLLM 是 0.27.0，架构注册表带 `Qwen3_5MoeForCausalLM`，这两个模型已测。
  经过见 [`../failures/serving-stack.md`](serving-stack.md) 的 **S2** 与 **S4**。
- **`Qwen3.8-27B` 不可候选**：HF 上没有 4-bit 量化版本，FP8 装不进 32 GiB 单卡。
- **`gpt-oss-20b`（原生 MXFP4）（gpt-oss）未解决**：`openai_harmony` 的词表必须在镜像里预置，否则决赛断网一律 L0。
- **平台 Cookie 约 4 小时失效**：失效后连实例状态都查不了，所以每批实验收工前必须先销毁实例。

---

## 11. 选型还差哪些实验（2026-09-25 末梳理，按团队口径修订）

**团队口径（2026-09-25 明确，优先于本文前面的旧计划）：**

1. **本阶段只测 baseline**，不测举办方示例 agent 框架下的表现。所以
   `--modes agent,baseline` 的联合跑分**不属于本阶段**，前面第 6、7 节里与联合阶段有关的
   安排一律推迟。
2. baseline 测试的重点是两件事：**做题情况**（`S_b`、等级分布、按题型通过率）
   与**错因**（失败原因分布、Vivado 报错编号）。
3. **决赛硬件（R9700 / gfx1201）暂不考虑**——初赛之后才有设备。因此 32 GiB 适配验证与
   gfx1201 复验都不在本阶段。

### 11.0 进展更新（2026-09-27）

| 原计划项 | 现在的状态 |
| --- | --- |
| `Qwen3.5-9B` 全题集 baseline | ✅ **已完成，`S_b` 0.542**（官方 BF16；原计划的 AWQ 版本经核实不存在） |
| `gpt-oss-20b` 的词表阻塞 | ✅ **已解决**，且全题集 baseline 已完成：**`S_b` 0.689**（目前最高），但代价是 22 次请求超时与 42.5 秒的单题耗时中位数 |
| `North-Mini-Code-1.0` 的全题集 baseline | ❌ **关闭**：五个量化版本逐一排除，当前服务栈没有可用格式（见 [`../failures/serving-stack.md`](serving-stack.md) 的 **P3**） |
| 重复性验证（多次采样） | ⏳ 进行中：对 `Qwen3.6-35B-A3B` 跑 **quick 34 题 × 3 次采样**。原计划跑全题集，但本次会话剩余时间不够（会撞上看门狗），因此改用联合对比所用的那个子集，并在文档里注明 |
| 错因与题型交叉分析 | ✅ **已完成**：见 [`../failures/l0-error-codes.md`](l0-error-codes.md)（从判定日志建立了「报错编号 → Vivado 原话」对照） |
| 备选候选（`GLM-4.7-Flash` 等）的 baseline | 未做 |
| 量化档对照（AWQ 与 GPTQ、4-bit 与 6-bit）的 baseline | 未做 |
| 32 GiB 等效预算验证、gfx1201 复验 | 按团队口径推迟到初赛之后 |
| 全题集的联合跑分 | 按团队口径本阶段不做 |

### 11.1 还差的 baseline 实验（按优先级）

| 实验 | 回答什么 | 代价 | 现状 |
| --- | --- | --- | --- |
| **`North-Mini-Code-1.0`（AWQ-4bit）的全题集 baseline** | 必测候选里最后一个没测的模型的做题情况与错因 | ~30 分钟 | 可服务已核实（vLLM 0.27 支持 `Cohere2MoeForCausalLM`），只差预算 |
| **`Qwen3.5-9B`（AWQ）的全题集 baseline** | 新一代 4–9B 档在「低基线路线」上的代表；现在的 `Qwen3-4B-Instruct-2507`（BF16）是旧架构 4B，需要同代对照 | ~20 分钟 | 有 `QuantTrio/Qwen3.5-9B-AWQ` |
| **`gpt-oss-20b`（原生 MXFP4）能否测** | 能否服务；以及「思考吃满 8192 导致基线自毁」是否真会发生 | 前置：解决词表 | 词表被代理 403，要先在 HuggingFace 上找可达来源 |
| **重复性：关键对比跑 `--samples 3`** | 现在 `Qwen3.6-35B-A3B`（0.610）、`Qwen3.6-27B`（0.610）、`Qwen3.5-35B-A3B`（0.605）、`Qwen3-30B-A3B-Instruct-2507`（0.588）全在噪声内，**没法说谁更好** | 求解 3 倍、判定时间不变 | 未做；计划 §5.2 要求分差小时必须重复 |
| 备选候选（有余力）：`GLM-4.7-Flash`、`Ministral-3-14B`、`gemma-4-12B`、`Qwen2.5-Coder-7B` 的全题集 baseline | 非 Qwen 家族、中尺寸 dense 的对照 | 每个 20–40 分钟 | 未做 |
| 量化档的 baseline 对照：`Qwen3-30B-A3B-Instruct-2507` 的 AWQ 与 GPTQ 对比；`Qwen3.6-27B` 的 4-bit 与 6-bit 对比 | 「参数量与量化精度孰轻孰重」的工程判断素材（`docs/FAQ.md` 第 13 问） | 每个 ~30 分钟 | 未做；同一个 4B 模型的三档（BF16 0.3935 / AWQ 8-bit 0.3923 / AWQ 4-bit 0.3432）已完成 |

### 11.2 分析侧（不占 GPU，直接服务「做题情况 + 错因」）

- **已做**：`dev/tools/analysis/overview.py` 现在产出四张表——A 分数、B 联合跑分、
  **C 错因分布**、**D 按题型通过率**（见 `generated/2026-09-25-candidate-tables.md`）。
- **待做**：把错因与 Vivado 报错编号（`samples.csv` 的 `error_ids`）按题型交叉，
  回答「哪一类题的哪一种错最多」。这是技能包选题的依据，也是 `REPORT.md` 失败分析的骨架。

### 11.3 本阶段明确不做

| 事项 | 为什么不做 |
| --- | --- |
| 联合跑分（`S_a`、增益、改坏道数） | 团队口径：本阶段只测 baseline；而且它衡量的是举办方示例 agent，不是我们要改进的方案 |
| 32 GiB 等效预算验证 | 决赛硬件初赛后才到位 |
| gfx1201（R9700）复验 | 同上 |
| 墙钟口径（`submit_client.py` 独占计时） | 那是「代价」项，属于联合/投题阶段 |
| `Qwen3.8-27B` `Qwen3.8-27B` | 没有 4-bit 量化；是否可用取决于决赛显存，等硬件确定后再判 |

### 11.4 最小可执行的下一步

**`North-Mini-Code-1.0` 与 `Qwen3.5-9B` 各跑一次全题集 baseline（合计约 50 分钟、不到 1 credit）**，必测候选候选就全部测完。
若还要回答「0.60–0.61 那四个到底谁更好」，需要把关键对比跑 `--samples 3` 复跑——
单次采样下它们的差距没有意义。

---

## 12. 备选候选的可行性核实（2026-09-27，全部逐项查证）

第 3 节的备选清单是**按传闻与体积**列的，没有核实过「在这张卡上到底跑不跑得起来」。
这次逐项查了 HF 上的 `config.json`、仓库体积、许可，以及 **vLLM v0.27.0 的注册表源码**。

### 12.1 三条硬门槛（都已用源码或实测确认）

| 门槛 | 判据 | 来源 |
| --- | --- | --- |
| 架构必须注册 | vLLM 的表里要有这个 `architectures` 名字 | 拉 `vllm/model_executor/models/registry.py`（v0.27.0）逐个 `grep` |
| 量化格式必须能在这张卡上跑 | **FP8 不行**：`supports_fp8()` 只在 `on_cdna() or on_gfx12x()` 为真，gfx1100 不在内；**NVFP4 / MXFP4 不行**；**AutoRound（`inc`）不行**（ROCm 明确拒绝）；**MoE 必须 `symmetric: true` 且组大小 ≠ 16** | 拉 `vllm/platforms/rocm.py`（v0.27.0）与今天实测的 `AssertionError` / `NotImplementedError` |
| 显存要装得下 | 4-bit 后 ≲ 30 GiB 才可能进 32 GiB 单卡；BF16 只有 ≲ 12B 的能进 | 已实测：22.41 GiB 权重在 32 GiB 等效预算下就已经很紧 |

**架构这一关 9/9 全部通过**（`Glm4MoeLiteForCausalLM`、`Mistral3ForConditionalGeneration`、
`Gemma4UnifiedForConditionalGeneration`、`GraniteForCausalLM`、`KimiLinearForCausalLM`、
`SeedOssForCausalLM`、`DeepseekV2ForCausalLM`、`Qwen2ForCausalLM`、`Qwen3_5ForConditionalGeneration`）。
所以备选候选的瓶颈**不在架构，而在量化格式与显存**。

### 12.2 逐项结论

| 候选 | 架构 / 许可 / 原始体积 | 可用的量化版本（已核对称性） | 现在能不能测 |
| --- | --- | --- | --- |
| `zai-org/GLM-4.7-Flash` | `Glm4MoeLiteForCausalLM` / MIT / 58.2 GiB BF16 | `cyankiwi/GLM-4.7-Flash-AWQ-4bit`：**对称=True、组 32** ✓；另有 `QuantTrio/…-AWQ`、8-bit、FP8（FP8 用不了） | ✅ **能**，4-bit 约 18 GB。**备选里最值得测的一个** |
| `ByteDance-Seed/Seed-OSS-36B-Instruct` | `SeedOssForCausalLM` / Apache-2.0 / 67.3 GiB BF16 | `QuantTrio/…-AWQ`、`…-GPTQ-Int4`、`cyankiwi/…-AWQ-4bit`；4-bit 约 20–21 GB | ✅ **能**（对称性未逐项核，但同作者同流程） |
| `mistralai/Ministral-3-14B-Instruct-2512` | `Mistral3ForConditionalGeneration` / Apache-2.0 / 29.3 GiB（官方 FP8） | 官方 FP8 **用不了**（gfx1100 不支持）；`cyankiwi/…-AWQ-4bit`：**对称=True、组 32** ✓，约 9 GB | ✅ **能** |
| `Qwen/Qwen2.5-Coder-7B-Instruct` | `Qwen2ForCausalLM` / Apache-2.0 / 14.2 GiB BF16 | 不需要量化 | ✅ **能，且最便宜**。已有 quick 分数 0.512，只缺全题集 |
| `google/gemma-4-12B-it` | `Gemma4UnifiedForConditionalGeneration` / **Apache-2.0 且不 gated** / 22.3 GiB BF16 | 官方/社区的 FP8 **用不了**；`cyankiwi/…-AWQ-INT4` 是**不对称**（dense 模型不受 MoE 那条限制，但未实测）；AutoRound 版走 `inc`，**ROCm 拒绝** | ⚠️ **BF16 可以**（22.3 GiB 上 48 GiB 卡没问题），4-bit 需实测 |
| `mistralai/Devstral-Small-2-24B-Instruct-2512` | `Mistral3ForConditionalGeneration` / Apache-2.0 / 48.1 GiB（官方 FP8） | 官方 FP8 **用不了**；有多个 `…-AWQ-4bit` | ⚠️ 能测但要先核对称性；它是面向 agent 的模型，本阶段只测 baseline，优先级低 |
| `moonshotai/Kimi-Linear-48B-A3B-Instruct` | `KimiLinearForCausalLM` / MIT / 91.5 GiB BF16 | `cyankiwi/…-AWQ-4bit`：**对称=True、组 32** ✓，约 27 GB | ⚠️ 能测但下载与显存都吃紧；**技术上有意思**（线性注意力 → KV 极小），适合当边界样本 |
| `ibm-granite/granite-4.2-30b` | `GraniteForCausalLM` / Apache-2.0 / 54.5 GiB BF16 | IBM 只发布 **fp8 / mxfp4 / nvfp4**——三种在本栈上都不行；**没找到社区 4-bit AWQ/GPTQ** | ❌ **暂时不可测**（与 `North-Mini-Code-1.0` 同一类问题） |
| `deepseek-ai/DeepSeek-Coder-V2-Lite-Instruct` | `DeepseekV2ForCausalLM` / 许可为 other（需注意提交合规） / 29.3 GiB BF16 | 只找到 FP8 与 w8a8（**FP8 用不了**）；没有 4-bit AWQ/GPTQ | ❌ 只有 BF16 可用，而它装不进 32 GiB；**48 GiB 卡上可以**，但那是另一回事 |
| `QuantTrio/Qwen3.6-27B-AWQ-6Bit` | `Qwen3_5ForConditionalGeneration` / Apache-2.0 / 25.8 GiB | `config.json` 写的是 `quant_method: awq`、`bits: 4`，**与仓库名里的「6Bit」不符**，且没有 `config_groups` 可核 | ❌ 不值得：精度存疑，而且 dense 27B 已因速度（4.9 token/s）出局 |

### 12.3 建议的测试顺序（如果要做 B 层）

按「能测 + 能回答新问题 + 便宜」排序：

1. **`Qwen2.5-Coder-7B-Instruct` 补全题集**（约 20 分钟，最便宜）——把一个已有的 quick 数据点变成可比较的全题集数据。
2. **`GLM-4.7-Flash`（cyankiwi 4-bit）**（约 25 分钟）——**唯一成本合适的非 Qwen 家族模型**，验证 A 层的结论是不是只对 Qwen 成立。
3. **`Ministral-3-14B`（cyankiwi 4-bit）**（约 20 分钟）——中尺寸 dense 的代表，看「dense 在 9–15B 档」能不能同时拿到低基线与可接受的速度。
4. **`Seed-OSS-36B-Instruct`（4-bit）**（约 25 分钟）——大尺寸 dense 的代表，与 30B 级 MoE 直接对照。

其余（`gemma-4-12B`、`Devstral-Small-2-24B`、`Kimi-Linear-48B`）留作第二轮；
`granite-4.2-30b` 与 `DeepSeek-Coder-V2-Lite` 在没有可用量化格式之前不必考虑。

**一句话总结**：备选候选的问题从来不是「值不值得测」，而是「有没有能在 ROCm + gfx1100 上跑的权重格式」——
10 个里有 3 个（granite、DeepSeek-Coder-V2-Lite、以及命名与配置不符的 Qwen3.6-27B-6Bit）就卡在这里。

### 12.4 实测结果与结论（2026-09-28）

按 §12.3 的建议顺序实际跑了 7 个候选（含量化对照），结果如下：

| 候选 | 结果 |
| --- | --- |
| `Qwen2.5-Coder-7B-Instruct`（BF16） | ✅ `S_b` **0.452**（运行 `20260928-003043-…`） |
| `Ministral-3-14B-Instruct-2512`（AWQ 4-bit） | ✅ `S_b` **0.476**（`20260928-073818-…`） |
| `gemma-4-12B-it`（BF16 权重，服务用 fp16） | ✅ `S_b` **0.679**——**备选里最高**，全场第二 |
| `Devstral-Small-2-24B`（AWQ 4-bit） | ✅ `S_b` **0.434**（`20260928-085636-…`） |
| `Qwen3-30B-A3B-Instruct-2507`（GPTQ-Int4） | ✅ 跑了两遍：**0.560** 与 **0.5845**（均值 0.572），对照同模型 AWQ 的 0.588 |
| `GLM-4.7-Flash`（AWQ 4-bit） | ❌ 不可服务：自带分词器与 transformers 5.15 不兼容（见 [`../failures/serving-stack.md`](serving-stack.md) 的 **P4**） |
| `Kimi-Linear-48B-A3B`（AWQ 4-bit） | ❌ 同一个根因 |

**三条结论**：

1. **门槛最低的挑战者不是能力最强的模型。** 按「反超 4B 方案所需 `S_a`」排，
   `Devstral-Small-2-24B`（0.580）、`Qwen2.5-Coder-7B`（0.597）、`Ministral-3-14B`（0.620）
   排在前三，而新一代 35B MoE 是 0.730–0.734。完整表见
   [`../decisions/0002-model-choice.md`](0002-model-choice.md)。
2. **量化对照没有给出显著差异**：同模型同 4-bit，AWQ 0.588，GPTQ 两次 0.560/0.5845（均值 0.572），
   差 0.016 **小于这两次自己之间的波动 0.0245**。所以差异不显著；GPTQ 唯一确定更差的是**稳定性**
   （请求失败 6 次与 4 次，AWQ 只有 1 次）。这条顺便提供了一个**全题集的重复性样本**。
3. **备选里的覆盖缺口集中在「自带代码」与「量化格式」两类**：
   `GLM-4.7-Flash`、`Kimi-Linear-48B` 卡在 transformers 版本；
   `granite-4.2-30b`、`DeepSeek-Coder-V2-Lite` 卡在没有可用的量化格式（§12.2）。
   这两类都不是「模型不好」，而是**服务栈的限制**——换镜像或换服务栈才可能解除。

**没跑到的两个候选**：`Qwen3.6-27B-AWQ-6Bit`（命名与配置不符，且 dense 已因速度出局）、
B 层之外的 `Qwen2.5-Coder-32B-Instruct` 与 `Qwen3-32B-AWQ`（只有 quick 分数，没补全题集）。
