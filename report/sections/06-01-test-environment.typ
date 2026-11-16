= 实测结果

== 测试环境

本章记录当前工作流在 VerilogEval 公开题集#super(link(<ref-verilogeval>, "[9]"))#super(link(<ref-evalpaper>, "[10]"))上的完整测试结果。测试采用规划、生成、结构检查、行为验证与反馈修复流程，关闭知识检索，每题保留一次首跑结果。实验环境与题集范围见 @tab-test-environment。

#show figure.where(kind: table): set figure.caption(position: top)
#figure(
  {
    set text(size: 10.5pt)
    set par(first-line-indent: 0pt, leading: 0.45em, justify: false)
    table(
      columns: (34mm, 1fr), inset: (x: 5pt, y: 4pt), stroke: none, align: left + top,
      table.hline(stroke: 0.8pt),
      table.header([*项目*], [*实验条件*]),
      table.hline(stroke: 0.5pt),
      [题集], [VerilogEval，按主办方清单排除 11 道缺陷题，保留 145 题],
      [推理硬件], [AMD Radeon GPU],
      [模型与后端], [Qwen3.8-27B Q4_K_M，llama.cpp HIP，启用 MTP 推测解码],
      [思考设置], [开启思考，采用中等强度],
      [采样与预算], [每题一次首跑，采用赛事单题时限],
      [判定工具], [主办方自测流程，Vivado 2026.1],
      table.hline(stroke: 0.8pt),
    )
  },
  caption: [测试环境与题集范围],
) <tab-test-environment>

本批测试固定源码、题面和阶段配置，结果对应测试时的参数设置。求解端仅接收公开题面；全部答案保存后，独立执行编译、仿真与综合判定，官方测试台和判定反馈不进入模型上下文。

统计保留首跑中的失败、空答案和超时，不以补测结果替换。仿真通过同时核对实际采样与比较结果，求解耗时和模型调用成本与独立判定开销分别记录。
