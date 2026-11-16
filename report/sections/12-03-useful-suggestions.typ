== 大模型给出的正确建议

开发助手的建议通过记录核对、问题复现和执行检查后采纳。具有明确实施依据的案例见 @tab-useful-suggestions。

#show figure.where(kind: table): set figure.caption(position: top)
#show figure.where(kind: table): set block(breakable: true)
#figure(
  {
    set text(size: 10.5pt)
    set par(first-line-indent: 0pt, leading: 0.45em, justify: false)
    table(
      columns: (30mm, 1fr, 1fr), inset: (x: 5pt, y: 4pt), stroke: none, align: left + top,
      table.hline(stroke: 0.8pt),
      table.header([*建议及来源*], [*采纳方式*], [*核验与作用*]),
      table.hline(stroke: 0.5pt),
      [保留完整模型交互（DeepSeek Harness）], [先保存请求与响应，再提取代码；提取失败仍保留原始材料及候选来源], [结合设计与实施记录核对，支持区分模型无正文、代码提取失败和工具执行错误],
      [检查结果绑定实际代码（Codex）], [按候选代码和检查器版本关联复检结果，逐用例保留覆盖缺项], [通过最小复现确认旧结果混用与覆盖遗漏问题，再修正记录和判定逻辑],
      [补全各阶段的必要输入（Codex）], [规划接收完整公开题面，检查器获得实际初始化规则，修复请求包含结构化诊断], [离线回归核对请求内容，使各阶段使用的约束与执行规则一致],
      [自动发现技能与迁移提示材料（Oh My Pi）], [统一技能目录发现方式，将提示材料整理为可维护的 Markdown 文件], [在独立副本完成测试，并通过假模型运行入口核对所选技能实际进入请求],
      table.hline(stroke: 0.8pt),
    )
  },
  caption: [已采纳建议及其核验依据],
) <tab-useful-suggestions>

这些建议主要改善了证据保存、检查一致性和提示接入。离线复现与假模型测试用于确认机制和调用路径，真实解题表现则按第 6 章的完整批次统计，两类结果分别评价。
