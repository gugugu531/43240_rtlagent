== 错误归因与反馈修复

流程按失败类型选择处理方式，如 @tab-retry 所示。结构错误直接依据工具诊断修复；行为不一致先分析实现和检查器，再决定修改对象，避免将错误的预期输出作为代码修复目标。

#show figure.where(kind: table): set figure.caption(position: top)
#figure(
  {
    set text(size: 10.5pt)
    set par(first-line-indent: 0pt, leading: 0.45em, justify: false)
    table(
      columns: (42mm, 1fr),
      inset: (x: 5pt, y: 4pt), stroke: none, align: left + top,
      table.hline(stroke: 0.8pt),
      table.header([*触发情况*], [*处理方式*]),
      table.hline(stroke: 0.5pt),
      [结构检查发现代码错误], [依据工具诊断修复 RTL，再执行检查],
      [行为失配或未知值], [分析 RTL 与检查器，决定修复对象或停止],
      [归因为 RTL 错误], [修复代码，重新执行结构与行为检查],
      [归因为检查器错误], [独立重建检查器，重新仿真比较],
      [首次生成或检查器回复为空], [仅在生成正常结束或达到输出长度上限时重新请求，不续接此前的思考内容],
      table.hline(stroke: 0.8pt),
    )
  },
  caption: [错误归因与处理方式],
) <tab-retry>

结构修复接收当前代码、日志摘要及结构化诊断。日志按严重程度筛选并去重，保留错误编号、位置和涉及信号，截断与省略作显式标记，完整日志另行保存。行为归因和修复补充失败用例、期望值、实测值及展开后的输入时间线，归因结论作为分析假设供修复参考。

检查器重建仅补充原检查器和失败用例标识，不接收候选 RTL、实测输出或归因理由。代码修复后重新执行结构与行为检查，检查器变化后重新仿真比较，旧结果不作为新检查器的证据。

CorrectBench#super(link(<ref-correctbench>, "[7]"))将生成测试台的功能自检与纠错纳入验证流程。本方案据此关注检查器本身的可靠性，在失配后区分代码错误与检查器错误，分别修复 RTL 或重建检查器；检查器重建仍仅依据公开规格及允许传递的检查材料。
