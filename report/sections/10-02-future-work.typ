== 后续改进方向

后续工作优先围绕已定位的失败原因展开，先改善完整答案交付与修复落实，再提高行为检查的覆盖能力。主要安排见 @tab-future-work。

#show figure.where(kind: table): set figure.caption(position: top)
#show figure.where(kind: table): set block(breakable: true)
#figure(
  {
    set text(size: 10.5pt)
    set par(first-line-indent: 0pt, leading: 0.45em, justify: false)
    table(
      columns: (29mm, 1fr, 1fr), inset: (x: 5pt, y: 4pt), stroke: none, align: left + top,
      table.hline(stroke: 0.8pt),
      table.header([*优先方向*], [*具体措施*], [*评价方式*]),
      table.hline(stroke: 0.5pt),
      [生成与归因的预算分配], [在现有空回复恢复机制基础上，协调生成、归因和修复额度，为最终代码与修复决策留出空间], [统计完整答案率、有效归因比例及对应耗时，区分阶段截断和总预算耗尽],
      [修复后的逐项复检], [对照原始诊断确认错误消除，并检查新增错误；结合剩余预算与修复进展决定是否继续], [核对父子代码差异、残留诊断和最终等级，评价修复成功率与额外成本],
      [关键行为覆盖], [从公开规格提取复位、状态保持和级联进位等目标，检查激励是否实际触发；为长时序行为扩展序列表达], [用自编正确例和错误反例检查误报与漏检，分别记录行为覆盖和输出覆盖],
      table.hline(stroke: 0.8pt),
    )
  },
  caption: [后续改进的优先顺序与评价方式],
) <tab-future-work>

上述改动采用固定题集和预算逐项对照，并保留全部首跑结果。完整流程与同模型基线配对评估，分别报告能力得分、归一化增益和调用成本；技能与策略调整采用开关对照，区分各项措施的贡献。模型及配置冻结后再开展多次独立采样，评价稳定性。官方判定继续独立于求解流程，仅用于保存答案后的结果评估。
