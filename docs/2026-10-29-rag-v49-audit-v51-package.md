# RAG v49 审计、97卡本地修订与下一批实验包

更新时间：2026-10-29（Asia/Tokyo）

## v49 完成审计

两台主机的不可变结果已经取回。33376 完成 9 个生成配对，33589
完成 10 个生成配对；共 38 次真实生成调用，thinking 全开、采样参数
配对内一致、无自动重试。19 个有效配对的 control/card 两臂全部交付
完整 RTL 并通过同一 Vivado 检查器，没有功能退步，也没有正确率救援。

| 指标 | control | card | 变化 |
| --- | ---: | ---: | ---: |
| 有效尝试 | 19 | 19 | — |
| 完整交付并通过 | 19/19 | 19/19 | 0 |
| 总 token | 102,681 | 89,861 | −12.5% |
| 累计耗时 | 1,502.1 秒 | 1,172.1 秒 | −22.0% |

收益高度集中：framing search 为 −49.3% token、overlapping case 为
−26.5%、packer valid count 为 −25.9%、serializer snapshot 为 −20.7%。
carry-lookahead composition、context-before-operation、pipeline valid
alignment 和 backpressure retention 分别增加约 8%–13% token。因而本批
只能增加“当前渲染无退步／局部效率”的筛选证据，不能证明普遍收益，也
不能恢复默认注入。

thinking 的有限线索与这个边界一致：有效率信号的卡通常较早固定唯一
局部关系；成本增加的卡仍会重新讨论表达式宽度、接口或替代架构。该线索
不作为因果证明，处置只依据真实请求、新稿与工具结果。

`v9-lang-const-not-parameter` 没有进入模型调用。它的 target 按设计触发
`VRFC 10-2951: N is not a constant`，而 v49 预检只接受功能失败，未声明
允许目标代码编译失败。该项属于实验合同缺口，不是卡片负面结果；reference
通过且 adjacent 被功能检查检出。后续机械执行器已经支持显式
`allow_target_compile_failure`，环境或合同失败不会计作 correct empty。

原始审计位于：

- `dev/optimization-v49/audit-33376.json`
- `dev/optimization-v49/audit-33589.json`
- `dev/optimization-v49/audit-33376-reasoning.json`
- `dev/optimization-v49/audit-33589-reasoning.json`

## 97 张卡的本地修订结果

生产运行资产与默认开关未修改。独立候选包 `rag-local-v51-r1` 完成了：

- 97/97 张研究卡均具有版本、来源、卡片哈希、夹具身份和处置合同；
- 24 张卡的正文被窄化，补充最小修改对象、检查产物和停止条件；
- 71 张功能／语言卡具有实验准入规则；这不是 71 个生产谓词；
- 五个有源码依赖的方法实现了有界结构定位器，32/32 本地源码正反例通过；
- 另两项源码依赖保持 pending：const/parameter 和综合排除区域；
- 26 张工具／资源卡具有 Vivado 2026.1、目标器件、所需报告、资源条件和
  语义限制合同；它们不会被普通功能仿真晋级；
- 真实准入测试 793/793、装配不变性与预算测试 10/10 通过；
- 99 个机械案例已冻结：97 张卡各一例，另加 block carry 与 batch final
  sample 两个独立开发上下文；
- 题面回放分布为 eligible 28、not_needed 21、unknown 50。大量 unknown 是
  保守边界，不是待放宽的失败。

卡片修订没有改变 129 张索引文档的投影，因此现有真实 embedding 向量不需
重算；这只保证索引身份连续，不证明全部 97 张的 dense 召回或生成收益。

本地没有 Vivado 可执行文件。机械执行器已实际运行一次并正确得到
`environment_failure`，未把工具缺失算成卡片通过或正确拒绝。可部署的
机械包为 `dev/optimization-v51/rag-local-v51-r2.tar.gz`，哈希
`4c8f2253e462b3ca96709d653a74ad36ec3c47ad0093e3e04ec588843f9e3c91`。
它只运行工具，不调用生成模型；逐卡失败后继续其他卡。r1 在部署前发现
current-card 哈希绑定错误，已由 r2 取代，r1 从未部署。

## 已启动的 v52 十卡批次

v52 从尚未检验新正文的卡中选择十张，平均分到 33376 和 33589：

1. based literal sign；
2. empty implicit event set；
3. remainder sign；
4. slice signedness；
5. FP exponent bias；
6. FP normal hidden bit；
7. FP round renormalize；
8. FP sticky rounding；
9. grid row/column wrap；
10. gshare training context。

每张先执行 reference/target/adjacent 机械预检，再执行一组 control/card 固定
修复配对。两台各最多 10 次调用，thinking 开启，temperature=0，无自动
重试。冻结包哈希为
`d77b61c4c4176f97280d36e367e12853a796a5a3f09f96c3657d3c697750d264`；
远端目录均为 `/root/rtl-rag-cohort52-20261029-r1`。该批测试新渲染的交付、
语法与功能风险，不测试检索器或自动路由。

## 后续顺序

1. v52 完成后回传并审计真实请求、thinking、用量、新稿和工具哈希；按
   无退步、成本长尾、未交付、机械合同错误分别处置。
2. v51-r2 已于 2026-10-29 13:13（日本时间）上传到两台主机并设置一次性
   接力启动：各自主机只有在自己的 v52 状态为 `completed` 后才解包和启动，
   避免两个队列同时竞争 Vivado。33376 分配 50 个机械案例，33589 分配
   49 个；模型调用均为 0。v52 若异常或六小时内未结束，接力器只记录
   `blocked`，不会自行重试或绕过失败。
3. 对机械通过且没有 blocker 的卡补拒绝矩阵；只有实际发送内容改变时才
   花模型预算。26 张工具卡和综合排除卡保持 mechanical-only/partial。
4. 两个 routed-first 新上下文另用真实 BM25/dense 检索、实验准入与真实
   tokenizer 验证。当前 71 条规则仍是开发实现，默认 RAG 保持关闭。
