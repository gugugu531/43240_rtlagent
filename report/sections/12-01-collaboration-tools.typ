#pagebreak()
= 大模型协作记录

== 所用模型与工具

开发过程中使用 Codex、Claude Code、DeepSeek Harness 和 Oh My Pi 辅助资料调研、方案讨论、代码实现与结果审查。依据留存的项目会话和协作审计，主要分工见 @tab-collaboration-tools；模型名称采用记录中的服务标识。

#show figure.where(kind: table): set figure.caption(position: top)
#show figure.where(kind: table): set block(breakable: true)
#figure(
  {
    set text(size: 10.5pt)
    set par(first-line-indent: 0pt, leading: 0.45em, justify: false)
    table(
      columns: (27mm, 55mm, 1fr), inset: (x: 5pt, y: 4pt), stroke: none, align: left + top,
      table.hline(stroke: 0.8pt),
      table.header([*工具*], [*记录中的模型*], [*参与环节*]),
      table.hline(stroke: 0.5pt),
      [Codex], [gpt-6.1-sol、gpt-6-astra、gpt-6-luna], [架构与文献研究、实现审查、预算与上下文处理、实验分析及报告整理],
      [Claude Code], [claude-opus-5、claude-opus-5-5], [早期工程规划、推理与判定分工、实验体系及框架方案讨论],
      [DeepSeek Harness], [deepseek-flash], [模型筛选分析、文献整理、证据审计及历史实验入口实现],
      [Oh My Pi], [deepseek-flash、deepseek-v4-flash、gpt-6-astra], [实现审查、提示材料迁移、技能发现与相关代码协作],
      table.hline(stroke: 0.8pt),
    )
  },
  caption: [开发协作模型与工具的主要分工],
) <tab-collaboration-tools>

开发助手提供资料分析、建议与实现草稿，人工确定研究方向、运行约束和方案取舍，代码与结论结合工具执行及实验记录复核。历史线程还记录了 gpt-6-sol 参与技能拆分和文档审阅，此项按线程记录归属。跨工具导入的历史按原始来源统计，初始化、认证失败和中止草案不计为完成的贡献。

开发助手不参与正式断网求解。第 6 章调用与用量统计对应求解流程，开发协作的消耗单独归类。
