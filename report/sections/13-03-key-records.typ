== 关键运行记录

以下案例均取自第 6 章的完整首跑批次，用于说明修复和检查的实际过程，不作为额外实验。记录保存在上一节所列目录中，可按题目标识查阅。

#show figure.where(kind: table): set figure.caption(position: top)
#show figure.where(kind: table): set block(breakable: true)
#figure(
  {
    set text(size: 10.5pt)
    set par(first-line-indent: 0pt, leading: 0.45em, justify: false)
    table(
      columns: (34mm, 1fr, 42mm), inset: (x: 5pt, y: 4pt), stroke: none, align: left + top,
      table.hline(stroke: 0.8pt),
      table.header([*案例*], [*记录中的执行过程*], [*最终判定与意义*]),
      table.hline(stroke: 0.5pt),
      [Prob006：位序变换], [行为检查发现失配，经归因后修改 RTL；修订稿与原稿内容不同，并在同一检查器下复检通过], [L3；检错、修复与复检形成完整过程],
      [Prob035：循环计数], [首稿存在过程赋值声明问题，修订稿又引入重复声明；复检仍编译失败，随后结束修复并交付修订稿], [L0；产生新代码不等于消除错误],
      [Prob066：边沿捕获], [结构修复后通过内部行为检查，但用例遗漏复位期间非零输入及解除复位后的历史状态等关键场景], [L1；内部用例通过不代表完整行为正确],
      table.hline(stroke: 0.8pt),
    )
  },
  caption: [典型运行记录及其含义],
) <tab-key-records>

三题在答案目录中的标识如下：

#block[
  #set text(size: 10pt)
  #set par(first-line-indent: 0pt, justify: false)
  verilogeval_prob006_vectorr #linebreak()
  verilogeval_prob035_count1to10 #linebreak()
  verilogeval_prob066_edgecapture
]

各题的 trace.jsonl 记录执行顺序，结合交付分析表中的运行标识，可定位 records/ 下的请求、响应与候选材料；逐题官方等级则在独立判定输出中核对。

阅读这些记录时，应分别确认实际修改了什么、复检执行了什么，以及最终交付的是哪份代码。修复案例关注父子代码与复检结果，漏检案例关注输入条件和状态是否真正触发，避免仅凭流程结束状态解释结果。
