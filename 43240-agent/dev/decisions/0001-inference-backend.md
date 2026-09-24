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
