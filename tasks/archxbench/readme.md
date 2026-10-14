# archxbench题集

自动生成，不要手改；在仓库根目录运行 `python3 43240-agent/dev/tools/datasets.py docs`。

来源：[https://github.com/sureshpurini/ArchXBench](https://github.com/sureshpurini/ArchXBench)；固定提交：`0db0d0de25aad5238393d51bd97ce952e579fa1a`。

本次登记71题，导入3题，未导入68题。导入不代表通过质量筛选；
逐题验证和排除原因见[候选清单](../../43240-agent/dev/datasets/catalog.json)。

## 导入方法与脚本

平方根、脉动阵列矩阵乘法和AES使用本地独立参考实现。平方根保留上游测试；另两题采用本地测试台与独立数学/上游Python模型。其余题缺少完整RTL参考答案或需要外部判定，暂未导入。改编版不能等同上游官方成绩。

本目录的[import.py](import.py)调用[统一转换器](../../43240-agent/dev/tools/datasets.py)，仅处理本来源。

本地适配见[ArchXBench适配器](../../43240-agent/dev/tools/archxbench_adapter.py)。

先将上游仓库放到 `43240-agent/dev/datasets/upstream/archxbench`，检出上述固定提交。
许可证及NOTICE见[licenses](../../43240-agent/dev/datasets/licenses)。

以下命令从仓库根目录执行；`--out`是来源目录的父目录。已有题目不会被覆盖，复现时使用空目录。

```bash
python3 tasks/archxbench/import.py --out 43240-agent/dev/runs/reimport-archxbench --manifest 43240-agent/dev/runs/reimport-archxbench/conversion.json
```

## 如何选题

只维护TXT清单，每行一个题号，支持空行与`#`注释；不创建选题副本目录。
本来源全量清单为[imported.txt](imported.txt)。跨来源清单可混写题号，实验配置的题目根目录设为`tasks/`。

## 已导入题目

| 题号 | 原始题号（如有） |
| --- | --- |
| [archxbench_level_3_newton_raphson_sqrt](archxbench_level_3_newton_raphson_sqrt/prompt.txt) | — |
| [archxbench_level_5_systolic_gemm](archxbench_level_5_systolic_gemm/prompt.txt) | — |
| [archxbench_level_6_aes_encryption](archxbench_level_6_aes_encryption/prompt.txt) | — |

## 未导入题目

| 题号 | 原因 |
| --- | --- |
| `archxbench_level_0_binary-encoder` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_0_bitmanip-unit` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_0_clock-divide-by-2` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_0_comparator-4bit` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_0_comparator-8bit` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_0_decoder-2to4` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_0_decoder-3to8` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_0_demux-1to2` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_0_demux-1to4` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_0_down-counter` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_0_gray-counter` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_0_johnson-counter` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_0_mux2to1` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_0_mux4to1` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_0_piso-regs` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_0_priority-encoder` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_0_ring-counter` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_0_sipo-regs` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_0_siso-regs` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_0_up-counter` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_1a_aes_sbox` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_1a_barrel_shifter` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_1a_cla_8bit` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_1a_gf2_8_multiplier` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_1a_lfsr_stream_cipher` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_1a_rca_32bit` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_1b_approximate_adder` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_1b_carry_select_adder_32bit` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_1b_carry_skip_adder_32bit` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_1b_parametric_shift_add_multiplier` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_1b_rca_32bit_with_4bit_cla` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_1c_booth_multiplier` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_1c_brent_kung_32bit` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_1c_constant_divider` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_1c_dadda_multiplier` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_1c_divider_restoring` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_1c_kogge_stone_32bit` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_1c_wallace_multiplier` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_2_aes128_single_round` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_2_cla_32bit_pipe` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_2_dadda_mult_pipe` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_2_dadda_mult_pipe_4bit` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_2_rca_32bit_pipe` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_2_wallace_tree_mult_pipe` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_3_fp_adder` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_3_fp_multiplier` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_3_gauss_seidel` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_3_gradient_descent` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_3_newton_raphson_polynomial` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_4_band_pass_fir` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_4_fft_ifft_16pt_iterative` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_4_fp_adder_pipeline` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_4_fp_mult_pipeline` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_4_high_pass_fir` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_4_low_pass_fir` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_5_conv1d` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_5_conv2d` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_5_dct_idct_8pt_pipelined` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_5_harris_corner_detection` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_5_unsharp_mask` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_6_aes_decryption` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_6_conv_3d` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_6_fft_streaming_64pt` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_6_fp_band_pass_fir` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_6_fp_high_pass_fir` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_6_fp_low_pass_fir` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_6_multich_conv2d` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
| `archxbench_level_6_quantized_matmul` | 上游未提供完整参考 RTL，不能伪造 reference/solution.sv；外部判定需另行适配 |
