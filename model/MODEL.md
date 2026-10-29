# MODEL.md

> 模板。所填内容须与 `manifest.json`、`REPORT.md` 第 3 节一致。
>
> **本文件未如实填写时，增益项 40 分不得分**（评分细则 2.4）。

---

## 1. 模型

| 项           | 内容                                    |
| ------------ | --------------------------------------- |
| 模型名称     | Qwen/Qwen3-8B                           |
| 来源         | https://huggingface.co/Qwen/Qwen3-8B    |
| 版本号 / SHA | `REPLACE_WITH_COMMIT_SHA`               |
| 权重校验和   | `sha256: ...`（无版本号时必填）         |
| 参数量       | 8B                                      |
| 许可证       | Apache-2.0                              |

**必须是可本地部署的开源权重。** 决赛在断网沙箱中运行，商用 API 在评分细则 2.1 与
2.3 两条上均不成立，全部运行类得分无法产生。

## 2. 量化与显存

| 项           | 内容                        |
| ------------ | --------------------------- |
| 量化方式     | 无 / AWQ / GPTQ / GGUF-Q4_K_M / ... |
| 量化工具与版本 |                           |
| **实测显存占用** | `__ GB`（单卡，加载后稳态） |
| 测量方式     | `rocm-smi --showmemuse`     |
| 测量硬件     | W7900 / R9700               |

**上限单卡 32 GB，不允许跨卡。** 验证阶段的云资源有 48 GB，但超出 32 GB 的配置在决赛
无法复现，风险自负。

参照：32B 模型 FP16 约 64 GB（装不下），4-bit 量化后约 18 GB；7B 模型 FP16 约 14 GB。

## 3. 上下文配置

| 项                 | 值    |
| ------------------ | ----- |
| `max_model_len`    | 32768 |
| 默认 Workflow 单次输出上限 | 16384 |
| 单题时限 / baseline 请求上限 | 900 / 840 秒 |
| 共享思考设置 | manifest.json 显式设置 enable_thinking=true，baseline 与方案共享 |
| 默认 Workflow temperature | 0.0 |
| RoPE 外推方式      | 无 / YaRN factor=... |

分支 `refactor/adaptive-orchestration` 的 `run.sh` 默认 `adaptive_verify`；
`main` 与封存版本仍默认 `single_generate`。`adaptive_verify` 使用短分析、首稿、
独立检查器构造/复核、结构检查与一次受限修复；模型、量化和推理服务仍未最终确定，
本文件其他占位内容尚未完成实测填写。

当前分支的实际工具与角色：

- 工具：`interface_check`、`vivado_lint`、`vivado_synth`、`submit_answer`、`finish_task`。
- 角色 profile：分析者 `small`，作者/构造/复核/归因 `large`；`small` 仅在 `guided_verify` 的抽象特征 planner 中启用，目标为
  `Nellyw888/VeriReason-Qwen2.5-1.5b-RTLCoder-Verilog-GRPO-reasoning-tb`，由远端
  llama.cpp 在 `127.0.0.1:8011` 提供（GGUF F16，约 3.1 GB）。
  可用 `VERI_GGUF=... ./serve/start_verireason.sh` 启动；官方默认 `serve/start.sh` 不启动 8011。`adaptive_verify` 等
  使用完整题面的分析请求会触发该模型的代码倾向，因此这些配置保持 `small.enabled: false`。许可证仍为空，
  `manifest.json` 的 `auxiliary_models` 尚未声明。HF API 复核 revision `a171280d7f001fef819e90218e008a887f1292c7`，`license` 为空，
两个 safetensors 合计约 6.2 GB（F32）；flat plan 输出格式未实测。当前未写入 `auxiliary_models`。小模型服务已在 8011 运行，flat plan 已用真实请求验证；
但正式封存前仍须补齐许可证与 manifest 声明。
正式提交前必须补齐许可证、manifest 声明、权重部署并验证 flat plan 格式。
- 作者阶段可选有界工具循环（`tool_steps` 默认 0）；`config/adaptive_tools.yaml` 设为 2，
  每步消耗一次 completion。提交工具只登记候选，`solution.v` 由宿主原子发布。
- `manifest.json` 的 `agent.skills` 只列自动准入的 `rtl-sequential-state-update`。
  路由还可能提出 `rtl-fsm-state-output`、`rtl-combinational-completeness`、
  `rtl-width-signed-arithmetic`，但它们在 catalog 中为 `frozen_rejected_fixed_ab`，
  会被自动准入拒绝，不会发送；`rtl-sequential-state-update-v3` 是 candidate，同样不列。

云端开发验证（2026-10-28，非正式成绩）：远端 llama.cpp `Qwen3.8-27B-Q4_K_M` + MTP，
`single_generate` 约 9.6 秒但本次输出 `xvlog` 失败；`repair_loop` 约 87.4 秒，
首稿 lint 失败、修复稿 lint/综合通过。该 27B 不是本文件声明的 Qwen3-8B，
结果只作开发验证，不用于正式能力或成绩声明。

开发验证使用远端 llama.cpp 服务（请求别名 `qwen38-27b-q4-k-m`，端口 8010），
该服务不属于正式 manifest 声明。可选开发预设 `config/design_verify_hip.yaml` 连接已有 HIP + MTP3 服务
（请求别名 `qwen38-27b-q4-k-m`，端口 8010），上下文上限 65536，规划及评审
输出上限 16384，RTL 与检查器生成/评审上限 32768。该预设显式采用 llama.cpp
分词协议，关闭服务端 JSON Schema 约束，保留本地严格校验；所有调用仍读取
manifest 的同一 generation。输出上限包含思考，且受剩余上下文和 900 秒时限限制。
此开发预设未替换 manifest 中的正式提交模板，也不代表启动脚本已部署 HIP 或扩大
token 上限后的真实模型验证已完成；正式采用前须同步填写模型、预测头和服务声明。
另有自适应工作流的可选预设 `config/adaptive_verify.yaml` 与 `config/adaptive_hip.yaml`，
使用 9600 秒宽预算/120 秒收尾和 8 个阶段额度；路由、检查器与预算边界见
[自适应工作流](../docs/adaptive.md)。该预算属于研究验证口径，不能当作 900 秒赛事预算成绩。

**本项不受统一约束，但必须如实声明。**

上下文长度对结果的影响是一阶的，不是可以含糊带过的参数。已有评测记录到：同一推理
模型在 8 K 输出窗口下因截断表现很差，放宽到 16 K 后通过率大幅跳升，而截断样本仅占
5.31%；另一项工作中统一的 4096 输出上限静默截断了七个受评模型中的三个，放宽后有
模型从第五名升至第一。

**基线运行必须使用与方案完全相同的上下文配置**，否则归一化增益无法作有效比较。

## 4. 推理栈

| 项           | 内容                    |
| ------------ | ----------------------- |
| 后端         | vLLM / llama.cpp / SGLang / ... |
| 版本         |                         |
| 常驻服务入口 | `./serve/start.sh`，就绪后返回 |
| 关键启动参数 | 见 `serve/vllm.sh`      |
| 并发策略     | 每卡一实例 / 单实例批处理 / ... |

默认启动按 `VRAM_BUDGET_GB=30` 与实际卡容量计算显存比例；显式 `GPU_UTIL` 可覆盖。
`serve/` 基于上游 `f7a8bd4` 的官方示例：显存比例保留两位小数，服务模型名取本地权重目录名。
`MODEL_NAME` 与 `LLM_MODEL` 只用于请求侧，应与该名称一致；启动脚本不读取 `VLLM_EXTRA_ARGS`，
固定使用 `--no-enable-log-requests`。Burr 分支增加可选 `ENABLE_TOOL_CALLING=1`，
启用 `--enable-auto-tool-choice --tool-call-parser hermes`（解析器可显式覆盖）；内置四条流程不要求启用。
辅助结构化请求与 RTL 生成共用 manifest 的 generation 设置，默认使用 JSON Schema 约束解码和严格校验。
非 baseline 等价请求通过服务 `/tokenize` 计算输出余量，不再加载本地 tokenizer。`manifest.json` 中的 vLLM 后端、启动入口与端口仍适用。启动参数仍是待测示例，
实际显存峰值和 vLLM 版本尚未验证，不能把默认预算写成实测值。

## 5. 微调

**未微调**填「否」，本节结束。

微调则以下各项均为必填（评分细则 2.5，缺失则增益项不得分）：

| 项             | 内容 |
| -------------- | ---- |
| 基座模型       |      |
| 微调方式       | 全参 / LoRA / QLoRA，rank、学习率、轮数 |
| 训练数据来源   | 须可核查                                |
| 训练数据规模   |                                         |
| **微调权重开源地址** | 链接须可达                        |

## 6. 辅助模型

当前 `manifest.json` 的 `auxiliary_models` 为空，正式方案未部署辅助模型。

### 6.1 Guided Verify 小模型候选（provisional）

| 项 | 内容 |
| --- | --- |
| 名称 | `Nellyw888/VeriReason-Qwen2.5-1.5b-RTLCoder-Verilog-GRPO-reasoning-tb` |
| 基座 | Qwen/Qwen2.5-Coder-1.5B-Instruct |
| Revision | `a171280d7f001fef819e90218e008a887f1292c7` |
| 参数量 | 约 1.54B |
| 用途 | Guided Verify 的 plan 阶段：选择 skill/知识和方法 |
| 运行位置 | 与主模型同一实例，独立 profile |
| 显存 | 公开 safetensors 合计约 6.2 GB（F32）；运行时开销待实测 |
| 许可证 | HF 模型卡未声明（`license: null`） |

该候选已在分支配置中启用，`manifest.json` 的 `auxiliary_models` 仍为空。
配置中已按用户要求启用该 profile；但 HF 许可证仍为空、flat plan 格式未实测、manifest 未声明。
许可证与 manifest 补齐前不得作为正式提交版本，启用状态记录在配置注释中。
分支配置中的 `small` profile 已启用，但 `auxiliary_models` 未声明；正式提交前必须补名称、
基座、参数量、用途、运行位置和显存，并确认与主模型合计不超过 32 GB。
后续使用判别、打分、检索或嵌入模型时须声明名称、基座、参数量、用途、运行位置和显存；
主模型、辅助模型与运行开销合计不得超过单卡 32 GB。经训练的辅助模型须声明训练方式和数据，
权重随封存版本提供给赛事方复现，不要求公开发布。

## 7. 声明

- [ ] 上述模型为可本地部署的开源权重，非商用 API
- [ ] 实测显存占用不超过 32 GB，单卡运行
- [ ] `run_baseline.sh` 使用与 `run.sh` 完全相同的模型、量化方式与上下文配置
- [ ] 若经微调，权重已开源且链接可达
- [ ] 本文件内容与 `manifest.json`、`REPORT.md` 一致
