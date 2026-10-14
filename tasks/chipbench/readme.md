# chipbench题集

自动生成，不要手改；在仓库根目录运行 `python3 43240-agent/dev/tools/datasets.py docs`。

来源：[https://github.com/zhongkaiyu/ChipBench](https://github.com/zhongkaiyu/ChipBench)；固定提交：`b4ba3a06759804ec88c26c3cf15b28b9a90b3443`。

本次登记45题，导入45题，未导入0题。导入不代表通过质量筛选；
逐题验证和排除原因见[候选清单](../../43240-agent/dev/datasets/catalog.json)。

## 导入方法与脚本

保留公开题面、参考RTL和激励；补全公开子模块与宏，隔离参考模块名称，统一最终统计行。

本目录的[import.py](import.py)调用[统一转换器](../../43240-agent/dev/tools/datasets.py)，仅处理本来源。

先将上游仓库放到 `43240-agent/dev/datasets/upstream/chipbench`，检出上述固定提交。
许可证及NOTICE见[licenses](../../43240-agent/dev/datasets/licenses)。

以下命令从仓库根目录执行；`--out`是来源目录的父目录。已有题目不会被覆盖，复现时使用空目录。

```bash
python3 tasks/chipbench/import.py --out 43240-agent/dev/runs/reimport-chipbench --manifest 43240-agent/dev/runs/reimport-chipbench/conversion.json
```

## 如何选题

当前目录布局与跨来源选题见[题库索引](../index.md)。

只维护TXT清单，每行一个题号，支持空行与`#`注释；不创建选题副本目录。
本来源全量清单为[imported.txt](imported.txt)。跨来源清单可混写题号，实验配置的题目根目录设为`tasks/`。

## 已导入题目

| 题号 | 原始题号（如有） |
| --- | --- |
| [chipbench_cpu_ip_prob001_controller](chipbench_cpu_ip_prob001_controller/prompt.txt) | — |
| [chipbench_cpu_ip_prob002_alu](chipbench_cpu_ip_prob002_alu/prompt.txt) | — |
| [chipbench_cpu_ip_prob003_regfile](chipbench_cpu_ip_prob003_regfile/prompt.txt) | — |
| [chipbench_cpu_ip_prob004_branch_unit](chipbench_cpu_ip_prob004_branch_unit/prompt.txt) | — |
| [chipbench_cpu_ip_prob005_alu_controller](chipbench_cpu_ip_prob005_alu_controller/prompt.txt) | — |
| [chipbench_cpu_ip_prob006_pc_reg](chipbench_cpu_ip_prob006_pc_reg/prompt.txt) | — |
| [chipbench_cpu_ip_prob007_div](chipbench_cpu_ip_prob007_div/prompt.txt) | — |
| [chipbench_cpu_ip_prob008_chapter12_ctrl](chipbench_cpu_ip_prob008_chapter12_ctrl/prompt.txt) | — |
| [chipbench_cpu_ip_prob009_cp0_reg](chipbench_cpu_ip_prob009_cp0_reg/prompt.txt) | — |
| [chipbench_not_self_contain_prob001_submodules_to_implement_comparison_of_three_input_numbers](chipbench_not_self_contain_prob001_submodules_to_implement_comparison_of_three_input_numbers/prompt.txt) | — |
| [chipbench_not_self_contain_prob002_implement_full_subtractor_using_three_to_eight_decoder](chipbench_not_self_contain_prob002_implement_full_subtractor_using_three_to_eight_decoder/prompt.txt) | — |
| [chipbench_not_self_contain_prob003_asynchronous_fifo](chipbench_not_self_contain_prob003_asynchronous_fifo/prompt.txt) | — |
| [chipbench_not_self_contain_prob004_synchronous_fifo](chipbench_not_self_contain_prob004_synchronous_fifo/prompt.txt) | — |
| [chipbench_not_self_contain_prob005_8_bit_alu](chipbench_not_self_contain_prob005_8_bit_alu/prompt.txt) | — |
| [chipbench_not_self_contain_prob006_cpu_top](chipbench_not_self_contain_prob006_cpu_top/prompt.txt) | — |
| [chipbench_self_contain_prob000_four-to-one_multiplexer](chipbench_self_contain_prob000_four-to-one_multiplexer/prompt.txt) | — |
| [chipbench_self_contain_prob001_continuous_input_sequence_detect](chipbench_self_contain_prob001_continuous_input_sequence_detect/prompt.txt) | — |
| [chipbench_self_contain_prob002_extraneous_items_sequence_detect](chipbench_self_contain_prob002_extraneous_items_sequence_detect/prompt.txt) | — |
| [chipbench_self_contain_prob003_non-overlapping_sequence_detect](chipbench_self_contain_prob003_non-overlapping_sequence_detect/prompt.txt) | — |
| [chipbench_self_contain_prob004_continuous_input_sequence_detect2](chipbench_self_contain_prob004_continuous_input_sequence_detect2/prompt.txt) | — |
| [chipbench_self_contain_prob005_signal_generator](chipbench_self_contain_prob005_signal_generator/prompt.txt) | — |
| [chipbench_self_contain_prob006_data_serial-to-parallel_circuit](chipbench_self_contain_prob006_data_serial-to-parallel_circuit/prompt.txt) | — |
| [chipbench_self_contain_prob007_data_accumulation_output](chipbench_self_contain_prob007_data_accumulation_output/prompt.txt) | — |
| [chipbench_self_contain_prob008_non-integer_data_width_conversion_24to128](chipbench_self_contain_prob008_non-integer_data_width_conversion_24to128/prompt.txt) | — |
| [chipbench_self_contain_prob009_non-integer_data_width_conversion_8to12](chipbench_self_contain_prob009_non-integer_data_width_conversion_8to12/prompt.txt) | — |
| [chipbench_self_contain_prob010_integer_multiple_data_bit_width_conversion_8to16](chipbench_self_contain_prob010_integer_multiple_data_bit_width_conversion_8to16/prompt.txt) | — |
| [chipbench_self_contain_prob011_4-bit_carry_look-ahead_adder_circuit](chipbench_self_contain_prob011_4-bit_carry_look-ahead_adder_circuit/prompt.txt) | — |
| [chipbench_self_contain_prob012_state_machine_overlapping_sequence_detection](chipbench_self_contain_prob012_state_machine_overlapping_sequence_detection/prompt.txt) | — |
| [chipbench_self_contain_prob013_least_common_multiple](chipbench_self_contain_prob013_least_common_multiple/prompt.txt) | — |
| [chipbench_self_contain_prob014_sequence_generator](chipbench_self_contain_prob014_sequence_generator/prompt.txt) | — |
| [chipbench_self_contain_prob015_vending_machine2](chipbench_self_contain_prob015_vending_machine2/prompt.txt) | — |
| [chipbench_self_contain_prob016_odd-number_division_with_a_duty_cycle_of_half](chipbench_self_contain_prob016_odd-number_division_with_a_duty_cycle_of_half/prompt.txt) | — |
| [chipbench_self_contain_prob017_arbitrary_fractional_frequency_division](chipbench_self_contain_prob017_arbitrary_fractional_frequency_division/prompt.txt) | — |
| [chipbench_self_contain_prob020_write_state_machine_two_stage](chipbench_self_contain_prob020_write_state_machine_two_stage/prompt.txt) | — |
| [chipbench_self_contain_prob023_gray_code_counter](chipbench_self_contain_prob023_gray_code_counter/prompt.txt) | — |
| [chipbench_self_contain_prob024_multiplication_and_bitwise_operations](chipbench_self_contain_prob024_multiplication_and_bitwise_operations/prompt.txt) | — |
| [chipbench_self_contain_prob025_pulse_synchronization_circuit](chipbench_self_contain_prob025_pulse_synchronization_circuit/prompt.txt) | — |
| [chipbench_self_contain_prob026_simple_stopwatch](chipbench_self_contain_prob026_simple_stopwatch/prompt.txt) | — |
| [chipbench_self_contain_prob027_settable_counter](chipbench_self_contain_prob027_settable_counter/prompt.txt) | — |
| [chipbench_self_contain_prob028_up_and_down_counter](chipbench_self_contain_prob028_up_and_down_counter/prompt.txt) | — |
| [chipbench_self_contain_prob030_simple_implementation_ram](chipbench_self_contain_prob030_simple_implementation_ram/prompt.txt) | — |
| [chipbench_self_contain_prob031_johnson_counter](chipbench_self_contain_prob031_johnson_counter/prompt.txt) | — |
| [chipbench_self_contain_prob032_pipeline_multiplier](chipbench_self_contain_prob032_pipeline_multiplier/prompt.txt) | — |
| [chipbench_self_contain_prob033_traffic_lights](chipbench_self_contain_prob033_traffic_lights/prompt.txt) | — |
| [chipbench_self_contain_prob034_gaming_machine_billing_program](chipbench_self_contain_prob034_gaming_machine_billing_program/prompt.txt) | — |

## 未导入题目

本次登记范围内没有未导入题目。
