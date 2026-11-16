= 复现说明

== 构建准备

部署复用主办方基础环境，主要准备项见 @tab-build-preparation。

#show figure.where(kind: table): set figure.caption(position: top)
#show figure.where(kind: table): set block(breakable: true)
#figure(
  {
    set text(size: 10.5pt)
    set par(first-line-indent: 0pt, leading: 0.45em, justify: false)
    table(
      columns: (32mm, 1fr), inset: (x: 5pt, y: 4pt), stroke: none, align: left + top,
      table.hline(stroke: 0.8pt),
      table.header([*准备项*], [*要求*]),
      table.hline(stroke: 0.5pt),
      [基础环境], [使用主办方基础镜像，提供 AMD GPU 访问能力及匹配的 HIP、rocBLAS 组件],
      [Python 依赖], [按仓库依赖清单安装工作流、配置解析、模型通信与投题服务所需组件],
      [模型文件], [按模型声明准备 GGUF 主权重与 MTP 预测头，核对文件完整性后挂载使用],
      [EDA 工具], [加载 Vivado 环境和有效授权，保证编译、仿真及综合工具可调用],
      [工作目录], [为任务输出、运行记录和 EDA 临时工程准备可写的本地磁盘目录],
      table.hline(stroke: 0.8pt),
    )
  },
  caption: [部署前的环境与文件准备],
) <tab-build-preparation>

容器构建时安装依赖并复制方案文件，权重通过外部挂载提供。全部组件在断网运行前准备完成；题库、参考实现和开发日志不纳入方案运行包。
