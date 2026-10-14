# cvdp题集

自动生成，不要手改；在仓库根目录运行 `python3 43240-agent/dev/tools/datasets.py docs`。

来源：[https://github.com/NVlabs/cvdp_benchmark](https://github.com/NVlabs/cvdp_benchmark)；固定提交：`8e894cf74414ab1eaea1e2b4e80a02f123df07b6`。

本次登记5题，导入1题，未导入4题。导入不代表通过质量筛选；
逐题验证和排除原因见[候选清单](../../43240-agent/dev/datasets/catalog.json)。

## 导入方法与脚本

仅处理官方带答案公开样例中的RTL模块生成题，将LFSR的Cocotb测试改写为SystemVerilog，覆盖全部255个非零种子。其他公开样例要求补丁、测试台或文字解释；不代表完整CVDP。

本目录的[import.py](import.py)调用[统一转换器](../../43240-agent/dev/tools/datasets.py)，仅处理本来源。

先将上游仓库放到 `43240-agent/dev/datasets/upstream/cvdp`，检出上述固定提交。
许可证及NOTICE见[licenses](../../43240-agent/dev/datasets/licenses)。

以下命令从仓库根目录执行；`--out`是来源目录的父目录。已有题目不会被覆盖，复现时使用空目录。

```bash
python3 tasks/cvdp/import.py --out 43240-agent/dev/runs/reimport-cvdp --manifest 43240-agent/dev/runs/reimport-cvdp/conversion.json
```

## 如何选题

当前目录布局与跨来源选题见[题库索引](../index.md)。

只维护TXT清单，每行一个题号，支持空行与`#`注释；不创建选题副本目录。
本来源全量清单为[imported.txt](imported.txt)。跨来源清单可混写题号，实验配置的题目根目录设为`tasks/`。

## 已导入题目

| 题号 | 原始题号（如有） |
| --- | --- |
| [cvdp_copilot_lfsr_0001](cvdp_copilot_lfsr_0001/prompt.txt) | — |

## 未导入题目

| 题号 | 原因 |
| --- | --- |
| `cvdp_agentic_8x3_priority_encoder_0003` | 题目要求在工程上下文中提交补丁，不能直接等同单模块RTL生成 |
| `cvdp_agentic_fixed_arbiter_0001` | 题目要求在工程上下文中提交补丁，不能直接等同单模块RTL生成 |
| `cvdp_copilot_barrel_shifter_0031` | 题目要求生成测试台或文字解释，输出契约不是RTL模块 |
| `cvdp_copilot_gf_multiplier_0039` | 题目要求生成测试台或文字解释，输出契约不是RTL模块 |
