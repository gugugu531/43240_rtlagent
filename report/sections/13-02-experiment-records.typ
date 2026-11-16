== 实验记录索引

第 6、8 章所用的 145 题首跑记录已复制到方案仓库内的本地记录目录，路径相对于方案目录：

#block[
  #set text(size: 9.5pt)
  #set par(first-line-indent: 0pt, justify: false)
  dev/report-evidence/verilogeval-145/
]

下表路径均相对于该目录。逐题结果、原始材料和分析汇总分别保存，便于从统计结论追溯到实际答案与检查过程。

#show figure.where(kind: table): set figure.caption(position: top)
#show figure.where(kind: table): set block(breakable: true)
#figure(
  {
    set text(size: 10.5pt)
    set par(first-line-indent: 0pt, leading: 0.45em, justify: false)
    table(
      columns: (88mm, 1fr), inset: (x: 5pt, y: 2.5pt), stroke: none, align: left + top,
      table.hline(stroke: 0.8pt),
      table.header([*记录位置*], [*核对内容*]),
      table.hline(stroke: 0.5pt),
      [#text(size: 9.5pt)[rag_off/effective-config.json]], [该批实际配置，结合模型声明核对运行条件],
      [#text(size: 9.5pt)[rag_off/answers/]], [逐题交付答案、服务响应和任务耗时],
      [#text(size: 9.5pt)[rag_off/judging/]], [逐题独立判定结果与工具记录，核对完整等级分布],
      [#text(size: 9.5pt)[records/]], [模型请求与响应、候选代码及流程执行材料],
      [#text(size: 9.5pt)[checks/20261031-0340-summary.json #linebreak() checks/20261031-first-round-audit.json]], [全批汇总、答案与判定关联，以及实际采样检查],
      [#text(size: 9.5pt)[rag-off-analysis/]], [调用、检查器、规划与交付分析，定位修复落实和失败原因],
      table.hline(stroke: 0.8pt),
    )
  },
  caption: [完整批次的结果与证据索引],
) <tab-experiment-records>

复核保留全部首跑结果，不以补测替换失败。该目录已加入 Git 忽略规则，不随方案提交或打包；判定反馈仅用于分析，求解流程不读取这些记录。
