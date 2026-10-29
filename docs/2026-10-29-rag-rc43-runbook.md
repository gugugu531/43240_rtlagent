# RAG rc4.3 交付与运行入口

`rag-catalog-v3-rc4.3` 是 2026-10-29 首批十卡晋升后的受限交付候选。129 张目录卡中，32 张保留旧策略，63 张为 shadow，8 张为 restricted，26 张仅保留机械证据。本批从 shadow 晋升三张：`v9-lang-context-before-operation`、`v9-public-batch-final-sample` 和 `v9-public-block-carry-chain`。

三张新增 restricted 卡仅允许在 `pre_generation` 阶段注入。题面必须通过卡片自身的公开契约谓词，BM25 或 dense 检索只负责生成候选，不会覆盖准入判断。无法确认、题面信息不足、卡片哈希不匹配、embedding 服务失败或卡片仍为 shadow 时，路由返回空结果，生成流程继续使用原题面。

首批十张中的其余七张继续保持 shadow。它们的既有模型结果不会绕过契约或召回门禁。第53批结果、真实 tokenizer 检查、双臂模型审计和晋升后 smoke 分别保存在 `dev/optimization-v53/route-results.json`、`tokenizer-results.json`、`model-audit-summary.json` 和 `post-promotion-smoke.json`。

embedding 服务使用 `knowledge/embedding-runtime-lock.json` 固定二进制、动态库和模型身份。两台主机目前均在 `127.0.0.1:8020` 运行，模型别名为 `qwen3-embedding-0.6b-q8-0`，输出维度 1024。服务只监听回环地址；权重和可移植运行时不包含在源码候选包中，需要在目标主机按锁文件准备。

交付包为 `dev/optimization-v53/rag-catalog-v3-rc43-candidate.tar.gz`，SHA-256 是 `f95797e3b23eae6a46ef59637979a222b2674884a884eb746a7dad690ba1341c`。两台主机的只读候选目录均为 `/root/rtl-rag-catalog-v3-rc43-20261029`；217 个清单文件的哈希和运行时导入已通过。候选部署没有启动新生成服务，也没有切换在线配置。

发布前检查包括本地 137 项单元测试、隔离解包后的 137 项单元测试、三张卡的 BM25/dense 实际 admitted 结果和 `git diff --check`。具体摘要见 `dev/optimization-v53/final-checks.json` 与 `release-note.json`。

回退时保留现有服务配置并重新选择 rc4.2 候选目录即可。8020 embedding 服务是独立、可停止的进程；停止它会使配置为 `fallback: empty` 的题面 dense 路由返回空结果，不影响未注入的基础生成路径。
