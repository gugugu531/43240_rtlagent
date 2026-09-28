# 0001 推理后端的选择

| 项 | 内容 |
| --- | --- |
| 状态 | **待定**——比赛不限定后端；vLLM 已在两代云镜像上跑通，**最终用哪个后端尚未决定** |
| 记录日期 | 2026-09-22 |
| 最后更新 | 2026-09-28 |
| 相关文件 | `../../serve/vllm.sh`、`../../manifest.json`、`../../model/MODEL.md`、[`../remote/remote_vllm.sh`](../remote/remote_vllm.sh) |
| 相关失败 | [`../failures/serving-stack.md`](../failures/serving-stack.md)（启动参数、量化格式、词表） |

## 结论（最新）

1. **比赛没有规定推理后端**，vLLM 只是示例方案的默认值；后端由队伍自选，但必须满足下面
   三条硬性要求。
2. **验证阶段实际用的是 vLLM**，在两代云镜像上都跑通了（0.16.1 与 0.27.0），
   量化格式覆盖 BF16、AWQ、GPTQ、原生 MXFP4（细节见「依据」）。
3. **仍未决定的**：最终提交用哪个后端；以及决赛硬件（R9700 / gfx1201）上的可用性——
   官方基础镜像发布后需要实测。

## 硬性要求（任何后端都要满足）

1. **接口**：提供 OpenAI 兼容的 `/v1/chat/completions`（`example/baseline.py` 第 13 行）；
   `baseline.py` 还会调 `/v1/models` 记录模型名，这个接口失败时会退回 `"default"`，最好也提供。
2. **运行条件**：单卡显存 32 GB 以内、**断网**运行、基于官方基础镜像构建；决赛硬件是
   AMD Radeon AI PRO R9700（gfx1201，ROCm），后端必须能在 ROCm 上运行（`SCORING.md` 第 1.1 节）。
3. **一致性**：方案与基线必须使用同一个推理服务，且与 `MODEL.md` 的声明一致（`SCORING.md` 第 3.2 节）。

## 对比表

| 后端 | OpenAI 兼容接口 | ROCm 支持 | 我们验证到什么程度 | 备注 |
| --- | --- | --- | --- | --- |
| **vLLM** | 有 | 有 | **已在两代云镜像上跑通全题集**（0.16.1 / 0.27.0，W7900 gfx1100） | 示例方案的默认值；量化格式与内核限制最多，见 [`../failures/serving-stack.md`](../failures/serving-stack.md) |
| SGLang | 有 | 有 | 未验证 | 需注意 gfx1201 上的算子库问题 |
| llama.cpp（`llama-server`） | 有 | 有 | 未验证 | GGUF 量化路径与上面两者不同；显存占用更低但吞吐未知 |

`example/serve/README.md`「跨代架构的已知问题」提到：部分框架在 gfx1201 上会把 FP8 悄悄转成
FP32、部分算子库不可用——选型时要留意（本赛道确实是现实问题，不是理论风险）。

## 依据

### 官方文档出处

| 出处 | 内容 |
| --- | --- |
| `README.md` 第 42 行、`SCORING.md` 第 12 行 | 方案须包含「推理栈」，没有指定用哪个后端 |
| `example/model/MODEL.md` 第 59 行 | 推理后端一栏为 `vLLM / llama.cpp / SGLang / ...` |
| `REPORT_TEMPLATE.md` 第 80 行 | 推理后端一栏为 `[vLLM / llama.cpp]` |
| `example/baseline.py` 第 11 行 | 「队伍决定模型、量化、推理后端与服务配置」 |
| `SCORING.md` 第 231 行、`docs/FAQ.md` 第 173 行 | 同一模型在不同后端下吞吐可差数倍，选择后端与调服务配置本身就是考察的工程能力 |

### 实测：量化格式与内核限制

| 事项 | 结论 | 现在还有效吗 |
| --- | --- | --- |
| AWQ（group_size=32）默认 bf16 起不来 | 加 `--dtype float16` 走 Exllama 路径 | 有效（针对 WNA16 路径），但**不能套用到 MLA 模型** |
| 旧镜像（vLLM 0.16.1）不认 `qwen3_5` | 换模板后解决——vLLM 0.27.0 的注册表里有这些架构 | 已解决，见 [`../failures/serving-stack.md`](../failures/serving-stack.md) 的 **S2** |
| gpt-oss 需要预置词表 | 已找到可复现方案（含文件名规则），断网可用 | 已解决；**提交层面仍待办**（P2） |
| `serve/vllm.sh` 的 `--disable-log-requests` 在 0.27 上不存在 | 去掉即可；它是提交文件，需团队确认 | **未解决**，见 P2 |
| MLA 类模型不能强加 fp16 | dtype 按模型类型给 | 已解决（S5） |

### 实测：精度与速度（同一个 4B 模型的三档）

| 精度 | 题集得分 | 权重显存 | tps（并发 1） |
| --- | ---: | ---: | ---: |
| BF16 | 0.3935 | 7.67 GiB | 52.0 |
| AWQ 8-bit | 0.3923 | 5.41 GiB | **99.3** |
| AWQ 4-bit | 0.3432 | 3.45 GiB | 34.7 |

**8-bit 与 BF16 在噪声内相同且快近一倍；4-bit 既掉分又更慢。** 所以 4-bit 只应作为
「装不下时的妥协」，不能当默认选择。运行编号见 [`../notes/2026-09-25-screening-results.md`](../notes/2026-09-25-screening-results.md)。

### 实测：服务参数对基线的影响

- **混合思考模型必须显式关思考**：否则思考写进 `content` 并吃掉 `baseline.py` 的 8192 上限，
  基线变成截断主导。同样 63 题上基线从 0.486 变到 0.695（加 `--reasoning-parser qwen3` 那次），
  可见开关的影响之大。细节见 [`../failures/thinking-in-content.md`](../failures/thinking-in-content.md)。
- **`gpu_memory_utilization` 要按「权重 + KV + 开销」定**：给 8B 调的 0.62 装不下 22.41 GiB
  的 35B MoE（报 `No available memory for the cache blocks`），实测 0.85 可用。
- 速度与显存：Qwen3-8B BF16 单路约 26 token/秒，MoE 4 位约 79 token/秒；AWQ 在 W7900 上偏慢。

### 平台计费

1 credit = 1 GPU 小时。历次会话的用量见 [`../notes/`](../notes/) 里各次记录。

## 未决问题

| # | 事项 | 卡在哪 |
| --- | --- | --- |
| 1 | 最终用哪个后端 | 需要团队决定；目前只有 vLLM 有实测 |
| 2 | 决赛硬件（R9700 / gfx1201）可用性 | 官方基础镜像发布后才能实测；**当前拿不到该硬件** |
| 3 | `serve/vllm.sh` 的启动参数与新镜像匹配 | 提交文件，需团队确认后改（[`../failures/serving-stack.md`](../failures/serving-stack.md) 的 P2） |
| 4 | 远端脚本与后端解耦 | 计划把 `remote_vllm.sh` 改成 `remote_serve.sh`：启动脚本由 `REMOTE_SERVE_SCRIPT` 指定（默认取 `manifest.json` 的 `serving.start_command`），只统一传 `MODEL`、`PORT` 等通用参数，后端专用参数走 `REMOTE_SERVE_ENV`；变量名与提示文字里的「vLLM」改为「推理服务」 |

## 决定之后要同步修改

- 本文「状态」一栏与选择理由（附 `../experiments/` 的运行编号）
- `../../serve/` 的启动脚本、`../../manifest.json` 的 `serving` 部分、`../../model/MODEL.md` 第 4 节
- `../../README.md` 第 5 节

## 变更记录

| 日期 | 变更 |
| --- | --- |
| 2026-09-28 | 按新的决策文档结构重组：合并 09-24 / 09-25 两段「实测进展」到「依据」；**删除已被取代的结论**（「这份 vLLM 不认 2026 年新架构」「要测新模型需要换镜像且两条路都没验证」「gpt-oss 词表阻塞」），它们现已在 [`../failures/serving-stack.md`](../failures/serving-stack.md) 里按状态记录。重组前的版本见 commit `6ad80ad` |
