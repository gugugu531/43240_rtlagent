# RAG rc4.5 第三批 restricted 运行说明

`rag-catalog-v3-rc4.5` 在 rc4.4 基础上新增 10 张 `restricted / pre_generation_only` 卡，当前统计为 32 `legacy_policy`、28 `restricted`、43 `shadow`、26 `mechanical_only`。

本批新增：cellular snapshot、triangle endpoint dwell、grid row/column wrap、comparison result sign、unsigned negative check、sampled edge history、framing search phase、instruction bank isolation、pause preserves subtick 和 Boolean versus bitwise。

候选门禁 10/10 通过。每张均完成正向、方法已知、冲突、信息不足、明确不适用、资产篡改、tokenizer、BM25 和真实远端 dense 检查。BM25 排名均为前两名；dense 最差为第四名。发布后两条路由均只接纳目标卡。

本批未新增生成调用。四张卡复用 v49 同版本且与 v51 完全相同的夹具；其余六张复用 v42/v45 的同版本、独立公开上下文双臂结果，并对当前 v51 题面另做路由和准入检查。所有模型结果均为 `both_pass`。

rc4.4 的明确不适用门禁已同步收紧：`result-backpressure`、`serializer-snapshot`、`stack-boundary` 和 `carry-lookahead` 的不适用样例现在必须得到 `not_needed`。同时修复了结构守卫对标量输出卡错误要求显式向量宽度的问题。

卡片投影文本没有变化，129 个 embedding 向量继续复用。默认配置和在线配置没有切换。生产化路径见 [restricted 到生产批准方案](2026-10-29-rag-restricted-to-production-plan.md)。

本地隔离候选包为 `dev/optimization-v55/rag-catalog-v3-rc45-candidate.tar.gz`，SHA-256 是 `c3fdd711555617d12c960be028ccbbb1ecb4f02af4e121b91a73f0360b7c8a24`。242 个文件及隔离环境中的 141 项测试均已验证；候选未上传、未部署、未提交。
