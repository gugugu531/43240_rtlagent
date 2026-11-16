== 分级结果

145 道题均完成首跑与独立判定，其中 120 道通过编译、仿真和综合，完整通过率为 82.76%。按每题达到的最高等级统计，结果见 @tab-graded-results。

#show figure.where(kind: table): set figure.caption(position: top)
#figure(
  {
    set text(size: 10.5pt)
    set par(first-line-indent: 0pt, leading: 0.45em, justify: false)
    table(
      columns: (1fr, 22mm, 25mm, 22mm),
      inset: (x: 5pt, y: 4pt), stroke: none, align: (left + top, right + horizon, right + horizon, right + horizon),
      table.hline(stroke: 0.8pt),
      table.header([*最高等级*], [*题数*], [*占比*], [*系数*]),
      table.hline(stroke: 0.5pt),
      [L0：未通过编译或无完整答案], [11], [7.59%], [0],
      [L1：编译通过，仿真未通过], [14], [9.66%], [0.2],
      [L2：仿真通过，综合未通过], [0], [0.00%], [0.7],
      [L3：编译、仿真及综合通过], [120], [82.76%], [1.0],
      table.hline(stroke: 0.5pt),
      [*合计*], [*145*], [*100%*], [—],
      table.hline(stroke: 0.8pt),
    )
  },
  caption: [当前工作流的最高等级分布],
) <tab-graded-results>

按赛事等级系数计算，题集得分为 $(120 + 14 times 0.2) / 145 approx 0.8469$。达到编译通过及以上等级的题目共 134 道，占 92.41%；本批所有通过功能仿真的答案均通过综合。独立判定未出现工具错误，仿真通过项均有实际采样与比较记录。上述结果对应本批公开题测试，题集得分与完整通过率分别统计。
