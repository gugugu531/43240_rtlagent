# 新对话交接：RTL Agent 当前状态、远端实验与后续消融

类型：交接快照与实验路线。日期：2026-10-13。最后远端只读检查：14:59 JST。
本文帮助新对话接手，不是授权自动启动全部实验；后续状态以真实文件、进程和新记录为准。
所有相对路径如无特别说明，均相对于 `43240-agent/`。

## 先读这段：现在停在哪里

我们已实现方案 A `evidence_repair`，跑过真实 Qwen3-8B + 本机 Vivado，不只是 mock 测试。
完整 quick-34、五题 thinking 对照和 11 题采样对照已经完成。**当前没有等待继续的模型实验。**
最近 11 题对照共 44 项有效评分；原会话被旧定时器中断，后来只补 3 个取消样本，合并完成。
推荐采样下 Agent 均值 0.7636、L3 为 8/11；greedy 为 0.3818、4/11。
这是定向开发集、每题一次，不是泛化或稳定性证明，也不是 RAG 的效果。

用户已取消今后整轮 5 小时/90 分钟等固定截止。保留单题/请求超时，完成或报错仍清理推理服务。
14:59 JST 核实：远端 GPU 显存 0 MiB、利用率 0%、无 vLLM/watchdog；本地实验、连接和阻止
休眠服务均 inactive，无本地保护 timer。**AutoDL 实例未由脚本关机，平台是否仍计费需在网页确认。**

15 张知识卡片和确定性检索已在开发区建立，尚未进入 Agent，也未做独立 HDL 执行验证。
**E1/E2 尚未执行。** 下一步先核对状态、设计必要接口与对照，再实施，不直接重跑旧 44 项。

## 1. 用户目标、工作区与协作边界

用户希望借鉴硬件/coding Agent 论文和开源工程，理解模块用途而非逐行阅读，以小而可解释的消融
逐步提高无官方 testbench 条件下的 RTL 解题效果；前四天教程基本读完。

| 项目 | 位置或现状 |
| --- | --- |
| 工作区 | `/home/cloudia/FPGACHINA` |
| 主仓库 | `/home/cloudia/FPGACHINA/AMD_SocChina_2026` |
| Agent 根目录 | `/home/cloudia/FPGACHINA/AMD_SocChina_2026/43240-agent` |
| 分支 | `docs/agent-research` |
| 当前 HEAD | `d03f0fddf1b6cedca9706a752a39f1c10eb0db2f` |
| Git 状态 | 大量修改与 untracked 文件，未统一提交；HEAD 不能代表实验源码全貌 |
| 本地 Vivado | `/home/cloudia/Downloads/FPGAVitis/2026.1/Vivado/settings64.sh` |
| Ross 仓库 | `/home/cloudia/FPGACHINA/ross-ai-assistant`，独立 Git 仓库 |
| 本机时区 | Asia/Tokyo，JST；远端为 CST，北京时间，比 JST 慢 1 小时 |

接手前读主仓库 `AGENTS.md` 和 [开发规范](../conventions.md)。特别注意：

- 保留脏工作区，不 reset/checkout 覆盖、不要自动 pull 引发冲突，也不要擅自 commit/push。
- 主办方原始根文档、`docs/`、`selftest/`、`example/` 只读；`baseline.py` 与 `run_baseline.sh` 不改。
- 正式代码不得导入 dev 或 selftest。题面/接口可见；官方 TB、参考 RTL、judge 等级与波形真值
  只能用于隔离的开发评测，不能进入正式提示、RAG、反思记忆或候选选择。
- 模型自评分、反思、检索建议、自建测试都不等于官方正确性证据。
- 阶段实施前先给出架构、函数接口、对照和验收计划。本文后续路线是建议，不表示已经实现或授权全部运行。
- 不打印/提交 `remote.env`、API key、Cookie、令牌、私钥、完整环境变量或历史含密钥配置。
- 原始 runs、生成报告与历史失败不覆盖；新变体用新配置/运行目录，并记录来源。

## 2. 实际已经实现的能力：不要把旧规划表当现状

| 能力 | 当前实现程度 | 关键位置/仍缺什么 |
| --- | --- | --- |
| 权威题面/接口上下文 | 已实现 | `TaskSpec` 读取 prompt/interface，`assemble_messages()` 拼装；不读 TB/ref |
| ContextAssembler | **未实现独立完整组件** | 目前是 `agent/prompts/builder.py` 的拼装函数，无真实 tokenizer 裁剪/优先级装箱 |
| token 记录 | 部分实现 | 模型返回 usage 入 trace，缺失保留未知；没有生成前准确输入 token 计算/整题累计额度控制 |
| 直接生成 | 已实现 | `single_generate` 沿用官方 baseline 提示/提取；不等于 E1 的同提示无修复对照 |
| 接口/编译/综合 | 已实现 | `InterfaceNode`、`LintNode`、`SynthNode`，由 `RunContext` 与 Supervisor 管理 |
| 结构化诊断反馈 | 部分实现 | `StructuredFeedbackNode` 有证据编号、阶段、归因、错误码和截断摘要；尚非完整位置/AST 映射 Diagnostic |
| 最多一次代码/提取修复 | 已实现 | `evidence_repair`，另有受限请求重试；“一次修复”不代表整题最多一次 API 请求 |
| 候选保留、选择、停止 | 已实现 | 保存首份/修复候选，按自身检查证据排序，受时间与调用数限制；不保证功能不被修坏 |
| ICL | 未在方案 A 中启用 | 还没有正式的示例装配接口；未来独立插入，不是开配置即有 |
| self-planning / plan 字段 | **未实现** | `GenerateInput` 目前只有 task/feedback/parent/round；`plan` 只是讨论中的预留设想 |
| TCRG | 未实现 | 完整图规划/执行需另外设计，测试相关部分缺正式权威 oracle |
| Agentless 分层定位 | 未实现 | 当前短模块优先完整输入；AST/块定位尚未接入 |
| 错误码卡片检索 | 开发原型已实现 | `dev/tools/knowledge_lookup.py`；不属于当前求解路径 |
| 完整 RAG 闭环 | 未实现 | 缺独立节点、实际 token 装配、合规提交资料和有/无检索实验 |
| RepoCoder 两轮检索 | 未实现 | 不是现有规则检索的配置开关 |
| Reflexion / ToT / AST-WT | 未实现 | 候选保存不等于这些完整框架 |
| patch 投票/权威回归测试 | 正式流程未实现 | 无官方 TB 时不能按隐藏回归结果投票；自身合规检查也不能冒充功能 oracle |
| SFT/LoRA/蒸馏 | 未实施 | 未建立本项目训练数据与独立验证流程 |

补充：当前名为 `lint` 的节点执行 `xvlog --sv` 和 `xelab`，不是 Ross 的
`synth_design -lint`；错误码和工具来源不能混用。接口解析有来源与置信度，不是完备 Verilog 解析器。

### 方案 A 主路径

```text
题面 + 接口 → 生成 → 提取/保存候选 → 接口 → xvlog/xelab → 综合
                     │                │          │          │
                     └─提取失败───────┴─自身代码错误─────────┘
                                      ↓
                              结构化反馈 → 最多一次修复
                                      ↓
                               重新检查 + 确定性选择
```

环境错误、未知失败和预算不足不能包装成 RTL 缺陷继续盲修；通过综合即停止，不代表功能正确。
正式代码关键入口：

- `run.sh` → `agent/core/supervision.py` / `runner.py` / `context.py`。
- `agent/workflows/evidence_repair.py`：当前方案 A；继承 `repair_loop.py` 的受限循环。
- `agent/nodes/generate.py`、`extract.py` / `extraction.py`、`check.py`、`feedback.py`。
- `agent/prompts/builder.py`：题面、接口、当前候选和反馈拼装；方案 A 的 `use_skills=False`。
- `agent/services/vivado.py`：工具执行与失败归因；`agent/recording/`：证据和指标。
- `dev/tools/run.py` / `experiment.py`：统一开发实验，官方 judge 只作隔离指标，不回传求解器。

## 3. 已完成实验及其可信范围

这里的系数均值不是普通二值正确率；使用官方 L0/L1/L2/L3 对应的 0/0.2/0.7/1 聚合。
L3 数量另外报告。低分、模型/环境失败和取消分别记录，不能把取消直接当作算法 L0。

### 3.1 完整 quick-34

68 个有效样本，Agent/baseline 各 34；Agent 均值 0.5294，baseline 0.5647，增益比约 0.9375。
Agent 2 胜、5 负、27 平；L3 为 17/34 对 18/34。Agent 有更高时间/token 成本。
这是当时的原采样/提示配置，不与后来 11 题单次结果混成一张“整体提升”成绩。

- 原记录：`dev/runs/20261012-225403-autodl-qwen3-8b-a-fixed-quick34-460c1d2a`，取消后保留 58 项。
- 5 题补跑：`dev/runs/20261013-105000-autodl-qwen3-8b-a-fixed-quick34-resume-4e464cbc`。
- 完整派生摘要在补跑目录 `combined/`，含 summary/metrics/provenance。
- [完整报告](../experiments/20261013-105000-autodl-qwen3-8b-a-fixed-quick34-resume-4e464cbc.md)。

更早商用 API/断连的 quick 子集结果不是完整、稳定的模型基准，不用于替代以上数据。

### 3.2 五题 thinking/采样诊断

会话：`dev/runs/20261013-generation-diagnostic-five-retry1`，三组共 30 项有效评分。

| 设置 | Agent 系数均值 | baseline 系数均值 | Agent L3 |
| --- | ---: | ---: | ---: |
| thinking 开，greedy | 0.24 | 0.60 | 1/5 |
| thinking 关，greedy | 0.20 | 0.12 | 0/5 |
| thinking 开，推荐采样 | 0.68 | 0.52 | 3/5 |

关闭 thinking 很快，但五题 Agent 都停在 L1。此轮可比较同一 greedy 下 thinking 开/关；
推荐配方同时改变多个采样参数，不是 temperature 单独消融。
[五题结论和原始 run ID](2026-10-13-generation-diagnostic-results.md)。
早先 `20261013-generation-diagnostic-five` 是预检失败的保留记录，不是有效模型实验。

### 3.3 最近完成：11 题，两个 thinking-on 配方

| 设置 | Agent L0/L1/L2/L3 | Agent 均值 | baseline 均值 | Agent 截断/调用 | Agent 输出 tokens |
| --- | --- | ---: | ---: | ---: | ---: |
| greedy | 6/1/0/4 | 0.3818 | 0.4727 | 7/19 | 75748 |
| 推荐采样 | 1/2/0/8 | 0.7636 | 0.4364 | 0/15 | 43766 |

与本轮 greedy 比，Agent 6 题等级改善、1 题下降、4 题不变。两组正式源码、题面和首次消息一致。
第一组额外网关传输重试 1 次；推荐组已完成的 26 次模型请求无额外重试。
旧中断 baseline 请求未收到响应，单独保留，可能已消耗算力，不能从成本解释中隐去。

- 旧会话 `dev/runs/20261013-generation-diagnostic-eleven` 仍为 incomplete；不要改回 prepared。
- 原 greedy 组：`dev/runs/20261013-130343-gen11-think-on-greedy-cf560ace`。
- 原 sampled 组：`dev/runs/20261013-140530-gen11-think-on-sampled-f2835de9`，已有 19 项有效评分。
- 补跑：`dev/runs/20261013-144415-gen11-think-on-sampled-resume-eff670fa`，仅 3 项。
- **当前完整会话**：`dev/runs/20261013-generation-diagnostic-eleven-resume1`，状态 completed。
  `combined-sampled/` 保存 19+3 项汇总及来源；`think-on-sampled/` 保存合并审计和中断请求。
- [完成结论](2026-10-13-diagnostic-eleven-results.md)、[生成的逐题表](../experiments/20261013-generation-diagnostic-eleven-resume1.md)。

11 题名单在 `dev/configs/generation-diagnostic-eleven.yaml`：101、105、109、115、138 五道历史退步，
026、048 历史获益，017、041 稳定通过，043、058 共同失败（完整 ID 以配置为准）。
这是有意选择的开发集；quick-34 也已多次看过，不能叫未见验证集。

残留问题：026 首份 VRFC 10-1280、修复后 10-9336，适合研究反馈；105 与 138 是 L1、
自身编译/综合通过，错误检索不会自然触发。不能让正式流程读取 judge 来定位它们。

## 4. 远端连接与配置：可直接接手，但先只读检查

### 4.1 两边分别做什么

```text
本机：Agent + 调度 + Vivado + 隔离 judge
                  ↓ HTTP 127.0.0.1:18000/v1
本机：带审计的 model gateway
                  ↓ 127.0.0.1:18001
本机：socat relay → 每连接一条 SSH
                  ↓
AutoDL：127.0.0.1:8000 的 vLLM → Qwen3-8B / NVIDIA GPU
```

不是所有求解都在云端；熄屏可以继续，本机关机、休眠或长期断网会中断本机求解/判定链路。
本地 systemd 管理 relay/gateway，退出后可重连；POST 传输重试可能重复上游推理，需看审计。
服务只监听 loopback，不应对公网直接开放无鉴权 vLLM。

### 4.2 连接与模型快照

```bash
ssh -p 11071 root@connect.westc.seetacloud.com
```

认证已配置在本机 SSH 中，不需要把私钥或密码贴进对话。实例重建后应重新确认地址/端口，
不要盲目忽略主机密钥变化。

| 配置 | 已核对值 |
| --- | --- |
| 配置文件 | `dev/tools/remote/remote.env`，不要展示整个文件 |
| REMOTE_HOST / SSH_PORT | `root@connect.westc.seetacloud.com` / `11071` |
| REMOTE_DIR | `~/fpgachina2026-remote`，以远端 root 展开 |
| REMOTE_MODEL | `/root/autodl-tmp/models/Qwen3-8B` |
| REMOTE_ACTIVATE | `source /root/autodl-tmp/venvs/vllm011/bin/activate` |
| 远端/本地/relay 端口 | `8000` / `18000` / `18001` |
| TUNNEL_MODE | `relay` |
| REMOTE_MAX_LEN / GPU_UTIL | `32768` / `0.85` |
| REMOTE_STRIP_ARGS | `--disable-log-requests`，只剥离远端副本，仓库 serve 脚本不改 |
| REMOTE_EXTRA_ENV | `CUDA_VISIBLE_DEVICES=0 VLLM_EXTRA_ARGS='--reasoning-parser qwen3'` |
| 远端软件 | Python 3.12.3、vLLM 0.11.0、PyTorch 2.8.0+cu128 |
| GPU | NVIDIA vGPU-48GB，49140 MiB；历史驱动 580.76.05 |

模型下载固定提交为 `b968826d9c46dd6066d109eabc6255188de91218`。9 个权重、config、generation_config、
tokenizer 文件的实测 SHA256 在上述完成会话 `remote-environment.json`，启动前重新比对。
`nvidia-smi` 的 CUDA Version 是驱动能力，不代表安装了 nvcc；当前推理环境已实际运行，不需因此重装。
模型和虚拟环境都放 `/root/autodl-tmp`，不要改到 30GB 系统盘或无确认地重复下载。

### 4.3 接手时安全只读检查

从 Agent 根目录执行，不要单独 `source remote.env`（其中旧平台 Cookie 行可能不能作为 shell 解析）：

```bash
cd /home/cloudia/FPGACHINA/AMD_SocChina_2026/43240-agent
git status --short
systemctl --user is-active fpgachina-autodl-experiment.service fpgachina-autodl-inhibit.service \
  fpgachina-model-gateway-18000.service fpgachina-transport-18000.service
systemctl --user list-timers 'fpgachina*' --all --no-pager
bash -c '. dev/tools/remote/_common.sh; rssh -o BatchMode=yes -o ConnectTimeout=10 \
  "date; nvidia-smi --query-gpu=name,memory.used,utilization.gpu --format=csv,noheader"'
```

`is-active` 在服务已停止时返回非零是正常现象，不能据此认定实验坏了。
SSH 失败时先报告原因，不自行租新机器、重装环境或重新下载模型。

### 4.4 管理入口与预算

| 文件 | 用途/限制 |
| --- | --- |
| `dev/tools/remote/_common.sh` | 安全读取配置、rssh、路径和模型探测 |
| `remote_vllm.sh start/wait/status/stop` | 远端模型生命周期；stop 尝试回收进程组 |
| `tunnel.sh up/down/status` | systemd relay 与 gateway；普通 up 不会自动启用推荐采样 |
| `model_gateway.py` | 270 秒内有界传输恢复、诊断配方与实际请求审计 |
| `autodl_session_limit.sh` | 默认 `AUTODL_SESSION_LIMIT_S=0`，撤销遗留 timer/watchdog |
| `autodl_generation_diagnostic.sh` | 已声明的冻结 5/11 题诊断启动、指纹核对、退出清理 |
| `autodl_quick34.sh` / `autodl_resume_quick34.sh` | 历史专用入口，不应为了接手再次运行已完成题集 |
| `generation_sweep.py` | prepare/verify/run，严格核对旧正式源码和预先声明题集 |
| `generation_resume.py` | 仅恢复特定第二组取消样本；非通用断点续跑，不能重抽低分 |
| `combine_runs.py` | 校验配置、正式源码与题面后生成派生汇总；不是重新执行 |

没有整轮时间上限，不代表无限重试，也不代表取消单题限制。最近实验参数：

- 每次输出最多 8192 tokens，单请求最多 300 秒，单题最多 360 秒，Agent 输出预留 20 秒。
- solve_jobs=1、metric_jobs=1；默认最多一次代码/提取修复，模型调用与传输重试分别记录。
- **8192 不是整题累计 token 上限。** 严格等累计 token 的消融需要先补计数和剩余额度控制。
- 无远端独立截止后，本机失联导致 EXIT 清理不可达时，远端可能继续驻留；恢复 SSH 后检查。
- `cloud.py` 是旧 Radeon Cloud 平台工具，不应用来关闭本次 AutoDL。模型停止不等于实例关机。

### 4.5 实际采样和“看配置却不一致”的陷阱

当前 `evidence_repair` 构造参数仍是 temperature=0、top_p=1，尚未改正式默认。
上轮推荐配方通过**开发网关**覆盖双方请求：

```text
MODEL_GATEWAY_PROFILE=think-on-sampled
enable_thinking=true
temperature=0.6, top_p=0.95, top_k=20, min_p=0
seed=20261013
```

启用时还必须给唯一 `MODEL_GATEWAY_AUDIT_DIR`，然后重建 gateway；已运行的 gateway 不会因为
当前 shell export 变量就换配方。启动服务的实际命令、gateway 请求 effective 字段才是证据。
`--reasoning-parser qwen3` 负责拆分 reasoning，不负责开启 thinking；硬开关在 chat template。
seed 现在写在 PROFILES 内，尚无安全独立 seed CLI。samples=3 不等于三个独立 seed。
diagnostic gateway 目前强制 max_tokens=8192；未来测输出上限/累计预算需要新可审计入口，不能绕过检查。

### 4.6 后台执行和手动暂停

最近使用 `systemd-run --user --collect --unit=fpgachina-autodl-experiment` 执行会话，
另用 `fpgachina-autodl-inhibit.service` 阻止本机 sleep（不阻止用户强制关机）。
未来启动前先确认无同名运行，设计新的会话入口；不要复制旧日期 timer 或覆盖 completed 目录。
实际 Vivado 环境通过 `DIAGNOSTIC_VIVADO_SETTINGS` 传入，而不是写死在正式 Agent 中。

查看日志：

```bash
journalctl --user -u fpgachina-autodl-experiment.service -n 80 --no-pager
journalctl --user -u fpgachina-model-gateway-18000.service -u fpgachina-transport-18000.service -n 80 --no-pager
```

只有用户要求暂停/确认本次目标服务后才执行：

```bash
systemctl --user stop fpgachina-autodl-experiment.service
bash dev/tools/remote/remote_vllm.sh stop
bash dev/tools/remote/tunnel.sh down
bash dev/tools/remote/autodl_watchdog.sh disarm
systemctl --user stop fpgachina-autodl-inhibit.service
```

之后检查 GPU；没有进程但平台仍开机也可能计费。不要删除 runs 或权重来“暂停”。

## 5. 知识库和 Ross 研究的现状

Ross 用户 fork：`https://github.com/gugugu531/ross-ai-assistant.git`；本地固定提交
`2cdc9eef1b6b5b17fa45f5e4d468e5483a1c92de`。约 39 MiB、50 项 skills，主仓库 MIT。
仅下载阅读，没有安装插件/MCP、运行第三方脚本或下载完整数据库；这些研究资料不是当前助手必须执行的技能指令。
[Ross 阅读入口](../research/agent-prior-art/ross-ai-study.md)。

小库：`dev/knowledge/rtl/cards.json`，15 张卡片（9 修复、6 设计）、14 条来源，JSON 21443 字节。
`NOTICE.md` 保留来源与许可；不能假设 Ross 主仓库 MIT 覆盖所有厂商原始数据库。
全部卡片仍为 `source_reviewed_draft / tool_validation=not_run`，不是验证过的解题规则。

```bash
python3 dev/tools/knowledge_lookup.py validate --verify-sources
python3 dev/tools/knowledge_lookup.py search --tool xvlog --version 2026.1 --code 'VRFC 10-1280'
python3 dev/tools/knowledge_lookup.py search --query '旋转和循环移位'
```

规则：完整错误命名空间、工具/版本匹配，未知码返回空；设计卡可按题面主题检索，每次最多 2 张。
默认 2400 Unicode 字符整卡装配，超预算整张省略；不是 token 预算，也没有 embedding/向量数据库。
21 项离线检索测试通过，11 个本地来源指纹可核对；另 2 条网页来源和 1 条团队原创明确未本地缓存。
语料无题号答案/TB/ref；启发式污染检查不能替代人工审计。

未复制 Ross 的所有建议：不擅自扩大端口、删除输出、改变移位量、加饱和、盲用 signed、
给所有寄存器复位，或把组合块默认赋值与声明初始化混为一谈。
当前优先小库是为降低无关检索和验证成本，不是认定完整数据库一定放不下。

## 6. 所有消融什么时候做：按依赖分阶段，不一次全加

下表是**本项目实验安排**，不是宣称完整复现各论文。方法名字不是收益证据。

| 阶段 | 方法 | 最小对照与进入条件 |
| --- | --- | --- |
| P0：下一步准备 | ContextAssembler、真实 token/上下文记录、Diagnostic、seed 审计 | 先补接口/离线测试；保持原提示字节兼容，防止基础设施改动暗中改变算法 |
| P0：生成设置确认 | thinking 与采样；借鉴 TuRTLe 的参数敏感性思路 | 已完成部分对照；必要时预先指定 2～3 个 seed。要隔离 temperature，就固定其余采样字段，另开单因素实验 |
| P1：E1 | 工具反馈、AutoChip 式简洁上下文、RTLFixer 式错误码短卡 RAG | 相同首次候选/证据，比较无修复、结构化修复、结构化修复+卡片；之后按需加原日志/仅错误码 |
| P2：E2 | ToT 的有限分支思想、两候选、MAGE 式候选检查点 | 同预算比较一候选修复/两候选确定性选择/审查修复；先宽度 2，不直接做完整 ToT 或多角色大搜索 |
| P3：廉价功能辅助 | 设计知识卡、ICL、RTLLM self-planning | E1 后可设计，主线先收尾 E2；三个方法各自单独对照，不同时开启；ICL 示例与评测划分隔离 |
| P3：Reflexion | 当前题内的一段短反思 | 结构化反馈 vs 同反馈+反思；额外调用计入预算，反思只是待验证假设，不以 judge 真值生成记忆 |
| P3/P4：E4 | AutoChip 历史压缩、TuRTLe 式上下文设置比较 | 先有准确 token 记录；分别测历史/日志策略与输入预算，不同时调 temperature/输出上限 |
| P4：E3 | Agentless 式块定位、AST 定位，再到 VerilogCoder AST-WT | 先验证源码位置→块的映射；波形追踪必须有合法自身测试/属性及可靠期望，不接官方隐藏 TB |
| P4：迭代检索 | RepoCoder 两轮 RAG | 单轮 RAG、反馈与预算稳定后，再比较单轮/两轮；仓库级或多模块任务确有检索需求再投入 |
| 更后：图规划/大搜索 | TCRG、完整 ToT、更多候选/角色 | 宽度 2 与轻量规划已显示收益，且合规功能证据和预算足够；无 TB 部分必须明确裁剪 |
| 更后：训练 | VerilogEval 相关 SFT 思路、LoRA、模型/Agent 蒸馏 | 有足量干净训练集、成功轨迹、独立验证与许可证确认后；作为模型级实验，固定 workflow 对比 |
| 不直接用于正式阶段 | 基于官方 TB 的 patch 投票/回归/状态真值调试 | 无合法 oracle 则不做该形式；可研究自建检查，但不得冒充官方证据 |

P3/P4 可按真实瓶颈选择，不要求把论文名单逐项跑一遍。若主要剩余问题是功能误解，
题面检查单可能比继续扩充编译错误卡更优先；若错误卡根本无命中，先解决覆盖与适用性。

### 6.1 最先执行的 E1，建议三组

- A0：使用**方案 A 同一首次提示/提取**，保留首份候选，不修复。
- A1：同样起点 + 自身工具失败的结构化反馈 + 最多一次修复。
- A2：A1 + 1～2 张错误码短指南；无命中退回 A1。

A1−A0 衡量修复策略增量，A2−A1 衡量检索增量。A1−A0 仍包含额外模型调用的收益，
不能据此单独宣称“错误反馈优于重采样”；若要隔离信息收益，再加同调用/预算、无具体错误信息
的重试组。官方 baseline 提示不同，不可代替 A0。现有 `single_generate` 也不是自动正确的 A0。

先做受控修复重放：保存并共享首次候选、工具证据、来源与成本，在相同剩余预算比较 A1/A2；
不根据隐藏分数挑首份答案，再做端到端确认。若用已分析题目定位问题，只能称诊断实验。
卡片先用非赛题独立小例子验证，冻结版本。不要把尚未触发/没命中的样本删掉来抬高整体收益。

### 6.2 用户点名的方法具体怎样隔离

**AutoChip 简洁上下文**：当前方案 A 每次重新拼题面/接口/当前候选/短反馈，未无限积累聊天，
但这不是完整复现。先在 E1 测“原日志/结构化短摘要/短摘要+指南”，以后 E4 单测历史压缩。
摘要长度、历史轮数和检索数量分别控制，不压掉权威接口或当前完整候选。

**TuRTLe 相关参数实验**：区分服务上下文上限（现为 32768）、实际输入 token、输出 cap（8192）
以及整题累计消耗；四者不是同一个窗口。服务上限/模型长度变化可能需重启并改变 KV/cache，
应单独标注，不把速度变化全部归因于提示压缩。

**ICL**：先测零示例 vs 一个短、非同题且分割隔离的例子，再考虑多个；记录额外输入和收益。
例子不能取自当前测试题答案。单独 ICL 组不加 planning/RAG，让提示级影响可解释。

**self-planning**：先比较直接实现 vs 固定字段短计划（接口、状态、时序/优先级）后实现。
若计划需要额外调用，计入预算；Qwen thinking 不能等同于显式计划节点。

**Reflexion**：先限当前题、一次短反思，与同一反馈直接修复比较。跨题记忆必须清洗、版本化，
不能从开发 judge 成绩自动写入正式知识库。

**ToT / MAGE 检查点**：E2 的 Candidate/父子关系/证据保存可以成为基础，但不是完整树搜索，
也不是仿真状态检查点恢复。更多分支只有在工具可区分候选且收益覆盖成本时才值得做。

**AST-WT**：先做 AST/行号定位，再考虑合法自建测试生成的波形。没有可靠期望时只能观察行为，
不能断言某周期错误；开发官方波形分析与可提交求解链路隔离，不承诺完整方法可直接搬到比赛。

**SFT/蒸馏**：先积累可信轨迹，但原始 runs 可能混有评测信息，必须只抽取合规字段并建立
训练/验证/测试隔离。34/11 题已反复分析，不应既训练又用来宣称泛化。训练与 workflow 优化
分开：同权重比流程，同流程比权重。先评估必要性，再花 GPU 训练，不把少量低质样本直接固化。

## 7. 新对话的第一轮操作清单

1. 读本文、AGENTS/规范、当前手册、11 题结论；确认用户希望实施哪个阶段，别默认续跑 completed。
2. 只读核对 git、旧 state、SSH/GPU、定时器；不得输出凭据，不替换现有工作区。
3. 先给 P0/E1 的接口设计：ContextAssembler、token 统计与预算语义、Diagnostic、可插拔反馈/检索，
   哪些进入正式包、哪些只作开发调度；获得认可后实施。
4. 优先验证旧提示/接口不变、未知 usage/检索无命中/工具环境错误、候选不丢失、停止与泄漏边界。
5. 新建实验配置/唯一运行目录，预先声明题集、seed、预算、三组行为及成本；不要同时开所有创新。
6. 模型与工具 smoke 后才后台运行；完成整理对照与原始来源，停 vLLM 并核查显存，不自动租机/关平台。

离线起步验证（不启动 GPU/Vivado）：

```bash
python3 -m unittest dev.tests.test_generation_resume dev.tests.test_generation_sweep \
  dev.tests.test_combine_runs dev.tests.test_knowledge_lookup -q
cmp baseline.py ../example/baseline.py
cmp run_baseline.sh ../example/run_baseline.sh
git diff --check
```

交接前这组 45 项测试通过。更早全项目记录为 172 项中 170 通过、2 跳过，是当时快照，
不是当前增加测试后的全量结果。修改正式代码后应重跑相应测试/全量验证，并单独做真实 smoke。

**重要工具限制**：`generation_sweep.py` 的 preflight 锁定旧正式源码、5/11 题和 profile，
是为保护已有采样实验，不能直接充当新 E1/E2 的通用启动器。新 workflow 改动后拒绝启动是预期行为。
不要删除哈希检查来“修好”；复用 `dev/tools/run.py`/ExperimentRunner，设计新的显式实验契约与审计。
当前也没有一条已经实现的 `--rag` / `--plan` / `--reflection` 命令供直接运行。

源码快照存在因敏感配置脱敏而 `source_complete=false` 的历史情况；正式 runtime 哈希已单独核对。
不得因此宣称原始包完整可重建，也不得通过抄回密钥来令标记变为 true。

## 8. 继续阅读入口与给新对话的请求模板

- [开发手册](../user-manual.md)：模块与配置；较早段落不替代本次已核对快照。
- [11 题完成结论](2026-10-13-diagnostic-eleven-results.md)、[执行历史](2026-10-13-diagnostic-eleven-execution.md)。
- [E1/E2 具体安排](2026-10-13-after-generation-experiment-order.md)、[原落地路线](../research/agent-prior-art/adoption-plan.md)。
- [知识卡片接口与验收](../design/knowledge-cards.md)、[远端管理](../design/remote-tools.md)。
- 前四天教程及下载论文/工程仅保存在本地 `dev/docs/research/agent-prior-art/tutorial/`，不随 PR 上传。
- 工作区另有 `/home/cloudia/FPGACHINA/傻瓜都能看懂的更改说明.md` 和
  `/home/cloudia/FPGACHINA/agent稳定基础工作.md`，属于早期背景，未在本轮重写；不能覆盖最新测量。

可以直接发给新对话：

> 请先完整阅读 `/home/cloudia/FPGACHINA/AMD_SocChina_2026/43240-agent/dev/docs/notes/2026-10-13-conversation-handoff.md`，
> 再读仓库 AGENTS.md 和开发规范。先只读核对本地与远端状态，不重跑已经完成的 11 题，
> 不输出密钥、不覆盖未提交修改。沿交接建议，先给出 P0/E1 的最小接口、对照与验收计划，
> 我确认后再实施并运行。今后不设整轮固定时长截止，但保留单题预算和结束清理。
