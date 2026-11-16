= 附录

== 关键实现清单

主要实现入口见 @tab-implementation-index，路径均相对于方案目录。可结合第 2、4 章，依次阅读工作流组织、节点实现、检查工具与运行管理，核对设计说明和实际执行逻辑。

#show figure.where(kind: table): set figure.caption(position: top)
#show figure.where(kind: table): set block(breakable: true)
#figure(
  {
    set text(size: 10.5pt)
    set par(first-line-indent: 0pt, leading: 0.45em, justify: false)
    table(
      columns: (90mm, 1fr), inset: (x: 5pt, y: 2.5pt), stroke: none, align: left + top,
      table.hline(stroke: 0.8pt),
      table.header([*实现入口*], [*阅读重点*]),
      table.hline(stroke: 0.5pt),
      [*工作流组织* #linebreak() #text(size: 9.5pt)[agent/orchestration/workflows/guided_verify.py]], [阶段配置、执行顺序与条件转移],
      [*规划、检查与修复* #linebreak() #text(size: 9.5pt)[agent/orchestration/nodes/guided.py]], [各阶段输入组织、归因、修复与空回复恢复],
      [*行为检查器* #linebreak() #text(size: 9.5pt)[agent/domain/rtl/guided_checker.py]], [能力限制、检查表解析、测试台生成与结果比较],
      [*检查规则与时间线* #linebreak() #text(size: 9.5pt)[agent/domain/rtl/guided_context.py]], [初始化约束、采样规则与输入事件展开],
      [*Vivado 工具适配* #linebreak() #text(size: 9.5pt)[agent/domain/rtl/vivado.py]], [编译与综合调用、结构诊断及日志摘要],
      [*答案保存与交付* #linebreak() #text(size: 9.5pt)[agent/submission/gateway.py]], [完整代码保存与最终答案输出],
      [*调用预算管理* #linebreak() #text(size: 9.5pt)[agent/runtime/allowance.py]], [模型调用与输出额度的分配及核对],
      [*运行记录* #linebreak() #text(size: 9.5pt)[agent/observability/recorder.py]], [执行事件与详细材料的关联保存],
      [*投题服务* #linebreak() #text(size: 9.5pt)[serve/serve_api.py]], [请求鉴权、排队、任务处理与响应],
      table.hline(stroke: 0.8pt),
    )
  },
  caption: [关键实现文件与阅读重点],
) <tab-implementation-index>

上述文件承担正式求解与记录职责。第 9 章所述日志回放查看器属于开发侧分析工具，用于读取保存的运行材料，与方案运行入口分开维护。
