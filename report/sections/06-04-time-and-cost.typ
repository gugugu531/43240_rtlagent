== 耗时与调用成本

本批按投题服务返回的任务耗时统计，覆盖全部 145 道题，包括失败和空答案。模型调用次数包含规划、生成、检查器构造及修复等阶段，结果见 @tab-time-cost。

#show figure.where(kind: table): set figure.caption(position: top)
#figure(
  {
    set text(size: 10.5pt)
    set par(first-line-indent: 0pt, leading: 0.45em, justify: false)
    table(
      columns: (1fr, 1fr), inset: (x: 5pt, y: 4pt), stroke: none, align: (left + top, right + horizon),
      table.hline(stroke: 0.8pt),
      table.header([*指标*], [*结果*]),
      table.hline(stroke: 0.5pt),
      [单题平均耗时], [114.8 秒],
      [单题最长耗时], [393.4 秒],
      [全部任务耗时累计], [16,650.4 秒，约 4.63 小时],
      [模型调用次数], [447 次，平均每题 3.08 次],
      [已知输入用量], [1,293,443 token],
      [已知输出用量], [631,628 token],
      table.hline(stroke: 0.8pt),
    )
  },
  caption: [任务耗时与模型调用统计],
) <tab-time-cost>

任务耗时反映服务端求解过程，不包含独立判定和本地公网传输开销。Token 统计采用模型服务返回的用量，输出包含思考与最终正文。
