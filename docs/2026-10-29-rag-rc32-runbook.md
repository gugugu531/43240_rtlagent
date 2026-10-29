# 当前候选rc3.2运行入口

当前目录为 `rag-catalog-v3-rc3.2`，题面候选谓词12类，受限注入4类。目录状态为32 legacy_policy、4 restricted、65 shadow、2 hold、26 mechanical_only。原136候选中39张冻结，允许研究的97张与旧32张组成129项。

rc3.2在rc3.1跨方法修复基础上，将经过新版独立确认的serial、triangle和grid从hold改为shadow，并绑定第42批的原版本、实际渲染哈希与审计。shadow仍不会进入普通on消息。mixed-sign及empty-star继续hold，六类新方法保持shadow。

使用 `config/rag_catalog_v3_shadow.yaml`；生成服务与embedding启动、身份核对和回退步骤见[rc3.1运行说明](2026-10-29-rag-rc31-runbook.md)。其中的五张hold数量是该版本历史状态，当前以本页为准。当前包不切换在线配置，权重和EDA工具不随包分发。

最终候选包、清单、隔离检查和两机部署收据保存在 `dev/optimization-v44/`。两机候选目录为 `/root/rtl-rag-catalog-v3-rc32-20261029`。实验原件继续保存在独立的 `/root/rtl-rag-cohort42-20261029-r1`，使用rc3冻结代码；复现时不要用当前实现覆盖旧实验。

完整结果、权限和下一批工作见[本批完成报告](2026-10-29-rag-batch42-results.md)。未进行仓库提交或推送；正式模型申报占位字段仍需在提交阶段核对。
