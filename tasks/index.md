# 题库

本文是团队维护的当前题库入口；同目录 `README.md` 保留主办方最初三道示例的说明，
其目录路径不代表当前布局。来源目录的清单由开发工具生成，本文维护选题与阅读导航。

题目按来源保存，每道题只有一份。选题只维护TXT清单，不再建立 `pool/` 或 `balanced/` 题目副本目录。
各来源目录的说明包含固定版本、导入方法和脚本、全部已导入题目，以及未导入题目的逐题原因。

| 来源 | 已导入 | 未导入（本次登记范围） | 说明与脚本 | 全量选题清单 |
| --- | ---: | ---: | --- | --- |
| VerilogEval | 156 | 0 | [说明](verilogeval/readme.md)、[导入](verilogeval/import.py) | [imported.txt](verilogeval/imported.txt) |
| 赛事示例 | 3 | 0 | [说明](example/readme.md)、[导入](example/import.py) | [imported.txt](example/imported.txt) |
| ChipBench | 45 | 0 | [说明](chipbench/readme.md)、[导入](chipbench/import.py) | [imported.txt](chipbench/imported.txt) |
| RTLLM | 50 | 0 | [说明](rtllm/readme.md)、[导入](rtllm/import.py) | [imported.txt](rtllm/imported.txt) |
| ArchXBench | 3 | 68 | [说明](archxbench/readme.md)、[导入](archxbench/import.py) | [imported.txt](archxbench/imported.txt) |
| CVDP公开样例 | 1 | 4 | [说明](cvdp/readme.md)、[导入](cvdp/import.py) | [imported.txt](cvdp/imported.txt) |

合计258道已导入题、72条未导入记录。CVDP只覆盖官方带答案公开样例，ArchXBench有本地改编，均不代表完整上游官方评测。
导入不等于通过质量门槛；当前241题通过质量筛选和去重，默认均衡清单选取其中60题。

## 目录与选题

```text
tasks/
  <来源>/
    readme.md
    import.py
    imported.txt
    <题号>/
      prompt.txt
      top.txt
      task.json
      ref.sv
      tb.sv
      reference/solution.sv
```

跨来源的TXT每行写一个题号，支持空行和整行 `#` 注释，例如：

```text
example_ex03_lfsr8
rtllm_adder_8bit
```

默认均衡清单为[balanced.txt](../43240-agent/dev/configs/balanced.txt)，配置为[balanced.yaml](../43240-agent/dev/configs/balanced.yaml)。
只更改TXT即可调整选题；新增方案只需换用另一份TXT。配置中的根目录和清单路径均相对YAML所在目录解析：

```yaml
experiment:
  tasks:
    root: ../../../tasks
    list: balanced.txt
```

原有 `Prob...`、`ex03_lfsr8` 等题号仍可在TXT或 `--task` 中使用；直接传目录时须使用新的来源路径。
从 `43240-agent/` 目录运行：

```bash
LLM_BACKEND=mock python3 dev/tools/run.py --config dev/configs/balanced.yaml --task ex03_lfsr8
python3 dev/tools/validate_datasets.py --list dev/configs/balanced.txt
```

原始官方自测入口不会递归发现来源目录，直接调用时须传 `--tasks ../tasks/verilogeval` 等单来源目录。
跨来源选题用统一实验入口，参考答案验证用上述开发工具；判定仍调用未修改的官方脚本。

题库与参考答案纳入Git，但不随参赛方案打包。完整适配、质量门槛和复现流程见[开发题集说明](../43240-agent/dev/docs/design/datasets.md)。
