#pagebreak()
= 参考文献

#let entry(number, body) = block(breakable: false, above: 9pt, below: 9pt)[
  #set text(size: 10.5pt)
  #set par(first-line-indent: 0pt, leading: 0.65em, spacing: 5pt, justify: false)
  #grid(columns: (21pt, 1fr), gutter: 2pt, [#("[" + str(number) + "]")], body)
]
#v(4pt)
#entry(1)[THAKUR S, BLOCKLOVE J, PEARCE H, et al. AutoChip: Automating HDL Generation Using LLM Feedback[EB/OL]. 2023. #link("https://arxiv.org/abs/2311.04887").] <ref-autochip>
#v(4pt)
#entry(2)[ZHAO Y, ZHANG H, HUANG H, et al. MAGE: A Multi-Agent Engine for Automated RTL Code Generation[EB/OL]. 2024. #link("https://arxiv.org/abs/2412.07822").] <ref-mage>
#v(4pt)
#entry(3)[Qwen. Qwen3.8-27B：模型卡[EB/OL]. #link("https://huggingface.co/Qwen/Qwen3.8-27B").] <ref-model>
#v(4pt)
#entry(4)[ggml-org. Qwen3.8-27B-GGUF[EB/OL]. #link("https://huggingface.co/ggml-org/Qwen3.8-27B-GGUF").] <ref-weights>
#v(4pt)
#entry(5)[ggml-org. llama.cpp: LLM inference in C/C++[EB/OL]. #link("https://github.com/ggml-org/llama.cpp").] <ref-llama>
#v(4pt)
#entry(6)[AMD. Vivado Design Suite User Guide: Logic Simulation (UG900)[EB/OL]. #link("https://docs.amd.com/r/en-US/ug900-vivado-logic-simulation").] <ref-vivado>
#v(4pt)
#entry(7)[QIU R, ZHANG G L, DRECHSLER R, et al. CorrectBench: Automatic Testbench Generation with Functional Self-Correction using LLMs for HDL Design[EB/OL]. 2024. #link("https://arxiv.org/abs/2411.08510").] <ref-correctbench>
#v(4pt)
#entry(8)[PING H, LI S, ZHANG P, et al. HDLCoRe: A Training-Free Framework for Mitigating Hallucinations in LLM-Generated HDL[EB/OL]. 2025. #link("https://arxiv.org/abs/2503.16528").] <ref-hdlcore>
#v(4pt)
#entry(9)[NVIDIA. VerilogEval[EB/OL]. #link("https://github.com/NVlabs/verilog-eval").] <ref-verilogeval>
#v(4pt)
#entry(10)[PINCKNEY N, BATTEN C, LIU M, et al. Revisiting VerilogEval: A Year of Improvements in Large-Language Models for Hardware Code Generation[EB/OL]. 2024. #link("https://arxiv.org/abs/2408.11053").] <ref-evalpaper>
