# RAG rc4.6 第四批 restricted 运行说明

`rag-catalog-v3-rc4.6` 在 rc4.5 基础上新增 10 张 `restricted / pre_generation_only` 卡，当前统计为 32 `legacy_policy`、38 `restricted`、33 `shadow`、26 `mechanical_only`。

本批新增：toggle divider period、fractional period duty、HDLC run classification、speculation rollback priority、Johnson orbit、mixed-radix time rollover、odd divider duty limit、ring one-hot invariant、serial error rearm 和 signed subtract overflow。

候选门禁和发布后检查均为 10/10。BM25 排名为 1–5，dense 排名为 1–2；两条路由最终都只接纳目标卡。每张均完成正向、方法已知、冲突、信息不足、明确不适用、资产篡改、tokenizer 与当前版本 control/card 模型对照。

本轮实际进行了 22 次生成调用且没有重试。20 次用于最终 10 张卡；`division-equality-boundary` 的 card 臂生成了使用 SystemVerilog 关键字 `cover` 的错误标识符，因此该卡未晋升并继续保持 shadow。替补卡 `toggle-divider-period` 的两臂均通过。

卡片投影文本没有变化，129 个 embedding 向量继续复用。默认配置、在线配置和生产 cohort 均没有切换。本地 `restricted` 只有在候选包被某个进程加载，并且该次运行显式设置 `rag_mode: on` 与 `retrieval.pre_generation: true`、检索进入前五且公开题面谓词通过时才会注入。`rag_mode: off`、`shadow` 或仍在使用旧包的线上进程都不会启用这些卡。

本批没有上传、部署、提交或提交评测。
