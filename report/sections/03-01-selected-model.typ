= 模型与推理栈

== 最终选用的模型

本方案选用 Qwen3.8-27B 的 Q4_K_M 量化权重#super(link(<ref-model>, "[3]"))#super(link(<ref-weights>, "[4]"))，主要配置见 @tab-selected-model。

#show figure.where(kind: table): set figure.caption(position: top)

#figure(
  {
    set text(size: 10.5pt)
    set par(first-line-indent: 0pt, leading: 0.55em, justify: false)
    table(
      columns: (34mm, 1fr),
      inset: (x: 7pt, y: 5pt),
      stroke: none,
      align: left + top,
      table.hline(stroke: 0.8pt),
      table.header([*项目*], [*选用配置*]),
      table.hline(stroke: 0.5pt),
      [模型], [Qwen/Qwen3.8-27B],
      [权重来源], [#link("https://huggingface.co/ggml-org/Qwen3.8-27B-GGUF/tree/a316ea527fde32c12487be7574e2db5ac2ad2a7e")[https://huggingface.co/ggml-org/Qwen3.8-27B-GGUF]],
      [权重仓库提交], [a316ea52],
      [文件格式与量化], [GGUF；主权重采用 Q4_K_M],
      [主权重文件大小], [18.97 GB],
      [服务上下文长度], [65,536 token],
      [思考设置], [开启思考，中等强度],
      [采样设置], [temperature 为 0.0，top_p 为 1.0],
      [RoPE 设置], [采用默认设置，无额外外推配置],
      [设备显存占用], [23.67 GiB],
      table.hline(stroke: 0.8pt),
    )
  },
  caption: [最终模型与主要配置],
) <tab-selected-model>
