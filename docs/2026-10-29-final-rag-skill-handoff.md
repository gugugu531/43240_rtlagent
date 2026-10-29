# RAG 与 Skill 最终交接报告

更新时间：2026-10-29（Asia/Tokyo）
交付候选：`rag-catalog-v3-rc4.6`
代码分支：`dev/skill-rag-followup-20261026`

本报告是当前代码、资产、实验和运行边界的权威入口。早期阶段报告保留，用于追溯决策和实验过程；当旧报告中的数量、状态或“正在运行”等描述与本报告冲突时，以本报告和当前锁文件为准。

## 1. 当前结论

当前版本已经具备可提交、可复现和可显式启用的 RAG 整体：统一目录、题面自动路由、BM25 与 dense 检索、embedding 服务身份锁定、失败空返回、逐卡准入、消息装配、运行记录和回退路径均已实现。当前权威目录含 129 张活动卡：32 张 `legacy_policy`、38 张 `restricted`、33 张 `shadow`、26 张 `mechanical_only`；另有 39 张候选保持冻结，不进入活动目录。

`restricted` 表示可以在加载 rc4.6 的进程中显式开启，并只用于首次生成前的窄方法注入。它不表示已经替换默认配置，也不表示生产流量已经使用。当前线上配置、默认 profile 和生产 cohort 均未改变。

rc4.6 的最终本地检查全部通过：143 项单元测试、Python 编译检查、十张新卡的候选门禁，以及晋升后的 BM25/dense 双路由检查。最后一批模型实验实际调用 22 次、无自动重试，其中 20 次形成十张晋升卡的当前版本 control/card 配对证据。`v9-public-division-equality-boundary` 的 card 臂错误使用了 SystemVerilog 关键字 `cover` 作为标识符，因此未晋升并继续保持 shadow；替补卡 `v9-public-toggle-divider-period` 两臂均通过。

候选压缩包保留在本地 `dev/optimization-v56/rag-catalog-v3-rc46-candidate.tar.gz`，共 3,888,789 字节、257 个文件，SHA-256 为 `c4a91d0ade70add17bb2cd8bd76f5647ef357a3fe8e01edfabc9d573dc4876fd`。压缩包不进入 Git；仓库中的源码、资产锁、测试、清单和审计结果足以重新构建并复核它。

## 2. RAG 当前实现

### 2.1 运行路径

首次生成入口在 `rtl_generate` 节点。运行时读取版本化目录和锁文件，对公开题面构造查询，使用 exact、BM25、dense 或 hybrid 检索，再通过逐卡公开合同谓词判断是否需要该卡。准入、资产身份、阶段、token 预算或外部服务任一环节不确定时，结果为空，不改变基础生成消息。

三种模式的含义固定如下：

- `off`：不检索、不装配。
- `shadow`：执行检索、准入和记录，但不把卡片发送给模型。
- `on`：只有检索、公开谓词、版本锁、阶段和预算全部通过时，才把至多一张卡装配到请求中。

`restricted` 卡真正被使用必须同时满足：运行进程加载 rc4.6；`rag_mode: on`；`retrieval.pre_generation: true`；卡片进入 `retrieve_k` 范围；公开题面谓词判定 `eligible`；卡片、目录、实现和索引哈希匹配；装配后不超过知识预算。当前配置固定 `retrieve_k: 5`、`inject_k: 1`、`knowledge_max_tokens: 1024`。`off`、`shadow`、旧候选包或未通过谓词的请求都不会发送 restricted 卡。

显式 BM25 入口是 `config/rag97_pregen_bm25.yaml`。它设置 `rag_mode: on`，可以真实注入；这是交付候选配置，不是默认生产配置。`config/rag97_pregen_dense.yaml` 仍设置 `rag_mode: shadow`，用于服务健康和排名核对。

### 2.2 自动题面路由

题面路由只使用公开规格和接口事实，不读取参考答案、隐藏测试或评分结果。当前实现支持：

- exact、BM25、dense、hybrid 四种检索策略；
- 公开题面查询投影和逐卡窄谓词；
- “题面已给出同一方法”和“明确不适用”返回 `not_needed`；
- 信息不足、事实冲突、相邻主题但无法确认时不注入；
- 资产篡改、错误版本、tokenizer 失败、embedding 超时或非有限向量时安全空返回；
- 最终只允许一张卡发送，并记录 retrieved、admitted、rejected、assembled 和 sent 各阶段证据。

BM25 是第一阶段可用路由，因为不依赖额外服务。dense 与 hybrid 已连通并通过当前卡片排名检查，dense 服务故障时按 `fallback: empty` 返回空结果，不阻断基础生成。

### 2.3 Embedding 服务

embedding 模型为 `Qwen3-Embedding-0.6B-Q8_0`，服务别名为 `qwen3-embedding-0.6b-q8-0`，输出 1024 维向量。运行合同固定为 CPU、4 线程、context 4096、last pooling 和客户端 L2 归一化。服务监听目标主机回环地址 `127.0.0.1:8020`，不直接暴露公网。

`knowledge/embedding-runtime-lock.json` 固定：

- portable runtime commit：`f114f91`；
- 可执行文件 SHA-256：`6fe3a0a7194eebb68423dd7f502659285f792a3a780308b9d88e1486fc59d638`；
- `libllama.so`：`d1682e9f145d012991f011eb864a228617cbbdfc9ce98bc5c0a85c3fe25fd7be`；
- `libggml.so`：`08a23ca36d4a4b1ac6b7bd284e19efbc970eeff59cba5221ce5fcda198e1e90b`；
- `libggml-base.so`：`72ce814d917651f88883857906f2e3f3dc701c71b2e77486521faca756cacf9d`；
- `libggml-cpu.so`：`5ecc784ba61bbabea309949ed0b8531fe8507b36ae1b2b4ecc8212aa0c542a8b`。

模型权重哈希绑定在目录模型合同中。`serve/embedding_service.py` 在启动前验证权重、二进制和四个动态库，避免把“端口可访问”误当成模型身份正确。两台实验主机 33376 与 33589 已使用同一 8020 服务完成 dense 路由和发布后 smoke；生成服务继续复用各自的 `127.0.0.1:8010`。最近一次候选部署检查没有启动或替换服务，也没有改变活动配置。

129 张卡的投影正文在 rc4.6 没有变化，因此复用了原有 129 个向量。当前关键资产为：

| 文件 | 大小 | SHA-256 |
| --- | ---: | --- |
| `knowledge/research-v3.json` | 615,401 | `fc53963eecd4d91b5d97d51dbcc26a80eb4bfac92a9ef09f3c877675b2dac751` |
| `knowledge/research-v3-vectors.json` | 4,009,694 | `c03d3f16ead6bd09af09716085a7ffe3346dac0b93c0fbbaaf4475afe6ce6681` |
| `knowledge/research-v3-lock.json` | 765 | `2623efe0f7e02f18bed8902ba3dc8f946cbe90ba9c37f482ff75989583067b91` |
| `knowledge/research-v3-vectors-lock.json` | 123 | `a22da017fdfef554b06e2044232bfb7097d5f24d3813a8d6d8599efdfe0b2ace` |

## 3. 卡片状态分布

### 3.1 旧策略卡：32 张

这些卡沿用诊断／修复阶段的 `legacy_policy`，以工具诊断、错误码、源码结构和执行身份准入。它们与首次生成前 restricted 卡具有不同触发证据，不能通过改名互相替代。

```text
diag-vrfc-10-1280
diag-vrfc-10-9336
diag-vrfc-10-4982
diag-vrfc-10-2989
diag-vrfc-10-9623
diag-synth-8-6859
counterexample-secondary-vrfc-8530
repair-procedural-variable
repair-ansi-port
repair-local-syntax
repair-undeclared-identifier
repair-source-encoding
repair-multiple-drivers
semantic-rotate-versus-shift
semantic-reset-contract
semantic-combinational-completeness
counterexample-secondary-tool-failure
diag-synth-event-control
repair-sequential-event-control
semantic-selection-shape
repair-index-and-part-select
diag-design-unit-resolution
repair-module-and-top-resolution
semantic-declaration-lifecycle
repair-duplicate-and-implicit-declaration
semantic-elaboration-constant
repair-generate-loop-index
semantic-enum-encoding
semantic-module-compilation-scope
diag-vrfc-explicit-type
repair-explicit-declaration-type
counterexample-encoding-before-syntax
```

### 3.2 Restricted：38 张

这些卡已通过当前准入和证据门禁，可在显式 opt-in 的首次生成路径中使用。它们仍不是默认生产批准卡。

```text
v8-lfsr-feedback-seed
v8-packer-temporal-order
v8-packer-valid-count
v8-pipeline-valid-alignment
v8-ram-port-write-mode
v8-result-backpressure-retention
v8-serializer-snapshot
v8-stack-boundary-guards
v9-lang-boolean-versus-bitwise
v9-lang-comparison-result-sign
v9-lang-conditional-x-merge
v9-lang-context-before-operation
v9-lang-indexed-select-constant-width
v9-lang-nba-rhs-sampling
v9-lang-unsigned-negative-check
v9-public-am-pm-phase
v9-public-batch-final-sample
v9-public-block-carry-chain
v9-public-carry-lookahead-composition
v9-public-cellular-snapshot-update
v9-public-division-remainder-invariant
v9-public-fractional-period-duty
v9-public-framing-search-phase
v9-public-grid-row-column-wrap
v9-public-hdlc-run-classification
v9-public-instruction-bank-isolation
v9-public-johnson-orbit
v9-public-mixed-radix-time-rollover
v9-public-odd-divider-duty-limit
v9-public-pause-preserves-subtick
v9-public-ring-onehot-invariant
v9-public-sampled-edge-history
v9-public-serial-error-rearm
v9-public-signed-subtract-overflow
v9-public-speculation-rollback-priority
v9-public-sticky-event-memory
v9-public-toggle-divider-period
v9-public-triangle-endpoint-dwell
```

### 3.3 Shadow：33 张

这些卡可以检索和记录，但不会发送给模型。继续测试的重点是当前版本独立上下文、路由可达性、明确不适用处理和模型配对稳定性。

```text
v8-bcd-decimal-carry
v8-pipeline-operand-cohort
v9-lang-arithmetic-right-sign
v9-lang-based-literal-sign
v9-lang-comb-read-before-write
v9-lang-concat-signedness
v9-lang-const-not-parameter
v9-lang-division-rounding
v9-lang-empty-star-events
v9-lang-lhs-not-sign-coercion
v9-lang-mixed-sign-arithmetic
v9-lang-overlapping-case-order
v9-lang-remainder-sign
v9-lang-same-process-nba-order
v9-lang-sign-conversion-width
v9-lang-size-cast-sign
v9-lang-slice-signedness
v9-public-bounded-modulus
v9-public-convolution-memory-depth
v9-public-division-equality-boundary
v9-public-fp-exponent-bias
v9-public-fp-normal-hidden-bit
v9-public-fp-round-renormalize
v9-public-fp-sticky-rounding
v9-public-gshare-training-context
v9-public-iterative-product-restart
v9-public-progression-first-term
v9-public-saturation-not-wrap
v9-public-sequence-prefix-fallback
v9-public-serial-sampling-vs-latch
v9-public-unsigned-borrow-not-sign
v9-public-weighted-partial-products
v9-tool-synthesis-excluded-functional-code
```

其中 `v9-public-division-equality-boundary` 已有一次明确 card-only 编译退步，下一轮必须更换独立题面并修复生成约束后重新配对。浮点四卡的有效证据曾绑定 `.local51.1` 修订，需要在当前版本上补充证据。部分语言卡和 `v8-pipeline-operand-cohort` 仍存在两臂路由不可达或只到达一臂的问题，不能仅凭旧固定注入结果晋升。

### 3.4 Mechanical only：26 张

这些卡只完成机械资料或局部合同，不允许发送给模型。它们大多依赖综合器版本、器件、约束和资源映射，必须补齐真实综合报告、版本／器件边界、正反例和评分口径。

```text
v9-lang-case-equality-synthesis
v9-lang-delay-not-hardware
v9-tool-bram-byte-column-shape
v9-tool-direct-enable-selection
v9-tool-direct-reset-selection
v9-tool-dsp-adder-mapping-default
v9-tool-dsp-attribute-scope-priority
v9-tool-dsp-pipeline-utilization
v9-tool-dsp-register-control-compatibility
v9-tool-dsp-signed-capacity
v9-tool-dsp-symmetric-preadder
v9-tool-extract-reset-sync-only
v9-tool-fsm-safe-default-target
v9-tool-fsm-safe-fault-model
v9-tool-ram-address-feedback
v9-tool-ram-array-runtime-reset
v9-tool-ram-initialization-not-runtime-reset
v9-tool-ram-output-async-reset
v9-tool-ram-output-fanout
v9-tool-register-reset-ce-priority
v9-tool-sdp-collision-bypass
v9-tool-srl-dynamic-tap
v9-tool-srl-extraction-precedence
v9-tool-srl-output-register
v9-tool-srl-reset-emulation
v9-tool-srl-style-static-only
```

### 3.5 冻结：39 张

这些候选不属于活动 129 张。`knowledge/research-scope.json` 将它们标为 `frozen`，并冻结 retrieval、admission、assembly、experiments 和 publication。主要原因是只有部分合同、当前工具能力不足，或 CDC／器件事实无法在现有公开检查条件下可靠验证。

```text
v8-cdc-bus-coherence
v8-cdc-sampling-precondition
v9-lang-function-lifetime-synthesis
v9-lang-icarus-concat-unsized
v9-lang-icarus-expression-width
v9-lang-icarus-library-macros
v9-lang-icarus-parameter-width
v9-lang-verilator-initial-edge
v9-lang-verilator-sensitivity
v9-lang-verilator-x-detector
v9-tool-async-reg-iob-priority
v9-tool-async-reg-physical-role
v9-tool-async-reg-simulation-mask
v9-tool-async-reset-recovery-removal
v9-tool-bufg-divider-phase-controls
v9-tool-cdc-async-reset-release
v9-tool-cdc-exception-not-synchronizer
v9-tool-cdc-gray-unit-step
v9-tool-cdc-handshake-destination-mode
v9-tool-cdc-handshake-return-to-idle
v9-tool-cdc-maxdelay-clockgroup-conflict
v9-tool-cdc-pulse-min-gap
v9-tool-cdc-pulse-reset-duration
v9-tool-cdc-reset-x-model
v9-tool-cdc-skew-and-latency
v9-tool-cdc-sync-reset-assertion
v9-tool-clock-buffer-enable
v9-tool-equal-frequency-asynchronous
v9-tool-false-path-direction
v9-tool-mmcm-output-phase-uncertainty
v9-tool-mmcm-startup-clock-enable
v9-tool-rom-ultra-device-scope
v9-tool-startup-domain-release
v9-tool-sync-reset-pulse-capture
v9-tool-timing-path-segmentation
v9-tool-uram-collision-order
v9-tool-uram-common-clock
v9-tool-uram-output-reset-value
v9-tool-uram-tdp-write-mode
```

在当前两小时交付目标下，这 39 张不应解冻，也不应消耗模型调用。

## 4. 最近三批 restricted 晋升

rc4.4、rc4.5、rc4.6 各晋升十张卡。每批均执行正向准入、方法已知、冲突、信息不足、明确不适用、资产篡改、tokenizer、BM25、dense、shadow 阻断和发布后 smoke。rc4.4 与 rc4.5 复用相同版本的既有模型证据，没有新增生成调用；rc4.6 使用 20 次当前版本生成调用形成最终十张配对证据。

rc4.6 十张卡为：toggle divider period、fractional period duty、HDLC run classification、speculation rollback priority、Johnson orbit、mixed-radix time rollover、odd divider duty limit、ring one-hot invariant、serial error rearm、signed subtract overflow。十张卡候选门禁 10/10、BM25 10/10、dense 10/10；BM25 排名 1–5，dense 排名 1–2，最终都只接纳目标卡。

权威结果入口：

- `dev/optimization-v54/final-checks.json`：rc4.4；
- `dev/optimization-v55/final-checks.json`：rc4.5；
- `dev/optimization-v56/final-checks.json`：rc4.6；
- `dev/optimization-v56/model-audit.json`：当前版本模型配对和排除项；
- `dev/optimization-v56/production-readiness.json`：当前启用边界；
- `dev/optimization-v56/candidate-receipt.json`：候选包收据。

## 5. Skill 线现状、缺陷和后续尝试

Skill 线当前暂停，权威状态在 `dev/optimization-v18/skill-lane-status.json`，状态为 `paused_by_user_direction`，运行时变更为 0。它没有随着 RAG 卡片晋升而恢复，也没有进行 Skill+RAG 联合注入。

当前目录状态是：

- `rtl-sequential-state-update` v2 为 `frozen_default_fixed`，是唯一保留的默认固定版本；
- sequential v3 为 `frozen_candidate_not_default`；
- width/signed arithmetic、combinational completeness 和 FSM 为 `frozen_rejected_fixed_ab`。

已有实验说明 Skill 仍不能作为交付默认项。v12 完成 48 对、96 次尝试，但总体没有稳定的成功率优势；36 对事实缺口样本中，Skill 组总 token 上升 10.0%，尝试墙钟总和上升 11.3%，只有一个窄场景出现救援信号。位宽方法的 token 增幅约 14.3%，FSM 候选没有完成可靠独立验证。v16 曾因计划配对未绑定在预检阶段停止，实际 Skill 模型调用为 0，不能作为效果证据。31778 的 soft-stop 审计没有证明价值，因此暂停后转向 RAG。

目前已知缺陷包括：

- 方法已在反馈或题面中给出时，路由仍可能重复注入并放大分析；
- 一些方法会引导模型继续推理而不交付完整 RTL；
- 位映射、复制和索引类提示曾诱发新的表达式错误；
- 主题相关不等于需要方法，自动路由必须允许稳定选择“无 Skill”；
- width、combinational 和 FSM 方法边界过宽，无法把收益或退步归因到一个局部步骤；
- 尚无可接受的 Skill 与 RAG 联合注入证据。

恢复 Skill 线时应按以下顺序进行：

1. 从独立公开失败中选择确实缺方法的样本，和“方法已给出”“主题相关但不适用”负例一起冻结。
2. 先验证固定注入的最小方法正文，再测试需求谓词和自动路由；路由返回无 Skill 应视为正常结果。
3. 将 FSM 拆成计数边界、完成脉冲、输出状态集合和异常恢复等独立方法，不累计注入整个方法集。
4. 每个方法写明最小检查产物和停止条件，并把完整新稿交付率作为硬门禁。
5. 只有单条 Skill 线在独立题族上可重复且不退步，才做 Skill+RAG 联合对照。

## 6. 实验记录是否随仓库提交

应该提交实验记录，但应分层归档。源码仓库需要保留能回答“运行了什么、身份是什么、为什么晋升、能否复核”的材料，不应保存所有生成正文和重复运行目录。

本次提交纳入：

- 实验脚本、公开检查器、题面谓词和发布脚本；
- batch、manifest、receipt、release note、final checks；
- 脱敏后的逐卡审计摘要、路由结果和模型配对汇总；
- 资产锁、哈希、测试和阶段报告；
- 两台主机的紧凑审计结果与调用计数。

本次提交排除：

- `returned/`、`runs/` 中逐调用原始回复、thinking、请求副本和 EDA 日志；
- 候选 `.tar.gz`、重复的 `frozen/` 和 `prior-*.json` 快照；
- portable 二进制、动态库、模型权重和 wheelhouse；
- 本机凭据、环境文件、主机密钥和服务日志。

排除这些文件不会丢失交付证据：仓库内保留摘要、调用数、输出哈希、归档哈希和候选收据。若未来需要长期审计原始数据，应将原始归档上传到受控对象存储或 GitHub Release，并用本报告中的 SHA-256 关联；不要把数百 MB 的模型回复直接放入普通 Git 历史。

## 7. 从当前候选到默认可用整体还缺什么

当前版本可以作为开发／受控环境中的显式 opt-in 版本交付。要获得与旧 32 张卡相近的“默认可使用”地位，还需要生产批准层，而不是把 `restricted` 字符串直接改成 `legacy_policy`。

建议新增哈希绑定的 `production-approval.json`，只允许批准 cohort 在生产 profile 中注入。最快路径为：

1. 先选 5–10 张 restricted 组成 BM25 canary；dense 保持 shadow，避免 embedding 成为第一阶段单点依赖。
2. 每张卡补足至少三个互不相同的公开题面家族，并覆盖已知方法、不适用、冲突、信息不足、相邻主题和资产错误。
3. 两台主机执行至少 200 条混合 canary，包含大量无关题面；要求错误注入为零，且相对 RAG off 的完整交付率和成功率不下降。
4. 验证实际请求只发送一张卡、知识段低于 1024 token、题面和接口没有被重写。
5. 完成 embedding 重启恢复、超时、错误模型、非有限向量和并发稳定性测试；所有异常必须安全空返回。
6. 演练一键关闭 RAG 和回退旧候选目录，再冻结批准文件和生产 profile。

embedding 本身已经通过模型身份、向量一致性、两机 dense 路由和失败回退验证，可以随本版本交付并在受控环境使用。把 dense 设为生产必需路径之前，仍应补重启、并发和长时间运行证据。题面路由已经可以随 BM25 显式配置交付；其进入默认生产的剩余工作主要是混合 canary 和独立题面覆盖，而不是继续重写路由框架。

## 8. 接手与验证

接手者应先核对 `knowledge/research-v3-lock.json` 的 `release_id` 为 `rag-catalog-v3-rc4.6`、`card_count` 为 129，再运行完整测试。候选重建后，应核对资产哈希与本报告第 2.3 节一致。

显式 BM25 验证使用 `config/rag97_pregen_bm25.yaml`。验证 restricted 是否发送时，必须检查运行记录中的最终 `sent`，不能用检索排名或 `admitted` 代替。dense 健康验证使用 `config/rag97_pregen_dense.yaml`；该配置为 shadow，不会改变模型消息。

阶段性历史入口仍保留：

- `docs/2026-10-28-rag-handoff.md`：云端环境和早期完整交接；
- `docs/2026-10-28-rag-final-day-batch-and-embedding-plan.md`：最后一天计划及后续更新；
- `docs/2026-10-29-rag-rc46-runbook.md`：最后十卡批次；
- `docs/2026-10-29-rag-restricted-to-production-plan.md`：restricted 到默认生产批准路径；
- `docs/knowledge.md`：Skill 与 RAG 设计、历史证据和运行接口。

本提交完成的是一版完整、可审查的交付候选和交接材料。它不宣称生产 cohort 已启用，也不把未完成的 Skill、shadow、mechanical-only 或冻结候选包装为已交付能力。
