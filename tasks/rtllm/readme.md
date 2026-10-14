# rtllm题集

自动生成，不要手改；在仓库根目录运行 `python3 43240-agent/dev/tools/datasets.py docs`。

来源：[https://github.com/hkust-zhiyao/RTLLM](https://github.com/hkust-zhiyao/RTLLM)；固定提交：`51ed553d0ffd32797a1a0a13e051656bf302c81f`。

本次登记50题，导入50题，未导入0题。导入不代表通过质量筛选；
逐题验证和排除原因见[候选清单](../../43240-agent/dev/datasets/catalog.json)。

## 导入方法与脚本

保留原始规格、激励和断言；测试数据嵌入测试台，统一模块名称与成功/失败出口，并处理SystemVerilog保留字。一次完整测试台判定计为一个样本。

本目录的[import.py](import.py)调用[统一转换器](../../43240-agent/dev/tools/datasets.py)，仅处理本来源。

先将上游仓库放到 `43240-agent/dev/datasets/upstream/rtllm`，检出上述固定提交。
许可证及NOTICE见[licenses](../../43240-agent/dev/datasets/licenses)。

以下命令从仓库根目录执行；`--out`是来源目录的父目录。已有题目不会被覆盖，复现时使用空目录。

```bash
python3 tasks/rtllm/import.py --out 43240-agent/dev/runs/reimport-rtllm --manifest 43240-agent/dev/runs/reimport-rtllm/conversion.json
```

## 如何选题

当前目录布局与跨来源选题见[题库索引](../index.md)。

只维护TXT清单，每行一个题号，支持空行与`#`注释；不创建选题副本目录。
本来源全量清单为[imported.txt](imported.txt)。跨来源清单可混写题号，实验配置的题目根目录设为`tasks/`。

## 已导入题目

| 题号 | 原始题号（如有） |
| --- | --- |
| [rtllm_accu](rtllm_accu/prompt.txt) | — |
| [rtllm_adder_16bit](rtllm_adder_16bit/prompt.txt) | — |
| [rtllm_adder_32bit](rtllm_adder_32bit/prompt.txt) | — |
| [rtllm_adder_8bit](rtllm_adder_8bit/prompt.txt) | — |
| [rtllm_adder_bcd](rtllm_adder_bcd/prompt.txt) | — |
| [rtllm_adder_pipe_64bit](rtllm_adder_pipe_64bit/prompt.txt) | — |
| [rtllm_alu](rtllm_alu/prompt.txt) | — |
| [rtllm_asyn_fifo](rtllm_asyn_fifo/prompt.txt) | — |
| [rtllm_barrel_shifter](rtllm_barrel_shifter/prompt.txt) | — |
| [rtllm_calendar](rtllm_calendar/prompt.txt) | — |
| [rtllm_clkgenerator](rtllm_clkgenerator/prompt.txt) | — |
| [rtllm_comparator_3bit](rtllm_comparator_3bit/prompt.txt) | — |
| [rtllm_comparator_4bit](rtllm_comparator_4bit/prompt.txt) | — |
| [rtllm_counter_12](rtllm_counter_12/prompt.txt) | — |
| [rtllm_div_16bit](rtllm_div_16bit/prompt.txt) | — |
| [rtllm_edge_detect](rtllm_edge_detect/prompt.txt) | — |
| [rtllm_fixed_point_adder](rtllm_fixed_point_adder/prompt.txt) | — |
| [rtllm_fixed_point_substractor](rtllm_fixed_point_substractor/prompt.txt) | — |
| [rtllm_float_multi](rtllm_float_multi/prompt.txt) | — |
| [rtllm_freq_div](rtllm_freq_div/prompt.txt) | — |
| [rtllm_freq_divbyeven](rtllm_freq_divbyeven/prompt.txt) | — |
| [rtllm_freq_divbyfrac](rtllm_freq_divbyfrac/prompt.txt) | — |
| [rtllm_freq_divbyodd](rtllm_freq_divbyodd/prompt.txt) | — |
| [rtllm_fsm](rtllm_fsm/prompt.txt) | — |
| [rtllm_instr_reg](rtllm_instr_reg/prompt.txt) | — |
| [rtllm_jc_counter](rtllm_jc_counter/prompt.txt) | — |
| [rtllm_lfsr](rtllm_lfsr/prompt.txt) | — |
| [rtllm_lifobuffer](rtllm_lifobuffer/prompt.txt) | — |
| [rtllm_multi_16bit](rtllm_multi_16bit/prompt.txt) | — |
| [rtllm_multi_8bit](rtllm_multi_8bit/prompt.txt) | — |
| [rtllm_multi_booth_8bit](rtllm_multi_booth_8bit/prompt.txt) | — |
| [rtllm_multi_pipe_4bit](rtllm_multi_pipe_4bit/prompt.txt) | — |
| [rtllm_multi_pipe_8bit](rtllm_multi_pipe_8bit/prompt.txt) | — |
| [rtllm_parallel2serial](rtllm_parallel2serial/prompt.txt) | — |
| [rtllm_pe](rtllm_pe/prompt.txt) | — |
| [rtllm_pulse_detect](rtllm_pulse_detect/prompt.txt) | — |
| [rtllm_radix2_div](rtllm_radix2_div/prompt.txt) | — |
| [rtllm_ram](rtllm_ram/prompt.txt) | — |
| [rtllm_right_shifter](rtllm_right_shifter/prompt.txt) | — |
| [rtllm_ring_counter](rtllm_ring_counter/prompt.txt) | — |
| [rtllm_rom](rtllm_rom/prompt.txt) | — |
| [rtllm_sequence_detector](rtllm_sequence_detector/prompt.txt) | — |
| [rtllm_serial2parallel](rtllm_serial2parallel/prompt.txt) | — |
| [rtllm_signal_generator](rtllm_signal_generator/prompt.txt) | — |
| [rtllm_square_wave](rtllm_square_wave/prompt.txt) | — |
| [rtllm_sub_64bit](rtllm_sub_64bit/prompt.txt) | — |
| [rtllm_synchronizer](rtllm_synchronizer/prompt.txt) | — |
| [rtllm_traffic_light](rtllm_traffic_light/prompt.txt) | — |
| [rtllm_up_down_counter](rtllm_up_down_counter/prompt.txt) | — |
| [rtllm_width_8to16](rtllm_width_8to16/prompt.txt) | — |

## 未导入题目

本次登记范围内没有未导入题目。
