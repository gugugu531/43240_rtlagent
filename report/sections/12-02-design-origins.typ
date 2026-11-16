== 设计创新点的来源

第 9 章的设计由人工提出需求与约束，结合论文调研、助手建议和执行反馈逐步形成。主要来源与分工见 @tab-design-origins。

#show figure.where(kind: table): set figure.caption(position: top)
#show figure.where(kind: table): set block(breakable: true)
#figure(
  {
    set text(size: 10.5pt)
    set par(first-line-indent: 0pt, leading: 0.45em, justify: false)
    table(
      columns: (31mm, 1fr), inset: (x: 5pt, y: 4pt), stroke: none, align: left + top,
      table.hline(stroke: 0.8pt),
      table.header([*设计特点*], [*来源与形成过程*]),
      table.hline(stroke: 0.5pt),
      [模块化框架设计], [人工提出工作流、节点和工具可配置及完整日志要求；Claude Code 参与框架比较，Codex 按授权实现不同方案，结合工程需求完成取舍。],
      [按任务与反馈路由策略], [人工确定先规划、再生成与检查的默认流程，并要求各阶段独立组织上下文；助手结合检查器能力与失败类型细化分支及回退规则。],
      [兼顾吞吐与部署的后端选择], [围绕本地硬件约束开展后端调研与测速，助手整理吞吐、权重格式和部署适配差异；方案综合这些记录选择 HIP 与 MTP 配置。],
      [分层检查与定向修复], [参考工具反馈修复研究，助手参与诊断整理与实现审查；候选代码和复检结果的绑定方式经过问题复现与修订形成。],
      [独立构造行为检查器], [人工提出缺少官方测试台时如何提高行为正确性的研究问题；助手比较行为参考与检查器纠错方法，结合执行规则和失败记录完善有限检查表。],
      [日志回放与结果追溯], [DeepSeek Harness 建议保留原始请求、响应及候选来源；人工进一步提出逐步查看和流程图需求，Codex 实现离线回放与工具关联展示。],
      table.hline(stroke: 0.8pt),
    )
  },
  caption: [设计创新点的来源与协作分工],
) <tab-design-origins>

论文提供方法参考，助手参与分析与实现，人工依据运行约束和实验反馈作出取舍。最终设计以实际代码和执行记录为依据，方案讨论、实现完成与实测效果分别记录。
