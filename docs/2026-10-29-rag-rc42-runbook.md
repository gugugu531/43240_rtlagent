# rc4.2候选运行与回退

2026-10-29。当前研究版`rag-catalog-v3-rc4.2`：129项=32 legacy_policy＋5 restricted＋66 shadow＋26 mechanical_only；原39张冻结，Skill暂停。题面候选谓词十五类，受限候选五类。所有on仍需显式选择实验配置，不改变默认关闭／shadow。

packer仅允许首次生成：二态、两个接受样本、首项低位／次项高位、第二个接受沿发布、一拍valid、未完成保持输出、同步高有效复位及2:1数据总线关系必须明确。已有存储方法则拒绝追加，缺时刻或极性返回unknown，冲突发布沿或低有效／异步复位不准入，资产异常返回failure。反馈路径和最终装配均禁止借用这项首次许可。

最终检查收紧了rc4.1未完整绑定的发布沿与复位极性。rc4.1隔离包仍保留于`dev/optimization-v47/`，未部署；最终以rc4.2包和锁为准。冻结查询`independent-5`因此由eligible改为unknown，原文本不变；它只写一拍valid与同步reset，不能推出输出发布沿和高有效。修正记录在`dev/optimization-v48/final-checks.json`，没有追加模型调用。原两组packer真实模型题面均明确这些条件，消息与卡片渲染没有改变。

其它四个受限方法及服务启动、embedding身份、回退配置见[rc3.1说明](2026-10-29-rag-rc31-runbook.md)。其中卡片数量与hold状态是历史值，以本页为准。研究文件为`knowledge/research-v3.json`及对应发布锁、向量锁和`catalog-v3.json`，旧32张独立诊断策略及F24适配器未替换。

完成的第45批使用rc4冻结源，两机目录`/root/rtl-rag-cohort45-20261029-r2`，不得用当前实现覆盖。只读检查与取回入口为`dev/optimization-v46/remote46.py`，独立审计入口`audit_returned46.py`。不要使用v45旧r1入口判断新结果，也不要重跑缺失导入的旧队列。完整结果见[第45批报告](2026-10-29-rag-batch45-results.md)。

最终候选包和收据：`dev/optimization-v48/rag-catalog-v3-rc42-candidate.tar.gz`、`candidate-manifest.json`、`candidate-receipt.json`、`deployment-33376.json`、`deployment-33589.json`。两机候选目录`/root/rtl-rag-catalog-v3-rc42-20261029`；仅隔离交付与加载核对，不启动生成或切换服务。

使用`config/rag_catalog_v3_shadow.yaml`作观察入口。保留固定embedding模型、权重及运行库，不重新训练、改维度或放松身份校验；服务失败安全返回空并记录failure，不计correct_empty。本包不带模型、许可证或EDA程序。`run.sh`与`run_baseline.sh`保持可执行，baseline thinking继续开启。

mixed-sign仅shadow：新版两次模型新稿通过但成本增加，方法不稳定；empty-star仅回接相同修订版本的历史通过证据，没有新的自动准入谓词。shadow不等于正式收益验收，也不会在普通on模式自动进入消息。
