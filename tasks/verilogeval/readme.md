# verilogeval题集

自动生成，不要手改；在仓库根目录运行 `python3 43240-agent/dev/tools/datasets.py docs`。

来源：[https://github.com/gugugu531/AMD_SocChina_2026](https://github.com/gugugu531/AMD_SocChina_2026)；固定提交：`7f1014925d5b83e737db02fb08045014a1ec4f54`。

本次登记156题，导入156题，未导入0题。导入不代表通过质量筛选；
逐题验证和排除原因见[候选清单](../../43240-agent/dev/datasets/catalog.json)。

## 导入方法与脚本

从本仓库固定提交恢复主办方适配的156道VerilogEval题，保留题面、参考答案及测试台，统一目录题号并保存original_task_id别名。

本目录的[import.py](import.py)调用[统一转换器](../../43240-agent/dev/tools/datasets.py)，仅处理本来源。

使用 `git archive` 从上述提交读取原始题目；无需额外下载。克隆时须保留该提交的Git历史。

以下命令从仓库根目录执行；`--out`是来源目录的父目录。已有题目不会被覆盖，复现时使用空目录。

```bash
python3 tasks/verilogeval/import.py --out 43240-agent/dev/runs/reimport-verilogeval --manifest 43240-agent/dev/runs/reimport-verilogeval/conversion.json
```

## 如何选题

只维护TXT清单，每行一个题号，支持空行与`#`注释；不创建选题副本目录。
本来源全量清单为[imported.txt](imported.txt)。跨来源清单可混写题号，实验配置的题目根目录设为`tasks/`。

## 已导入题目

| 题号 | 原始题号（如有） |
| --- | --- |
| [verilogeval_prob001_zero](verilogeval_prob001_zero/prompt.txt) | Prob001_zero |
| [verilogeval_prob002_m2014_q4i](verilogeval_prob002_m2014_q4i/prompt.txt) | Prob002_m2014_q4i |
| [verilogeval_prob003_step_one](verilogeval_prob003_step_one/prompt.txt) | Prob003_step_one |
| [verilogeval_prob004_vector2](verilogeval_prob004_vector2/prompt.txt) | Prob004_vector2 |
| [verilogeval_prob005_notgate](verilogeval_prob005_notgate/prompt.txt) | Prob005_notgate |
| [verilogeval_prob006_vectorr](verilogeval_prob006_vectorr/prompt.txt) | Prob006_vectorr |
| [verilogeval_prob007_wire](verilogeval_prob007_wire/prompt.txt) | Prob007_wire |
| [verilogeval_prob008_m2014_q4h](verilogeval_prob008_m2014_q4h/prompt.txt) | Prob008_m2014_q4h |
| [verilogeval_prob009_popcount3](verilogeval_prob009_popcount3/prompt.txt) | Prob009_popcount3 |
| [verilogeval_prob010_mt2015_q4a](verilogeval_prob010_mt2015_q4a/prompt.txt) | Prob010_mt2015_q4a |
| [verilogeval_prob011_norgate](verilogeval_prob011_norgate/prompt.txt) | Prob011_norgate |
| [verilogeval_prob012_xnorgate](verilogeval_prob012_xnorgate/prompt.txt) | Prob012_xnorgate |
| [verilogeval_prob013_m2014_q4e](verilogeval_prob013_m2014_q4e/prompt.txt) | Prob013_m2014_q4e |
| [verilogeval_prob014_andgate](verilogeval_prob014_andgate/prompt.txt) | Prob014_andgate |
| [verilogeval_prob015_vector1](verilogeval_prob015_vector1/prompt.txt) | Prob015_vector1 |
| [verilogeval_prob016_m2014_q4j](verilogeval_prob016_m2014_q4j/prompt.txt) | Prob016_m2014_q4j |
| [verilogeval_prob017_mux2to1v](verilogeval_prob017_mux2to1v/prompt.txt) | Prob017_mux2to1v |
| [verilogeval_prob018_mux256to1](verilogeval_prob018_mux256to1/prompt.txt) | Prob018_mux256to1 |
| [verilogeval_prob019_m2014_q4f](verilogeval_prob019_m2014_q4f/prompt.txt) | Prob019_m2014_q4f |
| [verilogeval_prob020_mt2015_eq2](verilogeval_prob020_mt2015_eq2/prompt.txt) | Prob020_mt2015_eq2 |
| [verilogeval_prob021_mux256to1v](verilogeval_prob021_mux256to1v/prompt.txt) | Prob021_mux256to1v |
| [verilogeval_prob022_mux2to1](verilogeval_prob022_mux2to1/prompt.txt) | Prob022_mux2to1 |
| [verilogeval_prob023_vector100r](verilogeval_prob023_vector100r/prompt.txt) | Prob023_vector100r |
| [verilogeval_prob024_hadd](verilogeval_prob024_hadd/prompt.txt) | Prob024_hadd |
| [verilogeval_prob025_reduction](verilogeval_prob025_reduction/prompt.txt) | Prob025_reduction |
| [verilogeval_prob026_alwaysblock1](verilogeval_prob026_alwaysblock1/prompt.txt) | Prob026_alwaysblock1 |
| [verilogeval_prob027_fadd](verilogeval_prob027_fadd/prompt.txt) | Prob027_fadd |
| [verilogeval_prob028_m2014_q4a](verilogeval_prob028_m2014_q4a/prompt.txt) | Prob028_m2014_q4a |
| [verilogeval_prob029_m2014_q4g](verilogeval_prob029_m2014_q4g/prompt.txt) | Prob029_m2014_q4g |
| [verilogeval_prob030_popcount255](verilogeval_prob030_popcount255/prompt.txt) | Prob030_popcount255 |
| [verilogeval_prob031_dff](verilogeval_prob031_dff/prompt.txt) | Prob031_dff |
| [verilogeval_prob032_vector0](verilogeval_prob032_vector0/prompt.txt) | Prob032_vector0 |
| [verilogeval_prob033_ece241_2014_q1c](verilogeval_prob033_ece241_2014_q1c/prompt.txt) | Prob033_ece241_2014_q1c |
| [verilogeval_prob034_dff8](verilogeval_prob034_dff8/prompt.txt) | Prob034_dff8 |
| [verilogeval_prob035_count1to10](verilogeval_prob035_count1to10/prompt.txt) | Prob035_count1to10 |
| [verilogeval_prob036_ringer](verilogeval_prob036_ringer/prompt.txt) | Prob036_ringer |
| [verilogeval_prob037_review2015_count1k](verilogeval_prob037_review2015_count1k/prompt.txt) | Prob037_review2015_count1k |
| [verilogeval_prob038_count15](verilogeval_prob038_count15/prompt.txt) | Prob038_count15 |
| [verilogeval_prob039_always_if](verilogeval_prob039_always_if/prompt.txt) | Prob039_always_if |
| [verilogeval_prob040_count10](verilogeval_prob040_count10/prompt.txt) | Prob040_count10 |
| [verilogeval_prob041_dff8r](verilogeval_prob041_dff8r/prompt.txt) | Prob041_dff8r |
| [verilogeval_prob042_vector4](verilogeval_prob042_vector4/prompt.txt) | Prob042_vector4 |
| [verilogeval_prob043_vector5](verilogeval_prob043_vector5/prompt.txt) | Prob043_vector5 |
| [verilogeval_prob044_vectorgates](verilogeval_prob044_vectorgates/prompt.txt) | Prob044_vectorgates |
| [verilogeval_prob045_edgedetect2](verilogeval_prob045_edgedetect2/prompt.txt) | Prob045_edgedetect2 |
| [verilogeval_prob046_dff8p](verilogeval_prob046_dff8p/prompt.txt) | Prob046_dff8p |
| [verilogeval_prob047_dff8ar](verilogeval_prob047_dff8ar/prompt.txt) | Prob047_dff8ar |
| [verilogeval_prob048_m2014_q4c](verilogeval_prob048_m2014_q4c/prompt.txt) | Prob048_m2014_q4c |
| [verilogeval_prob049_m2014_q4b](verilogeval_prob049_m2014_q4b/prompt.txt) | Prob049_m2014_q4b |
| [verilogeval_prob050_kmap1](verilogeval_prob050_kmap1/prompt.txt) | Prob050_kmap1 |
| [verilogeval_prob051_gates4](verilogeval_prob051_gates4/prompt.txt) | Prob051_gates4 |
| [verilogeval_prob052_gates100](verilogeval_prob052_gates100/prompt.txt) | Prob052_gates100 |
| [verilogeval_prob053_m2014_q4d](verilogeval_prob053_m2014_q4d/prompt.txt) | Prob053_m2014_q4d |
| [verilogeval_prob054_edgedetect](verilogeval_prob054_edgedetect/prompt.txt) | Prob054_edgedetect |
| [verilogeval_prob055_conditional](verilogeval_prob055_conditional/prompt.txt) | Prob055_conditional |
| [verilogeval_prob056_ece241_2013_q7](verilogeval_prob056_ece241_2013_q7/prompt.txt) | Prob056_ece241_2013_q7 |
| [verilogeval_prob057_kmap2](verilogeval_prob057_kmap2/prompt.txt) | Prob057_kmap2 |
| [verilogeval_prob058_alwaysblock2](verilogeval_prob058_alwaysblock2/prompt.txt) | Prob058_alwaysblock2 |
| [verilogeval_prob059_wire4](verilogeval_prob059_wire4/prompt.txt) | Prob059_wire4 |
| [verilogeval_prob060_m2014_q4k](verilogeval_prob060_m2014_q4k/prompt.txt) | Prob060_m2014_q4k |
| [verilogeval_prob061_2014_q4a](verilogeval_prob061_2014_q4a/prompt.txt) | Prob061_2014_q4a |
| [verilogeval_prob062_bugs_mux2](verilogeval_prob062_bugs_mux2/prompt.txt) | Prob062_bugs_mux2 |
| [verilogeval_prob063_review2015_shiftcount](verilogeval_prob063_review2015_shiftcount/prompt.txt) | Prob063_review2015_shiftcount |
| [verilogeval_prob064_vector3](verilogeval_prob064_vector3/prompt.txt) | Prob064_vector3 |
| [verilogeval_prob065_7420](verilogeval_prob065_7420/prompt.txt) | Prob065_7420 |
| [verilogeval_prob066_edgecapture](verilogeval_prob066_edgecapture/prompt.txt) | Prob066_edgecapture |
| [verilogeval_prob067_countslow](verilogeval_prob067_countslow/prompt.txt) | Prob067_countslow |
| [verilogeval_prob068_countbcd](verilogeval_prob068_countbcd/prompt.txt) | Prob068_countbcd |
| [verilogeval_prob069_truthtable1](verilogeval_prob069_truthtable1/prompt.txt) | Prob069_truthtable1 |
| [verilogeval_prob070_ece241_2013_q2](verilogeval_prob070_ece241_2013_q2/prompt.txt) | Prob070_ece241_2013_q2 |
| [verilogeval_prob071_always_casez](verilogeval_prob071_always_casez/prompt.txt) | Prob071_always_casez |
| [verilogeval_prob072_thermostat](verilogeval_prob072_thermostat/prompt.txt) | Prob072_thermostat |
| [verilogeval_prob073_dff16e](verilogeval_prob073_dff16e/prompt.txt) | Prob073_dff16e |
| [verilogeval_prob074_ece241_2014_q4](verilogeval_prob074_ece241_2014_q4/prompt.txt) | Prob074_ece241_2014_q4 |
| [verilogeval_prob075_counter_2bc](verilogeval_prob075_counter_2bc/prompt.txt) | Prob075_counter_2bc |
| [verilogeval_prob076_always_case](verilogeval_prob076_always_case/prompt.txt) | Prob076_always_case |
| [verilogeval_prob077_wire_decl](verilogeval_prob077_wire_decl/prompt.txt) | Prob077_wire_decl |
| [verilogeval_prob078_dualedge](verilogeval_prob078_dualedge/prompt.txt) | Prob078_dualedge |
| [verilogeval_prob079_fsm3onehot](verilogeval_prob079_fsm3onehot/prompt.txt) | Prob079_fsm3onehot |
| [verilogeval_prob080_timer](verilogeval_prob080_timer/prompt.txt) | Prob080_timer |
| [verilogeval_prob081_7458](verilogeval_prob081_7458/prompt.txt) | Prob081_7458 |
| [verilogeval_prob082_lfsr32](verilogeval_prob082_lfsr32/prompt.txt) | Prob082_lfsr32 |
| [verilogeval_prob083_mt2015_q4b](verilogeval_prob083_mt2015_q4b/prompt.txt) | Prob083_mt2015_q4b |
| [verilogeval_prob084_ece241_2013_q12](verilogeval_prob084_ece241_2013_q12/prompt.txt) | Prob084_ece241_2013_q12 |
| [verilogeval_prob085_shift4](verilogeval_prob085_shift4/prompt.txt) | Prob085_shift4 |
| [verilogeval_prob086_lfsr5](verilogeval_prob086_lfsr5/prompt.txt) | Prob086_lfsr5 |
| [verilogeval_prob087_gates](verilogeval_prob087_gates/prompt.txt) | Prob087_gates |
| [verilogeval_prob088_ece241_2014_q5b](verilogeval_prob088_ece241_2014_q5b/prompt.txt) | Prob088_ece241_2014_q5b |
| [verilogeval_prob089_ece241_2014_q5a](verilogeval_prob089_ece241_2014_q5a/prompt.txt) | Prob089_ece241_2014_q5a |
| [verilogeval_prob090_circuit1](verilogeval_prob090_circuit1/prompt.txt) | Prob090_circuit1 |
| [verilogeval_prob091_2012_q2b](verilogeval_prob091_2012_q2b/prompt.txt) | Prob091_2012_q2b |
| [verilogeval_prob092_gatesv100](verilogeval_prob092_gatesv100/prompt.txt) | Prob092_gatesv100 |
| [verilogeval_prob093_ece241_2014_q3](verilogeval_prob093_ece241_2014_q3/prompt.txt) | Prob093_ece241_2014_q3 |
| [verilogeval_prob094_gatesv](verilogeval_prob094_gatesv/prompt.txt) | Prob094_gatesv |
| [verilogeval_prob095_review2015_fsmshift](verilogeval_prob095_review2015_fsmshift/prompt.txt) | Prob095_review2015_fsmshift |
| [verilogeval_prob096_review2015_fsmseq](verilogeval_prob096_review2015_fsmseq/prompt.txt) | Prob096_review2015_fsmseq |
| [verilogeval_prob097_mux9to1v](verilogeval_prob097_mux9to1v/prompt.txt) | Prob097_mux9to1v |
| [verilogeval_prob098_circuit7](verilogeval_prob098_circuit7/prompt.txt) | Prob098_circuit7 |
| [verilogeval_prob099_m2014_q6c](verilogeval_prob099_m2014_q6c/prompt.txt) | Prob099_m2014_q6c |
| [verilogeval_prob100_fsm3comb](verilogeval_prob100_fsm3comb/prompt.txt) | Prob100_fsm3comb |
| [verilogeval_prob101_circuit4](verilogeval_prob101_circuit4/prompt.txt) | Prob101_circuit4 |
| [verilogeval_prob102_circuit3](verilogeval_prob102_circuit3/prompt.txt) | Prob102_circuit3 |
| [verilogeval_prob103_circuit2](verilogeval_prob103_circuit2/prompt.txt) | Prob103_circuit2 |
| [verilogeval_prob104_mt2015_muxdff](verilogeval_prob104_mt2015_muxdff/prompt.txt) | Prob104_mt2015_muxdff |
| [verilogeval_prob105_rotate100](verilogeval_prob105_rotate100/prompt.txt) | Prob105_rotate100 |
| [verilogeval_prob106_always_nolatches](verilogeval_prob106_always_nolatches/prompt.txt) | Prob106_always_nolatches |
| [verilogeval_prob107_fsm1s](verilogeval_prob107_fsm1s/prompt.txt) | Prob107_fsm1s |
| [verilogeval_prob108_rule90](verilogeval_prob108_rule90/prompt.txt) | Prob108_rule90 |
| [verilogeval_prob109_fsm1](verilogeval_prob109_fsm1/prompt.txt) | Prob109_fsm1 |
| [verilogeval_prob110_fsm2](verilogeval_prob110_fsm2/prompt.txt) | Prob110_fsm2 |
| [verilogeval_prob111_fsm2s](verilogeval_prob111_fsm2s/prompt.txt) | Prob111_fsm2s |
| [verilogeval_prob112_always_case2](verilogeval_prob112_always_case2/prompt.txt) | Prob112_always_case2 |
| [verilogeval_prob113_2012_q1g](verilogeval_prob113_2012_q1g/prompt.txt) | Prob113_2012_q1g |
| [verilogeval_prob114_bugs_case](verilogeval_prob114_bugs_case/prompt.txt) | Prob114_bugs_case |
| [verilogeval_prob115_shift18](verilogeval_prob115_shift18/prompt.txt) | Prob115_shift18 |
| [verilogeval_prob116_m2014_q3](verilogeval_prob116_m2014_q3/prompt.txt) | Prob116_m2014_q3 |
| [verilogeval_prob117_circuit9](verilogeval_prob117_circuit9/prompt.txt) | Prob117_circuit9 |
| [verilogeval_prob118_history_shift](verilogeval_prob118_history_shift/prompt.txt) | Prob118_history_shift |
| [verilogeval_prob119_fsm3](verilogeval_prob119_fsm3/prompt.txt) | Prob119_fsm3 |
| [verilogeval_prob120_fsm3s](verilogeval_prob120_fsm3s/prompt.txt) | Prob120_fsm3s |
| [verilogeval_prob121_2014_q3bfsm](verilogeval_prob121_2014_q3bfsm/prompt.txt) | Prob121_2014_q3bfsm |
| [verilogeval_prob122_kmap4](verilogeval_prob122_kmap4/prompt.txt) | Prob122_kmap4 |
| [verilogeval_prob123_bugs_addsubz](verilogeval_prob123_bugs_addsubz/prompt.txt) | Prob123_bugs_addsubz |
| [verilogeval_prob124_rule110](verilogeval_prob124_rule110/prompt.txt) | Prob124_rule110 |
| [verilogeval_prob125_kmap3](verilogeval_prob125_kmap3/prompt.txt) | Prob125_kmap3 |
| [verilogeval_prob126_circuit6](verilogeval_prob126_circuit6/prompt.txt) | Prob126_circuit6 |
| [verilogeval_prob127_lemmings1](verilogeval_prob127_lemmings1/prompt.txt) | Prob127_lemmings1 |
| [verilogeval_prob128_fsm_ps2](verilogeval_prob128_fsm_ps2/prompt.txt) | Prob128_fsm_ps2 |
| [verilogeval_prob129_ece241_2013_q8](verilogeval_prob129_ece241_2013_q8/prompt.txt) | Prob129_ece241_2013_q8 |
| [verilogeval_prob130_circuit5](verilogeval_prob130_circuit5/prompt.txt) | Prob130_circuit5 |
| [verilogeval_prob131_mt2015_q4](verilogeval_prob131_mt2015_q4/prompt.txt) | Prob131_mt2015_q4 |
| [verilogeval_prob132_always_if2](verilogeval_prob132_always_if2/prompt.txt) | Prob132_always_if2 |
| [verilogeval_prob133_2014_q3fsm](verilogeval_prob133_2014_q3fsm/prompt.txt) | Prob133_2014_q3fsm |
| [verilogeval_prob134_2014_q3c](verilogeval_prob134_2014_q3c/prompt.txt) | Prob134_2014_q3c |
| [verilogeval_prob135_m2014_q6b](verilogeval_prob135_m2014_q6b/prompt.txt) | Prob135_m2014_q6b |
| [verilogeval_prob136_m2014_q6](verilogeval_prob136_m2014_q6/prompt.txt) | Prob136_m2014_q6 |
| [verilogeval_prob137_fsm_serial](verilogeval_prob137_fsm_serial/prompt.txt) | Prob137_fsm_serial |
| [verilogeval_prob138_2012_q2fsm](verilogeval_prob138_2012_q2fsm/prompt.txt) | Prob138_2012_q2fsm |
| [verilogeval_prob139_2013_q2bfsm](verilogeval_prob139_2013_q2bfsm/prompt.txt) | Prob139_2013_q2bfsm |
| [verilogeval_prob140_fsm_hdlc](verilogeval_prob140_fsm_hdlc/prompt.txt) | Prob140_fsm_hdlc |
| [verilogeval_prob141_count_clock](verilogeval_prob141_count_clock/prompt.txt) | Prob141_count_clock |
| [verilogeval_prob142_lemmings2](verilogeval_prob142_lemmings2/prompt.txt) | Prob142_lemmings2 |
| [verilogeval_prob143_fsm_onehot](verilogeval_prob143_fsm_onehot/prompt.txt) | Prob143_fsm_onehot |
| [verilogeval_prob144_conwaylife](verilogeval_prob144_conwaylife/prompt.txt) | Prob144_conwaylife |
| [verilogeval_prob145_circuit8](verilogeval_prob145_circuit8/prompt.txt) | Prob145_circuit8 |
| [verilogeval_prob146_fsm_serialdata](verilogeval_prob146_fsm_serialdata/prompt.txt) | Prob146_fsm_serialdata |
| [verilogeval_prob147_circuit10](verilogeval_prob147_circuit10/prompt.txt) | Prob147_circuit10 |
| [verilogeval_prob148_2013_q2afsm](verilogeval_prob148_2013_q2afsm/prompt.txt) | Prob148_2013_q2afsm |
| [verilogeval_prob149_ece241_2013_q4](verilogeval_prob149_ece241_2013_q4/prompt.txt) | Prob149_ece241_2013_q4 |
| [verilogeval_prob150_review2015_fsmonehot](verilogeval_prob150_review2015_fsmonehot/prompt.txt) | Prob150_review2015_fsmonehot |
| [verilogeval_prob151_review2015_fsm](verilogeval_prob151_review2015_fsm/prompt.txt) | Prob151_review2015_fsm |
| [verilogeval_prob152_lemmings3](verilogeval_prob152_lemmings3/prompt.txt) | Prob152_lemmings3 |
| [verilogeval_prob153_gshare](verilogeval_prob153_gshare/prompt.txt) | Prob153_gshare |
| [verilogeval_prob154_fsm_ps2data](verilogeval_prob154_fsm_ps2data/prompt.txt) | Prob154_fsm_ps2data |
| [verilogeval_prob155_lemmings4](verilogeval_prob155_lemmings4/prompt.txt) | Prob155_lemmings4 |
| [verilogeval_prob156_review2015_fancytimer](verilogeval_prob156_review2015_fancytimer/prompt.txt) | Prob156_review2015_fancytimer |

## 未导入题目

本次登记范围内没有未导入题目。
