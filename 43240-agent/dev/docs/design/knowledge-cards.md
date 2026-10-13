# 开发用 RTL 知识卡片与确定性检索

日期：2026-10-13。状态：首版离线原型已实现，未接入正式 Agent 或正在进行的实验。
用户已认可“开发区卡片、检索与离线测试”的阶段范围；本轮没有扩大到模型或 Vivado 验证。

## 边界与目录

资料：[dev/knowledge/rtl](../../knowledge/rtl/README.md)。
工具：[knowledge_lookup.py](../../tools/knowledge_lookup.py)。
测试：[test_knowledge_lookup.py](../../tests/test_knowledge_lookup.py)。

不修改 agent/、skill/、config/、baseline、实验配置或正在运行的实验工具。
正式代码不得导入 dev；未来接入需要独立实验变体和单独审核的可提交资料。
本轮不自动安装 Ross skills，不下载完整知识库，不执行第三方脚本，不启动 GPU 或 Vivado。

RAG 的完整使用过程是“检索资料 → 限量加入上下文 → 模型据此生成”。
关键词检索同样可以用于这个过程，不要求向量数据库；当前只完成检索与上下文打包，
不能称为已经参与模型求解并取得收益的 RAG 系统。

## 数据契约

`cards.json` 使用 schema_version=1；文件级含 corpus_id、状态、sources 和 cards。
每张卡片包含：

- id、title、kind（repair/design）。
- tools、versions、codes：错误命名空间与适用版本；当前 repair 卡仅面向 2026.1。
- keywords、applies_when、guidance、verify、cautions。
- source_ids、review_status、tool_validation。

sources 记录标题、来源类型、链接、许可，以及本地参考文件的相对路径和 SHA256。
Ross 来源固定为提交 `2cdc9eef1b6b5b17fa45f5e4d468e5483a1c92de`；本地通用错误规则来源于既有服务与接口说明。
AMD 文档只保留链接和原创简短归纳；通用不变量明确标记为团队原创，不冒充外部已验证资料。

不读取 dev/runs、赛事 tasks、官方 TB、参考实现或 judge；不把题目名称作为检索键。
结构校验会拒绝明确题号和 ref/tb 文件名，但这不是完整的数据污染审计，新增内容仍需人工审核。
全部卡片是已核对资料的草稿，未做独立 HDL 执行或解题收益验证。

## 函数接口

```python
load_corpus(path=DEFAULT_CORPUS) -> dict
verify_local_sources(corpus, ross_root=DEFAULT_ROSS) -> list[dict]
retrieve(corpus, *, query='', tool=None, version=None,
         code=None, kind=None, limit=2) -> dict
build_context(result, max_chars=2400) -> dict
```

1. 错误码按完整命名空间精确匹配，不用数字后缀串联不同工具。
2. repair 查询要求 tool 和 version；不匹配版本不返回该卡片。
3. 查询出现可识别错误码时采用严格错误码模式，未知码返回空，不用词匹配掩盖未覆盖。
4. 设计主题默认只查 design 卡，以中文短语或英文词边界匹配；相同分数按 card_id 排序。
5. 每次最多 2 张，返回命中原因、来源与内容哈希；不是基于模型的语义理解。
6. context 以完整卡片打包，超预算整张省略，保留 omitted_for_budget 记录。
   字符数不是 token 数；未实现真实 tokenizer 预算或 Agent Budget 接入。

没有网络调用、模型调用、命令执行、向量索引或文件写入。CLI 只向 stdout 输出 JSON。
资料校验通过只说明字段与来源指纹一致，不意味着建议一定正确或适用于当前题目。

## 已验证与仍未验证

运行：`python3 -m unittest dev.tests.test_knowledge_lookup`，21 项测试全部通过。
覆盖精确错误码、未知错误拒绝回退、工具/版本过滤、命名空间隔离、中英主题、稳定排序、
空命中、最多 2 张、整卡字符预算、来源完整性、重复 ID、基准题污染标记和来源路径/哈希变化。
`validate --verify-sources` 核对 11 个本地来源；其余 3 条明确标记 not_locally_cached。
资料 JSON 为 21443 字节；此数字不含工具、测试、README 或原始 Ross 仓库。

同时只读复核正在进行的 11 题会话：正式源码、配置、题面及 profile 指纹未变。
没有为了验证知识库再运行整个项目测试套件或额外启动 Vivado，以免增加当前对照的资源竞争。

仍需：独立小例子验证、资料内容人工复核、检索精度/漏检测量、真实 tokenizer 预算、
新 workflow 接入与有/无检索消融。当前尚不能宣称模型表现已提高。

## 下一阶段实验建议

先冻结本轮生成设置，再在新的运行中比较“结构化反馈”与“结构化反馈 + 1～2 条修复指南”，
保持模型、首次提示、总 token/时间预算与任务集一致，记录无命中、命中卡片、实际注入片段和成本。
不能看到官方 L1 后在正式 Agent 内触发检索；触发只能来自题面和自身合规工具证据。
功能检查清单另外测量，不能同时增加检索、审查节点和候选数量后把提升归因于 RAG。
