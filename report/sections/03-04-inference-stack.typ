== 推理栈

方案采用 llama.cpp 的 HIP 后端#super(link(<ref-llama>, "[5]"))，兼顾生成吞吐与部署成本。在 W7900D 的短提示测速中，启用 MTP 后解码速度约为每分钟 2,640 token（TPM），较未启用时约 1,760 TPM 提高约 50%。ExLlamaV3 虽有更高的测速结果，但需要更换为 EXL3 权重、修补 ROCm 分支的编译问题并适配 HTTP 服务。HIP 则可复用已有 GGUF 权重、MTP 预测头及 HTTP 接口，部署改动较少，因此选为默认后端。主要配置见 @tab-inference-stack。

#show figure.where(kind: table): set figure.caption(position: top)
#figure(
  {
    set text(size: 10.5pt)
    set par(first-line-indent: 0pt, leading: 0.5em, justify: false)
    table(
      columns: (34mm, 1fr),
      inset: (x: 6pt, y: 3pt), stroke: none, align: left + top,
      table.hline(stroke: 0.8pt),
      table.header([*项目*], [*配置*]),
      table.hline(stroke: 0.5pt),
      [后端与加载], [llama.cpp 0.4.0-dev（HIP）；主模型与 MTP 预测头全部加载到 GPU],
      [推测解码], [MTP（多 token 预测），每次最多预测 3 个 token；预测头采用 Q4_0 量化],
      [计算与调度], [Flash Attention，FP16 键值缓存；单请求推理，投题服务按队列顺序处理任务],
      table.hline(stroke: 0.8pt),
    )
  },
  caption: [推理服务的主要配置],
) <tab-inference-stack>
