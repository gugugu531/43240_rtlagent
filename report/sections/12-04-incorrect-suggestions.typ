== 大模型给出的错误建议

开发助手也曾将示例配置当作约束、误判代码错误，或扩大重测范围。这些建议经人工核查和工具执行后纠正，典型案例见 @tab-incorrect-suggestions。

#show figure.where(kind: table): set figure.caption(position: top)
#show figure.where(kind: table): set block(breakable: true)
#figure(
  {
    set text(size: 10.5pt)
    set par(first-line-indent: 0pt, leading: 0.45em, justify: false)
    table(
      columns: (35mm, 1fr, 1fr), inset: (x: 5pt, y: 4pt), stroke: none, align: left + top,
      table.hline(stroke: 0.8pt),
      table.header([*错误建议及来源*], [*发现方式*], [*纠正结果*]),
      table.hline(stroke: 0.5pt),
      [将 vLLM 视为既定后端（Claude Code）], [人工质疑示例默认配置是否属于赛事要求，要求重新核对主办方资料], [撤回既定后端假设，将后端选型恢复为依据硬件、吞吐和部署条件作出的工程选择],
      [将编译失败归因于嵌套模块（DeepSeek Harness）], [在同一 Vivado 环境比较完整回复、结构化提取和原有提取结果；前两者编译成功，原有提取结果发生截断], [撤回对 RTL 本身的错误判断，将该例定位为代码提取问题；编译结果与功能正确性分别评价],
      [要求全部重新判定（Codex）], [核对历史结果及实际文件变更，区分记录缺失与已执行结果失效], [按变更影响确定重测范围，保留原有真实执行结果，并单独说明历史输入一致性的证据缺口],
      table.hline(stroke: 0.8pt),
    )
  },
  caption: [错误建议的发现与纠正],
) <tab-incorrect-suggestions>

这些案例表明，助手的解释需要与原始材料和实际执行结果相互核对。配置要求以赛事资料为依据，错误定位先检查原始回复、提取结果与工具诊断，重测范围则由实际变更决定。纠正后的判断保留适用范围，避免将局部证据扩大为整体结论。
