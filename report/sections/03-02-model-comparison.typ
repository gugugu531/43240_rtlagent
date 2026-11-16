== 评估过并放弃的候选模型

#show figure.where(kind: table): set figure.caption(position: top)

模型选型重点考察难题上的生成能力，以及智能体能够针对哪些错误发挥作用。实验在 NVIDIA GPU 上使用 llama.cpp CUDA，采用由 ChipBench、RTLLM、VerilogEval 和示例题组成的固定 60 题测试集，基础、进阶和复杂题各 20 题。每题单次生成，限时 900 秒。

#figure(
  {
    set text(size: 10pt)
    set par(first-line-indent: 0pt, leading: 0.5em, justify: false)
    table(
      columns: (1fr, 17mm, 17mm, 17mm, 17mm, 20mm),
      inset: (x: 4pt, y: 6pt), stroke: none,
      align: (left + top, right + horizon, right + horizon, right + horizon, right + horizon, right + horizon),
      table.hline(stroke: 0.8pt),
      table.header([*模型及量化*], [*总体*], [*基础*], [*进阶*], [*复杂*], [*复杂题#linebreak()L3 题数*]),
      table.hline(stroke: 0.5pt),
      [Gemma-4-31B#linebreak()QAT Q4_0], [0.5533], [0.8100], [0.6400], [0.2100], [3/20],
      [Qwen3.6-35B-A3B#linebreak()Q4_K_M], [0.5400], [0.7300], [0.5700], [0.3200], [4/20],
      [Qwen3.8-27B#linebreak()Q4_K_M], [0.4333], [0.6100], [0.3300], [0.3600], [6/20],
      [Empero Qwen3.8-35B-A3B-Distill#linebreak()Q4_K_M], [0.4300], [0.7000], [0.3900], [0.2000], [2/20],
      table.hline(stroke: 0.8pt),
    )
  },
  caption: [固定 60 题测试集上的总体与分难度得分],
) <tab-model-baselines>

表中得分为各题判定系数的平均值，L3 表示编译、功能仿真和综合全部通过。Gemma-4-31B 和 Qwen3.6-35B-A3B 的总体得分较高，优势主要体现在基础与进阶题。Qwen3.8-27B 在复杂题上的得分为 0.3600，20 题中有 6 题达到 L3，这两项指标均为本批四款模型中最高。分难度结果使选型关注点从总体分数进一步转向复杂设计能力，为选择 Qwen3.8-27B 提供了依据。

完整 60 题的错误分析还表明，Qwen3.8-27B 的失分中包含较多 Verilog 声明和赋值规则错误。这些错误反映出模型在 RTL 语言规则的运用上不够稳定，也会使生成代码在编译阶段被阻断。

上述表现形成了本方案的选型理由：Qwen3.8-27B 在本批复杂题上表现较好，同时存在一批能够由编译工具明确定位的语言规则错误。智能体因此可以围绕声明、赋值和模块依赖提供针对性检查与反馈，并通过完整代码提取保留模型已经生成的实现。这一方向兼顾复杂题能力与错误修正空间，符合在保持较高增益得分的基础上提高能力得分的设计目标。模型与智能体结合后的整体收益在实测结果章节中分析。
