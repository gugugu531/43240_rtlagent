# 公开题集整理与均衡筛选验收

类型：验收记录。状态：本次整理与筛选已完成。日期：2026-10-14。

后续目录迁移：按用户要求，完整池和均衡子集已分别移到仓库根目录`tasks/pool/`与`tasks/balanced/`，
逐题内容指纹保持一致。下文保留迁移前的验收路径和历史命令；当前用法见[题集说明](../design/datasets.md)。

## 交付范围

完整候选池在`dev/datasets/pool/`，共258题：原有156道VerilogEval、3道示例、45道ChipBench、
50道RTLLM、3道ArchXBench本地改编题和1道CVDP公开样例。每题保持现有六文件目录契约。
质量验证及保守文本去重后有241道合格候选，从中选出60题，实际副本在`dev/datasets/balanced/`。

并非所有调研题目都已转换：ArchXBench其余68题没有现成完整RTL参考答案，且部分需要外部判定；
CVDP其余4道带答案样例要求工程补丁、测试台或文字解释，不能直接当作RTL模块生成题。
这些题的来源和未转换原因保存在`dev/datasets/conversion.json`。完整CVDP及RealBench没有整体移植。
ArchXBench的三个参考实现由本地独立编写，CVDP仅代表官方公开样例；不能据此宣称完整上游成绩。

固定上游版本、许可证、转换方式与复现命令见[题集说明](../design/datasets.md)。
逐题标签、验证结果和排除原因在`dev/datasets/catalog.json`。这些文件以及参考答案均位于开发区，
主办方原始题目、判定代码、两个baseline及正式求解代码保持不变。

## 验证证据

本地验证目录为`dev/runs/dataset-validation/full/`，每题有独立的`validation.json`、
参考答案判定结果和负例记录。全池汇总为同目录的`summary.json`。
最终完整性核对结果为`dev/runs/dataset-validation/audit.json`。

- 258题全部通过目录、模块名、元数据及外部文件依赖检查。
- 258题全部经过未修改的官方参考答案链路，250题达到L3（编译、仿真、综合通过），
  2题停在L2、5题停在L1、1题停在L0；没有工具环境错误被当作有效题目结果。
- 对通过参考仿真的题目检查恒零和未知值输出负例；编译失败不算功能错误被检出。
  明确要求恒零的两道原题免除恒零负例要求。
- 从完整池排除8道参考答案未达L3的题、8道测试台未检出错误输出的题和1道文本重复题，得到241题。
- 60道入选题全部具有与当前题目内容一致的验证指纹；副本与完整池逐字节一致。
- 倒置候选输入顺序后，筛选结果保持一致。配置解析得到的60道任务与筛选清单完全一致。
- 11项开发工具测试通过；提交文件检查没有错误，提交清单不包含题库和参考答案。

Vivado验证必须在能正常运行xsim的本机环境中进行。本次发现沙箱内xsim出现Tcl异常，
正式验证改为沙箱外执行；该环境故障没有作为题目失败写入最终有效记录。
中断后根据题目内容指纹复用已完成结果，最后对258题统一核对，并非只检查入选的60题。

## 排除实例

ChipBench的最小公倍数题参考答案与测试台存在389/399个采样差异；RTLLM的`clkgenerator`
也未通过参考仿真。这些结果只证明当前版本在本地链路中不一致，没有通过削弱测试来强行纳入。

RTLLM的`float_multi`存在混合电平与边沿敏感事件，`synchronizer`存在Vivado不能明确识别的时钟事件，
均在综合阶段失败。`comparator_3bit`、`comparator_4bit`、两道定点加减法、`sequence_detector`、
`edge_detect`和`square_wave`的测试台至少接受一种明显错误输出，因此不入选。

原有VerilogEval的Prob082、Prob141、Prob156在官方仿真链路中超时，Prob099存在接口不匹配。
Prob053接受恒零输出；Prob008与Prob007的参考代码去掉注释和空白后相同，保留一题。
所有被排除的题仍留在完整池，便于之后修复或另行评估。

## 均衡效果与限制

完整池的基础、进阶、复杂题分别为100、121、37道；均衡集变为各20道。
十类题型全部覆盖，其中算术8题，组合逻辑、寄存器与移位、计数、状态机、存储、接口和处理器部件各7题，
信号处理2题、密码运算1题。此次也覆盖了合格候选中全部23种已有的题型与难度组合。
详细来源分项和缺口见[自动筛选统计](2026-10-14-balanced-datasets-selection.md)。

难度是依据题面和结构作出的估计，没有执行真实模型测评；后续可以用相同预算下的模型通过率重新校准。
两种负例只是测试质量的最低门槛，不能证明测试台完备。信号处理与密码运算题量仍少，
参数化题也可能仅覆盖默认配置。这些限制在来源和逐题适配说明中保留。

## 使用入口与流程检查

在`43240-agent/`下，`dev/configs/balanced.yaml`读取`pool/`和`balanced.txt`清单。
默认使用假模型；切换真实模型并加入`judge`指标的方法见[题集说明](../design/datasets.md)。
调整题量使用筛选器的`--size`，不需要重复整理上游数据。

本次假模型运行编号：`20261014-114435-balanced-smoke-7cc6da00`。
它通过现有实验入口完成了一道新增ChipBench题的读取、生成、记录和输出，产出非空`solution.v`。
该检查仅证明流程兼容，不代表假模型功能正确，也不是模型能力测评。

```bash
LLM_BACKEND=mock python3 dev/tools/run.py --config dev/configs/balanced.yaml \
  --task chipbench_self_contain_prob000_four-to-one_multiplexer \
  --metrics runtime model --tag balanced-smoke
python3 -m unittest discover -s dev/tests -p test_datasets.py -v
python3 dev/tools/submission.py
```

均衡集和完整池是本地交付目录；Git保存转换与筛选工具、来源清单、标签和验证摘要、许可证、
独立适配源码、配置与文档。上游仓库、展开题目和原始运行日志不提交；换机器按题集说明复现。
