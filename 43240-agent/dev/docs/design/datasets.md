# 开发题集转换与均衡筛选

类型：开发工具说明。状态：已实现并完成全池验证，见[验收记录](../notes/2026-10-14-balanced-datasets-validation.md)
和[筛选统计](../notes/2026-10-14-balanced-datasets-selection.md)。日期：2026-10-14。

## 目的与边界

将公开RTL生成题整理为现有六文件契约，再从原有题目和新增题目中选择题型与难度覆盖更均匀的子集。
当前完整池258题，质量验证及去重后可用241题，默认均衡集60题。基础、进阶、复杂各20题。
完整题库位于仓库根目录 `tasks/pool/`，均衡子集位于 `tasks/balanced/`。
来源清单、许可证、适配源码和上游下载仍位于 `43240-agent/dev/datasets/`，验证日志仍位于开发区。
本次按用户要求将两个题库目录从开发区迁入 `tasks/`，逐题内容指纹保持一致，已有验证结果继续有效。
`tasks/`下原有的159道题、主办方判定代码及两个baseline保持不变。
题库不随参赛方案打包；求解器仍只读取题面，不新增 `interface.txt`。

每题包含 `prompt.txt`、`top.txt`、`task.json`、`ref.sv`、`tb.sv`、`reference/solution.sv`。
顶层统一为 `TopModule`、`RefModule` 和 `tb`。测试台输出 `Mismatches: <n> in <m> samples`。
统一池的目录名全部小写；原题号保存在来源记录中。

## 来源与转换方式

| 来源 | 固定版本 | 处理 |
| --- | --- | --- |
| [ChipBench](https://github.com/zhongkaiyu/ChipBench) | `b4ba3a06759804ec88c26c3cf15b28b9a90b3443` | 45道RTL生成题；补全参考侧宏和题面公开子模块、隔离参考侧模块名称、统一统计出口 |
| [RTLLM](https://github.com/hkust-zhiyao/RTLLM) | `51ed553d0ffd32797a1a0a13e051656bf302c81f` | 50道；保留断言和激励，外部向量按原值嵌入，统一名称和结束判定 |
| [ArchXBench](https://github.com/sureshpurini/ArchXBench) | `0db0d0de25aad5238393d51bd97ce952e579fa1a` | 登记71道；定点平方根、4×4脉动阵列矩阵乘法和AES流水线提供本地独立参考，其他68道记录未转换原因 |
| [CVDP公开样例](https://github.com/NVlabs/cvdp_benchmark) | `8e894cf74414ab1eaea1e2b4e80a02f123df07b6` | 检查5道带答案样例；转换1道RTL生成题，另外4道属于补丁、测试台生成或文字解释任务 |
| 当前 `tasks/` | 每文件SHA-256 | 156道VerilogEval和3道示例全部复制到统一池，原文件不修改 |

许可证与NOTICE保存在 `dev/datasets/licenses/`。来源URL、提交版本和逐文件SHA-256保存在
`conversion.json`。上游仓库、转换后的大量文件及运行日志只留在本地；工具、许可证、清单和适配源码进入Git。

ArchXBench上游没有完整RTL参考答案。此次补充的三个答案明确标记为本地独立实现，不能当作上游参考答案。
平方根沿用上游50组输入与数学比较；矩阵乘法采用Python整数运算生成8组向量，覆盖上游两组、负数和边界；
AES采用上游Python模型生成64组向量，并检查逐拍吞吐、输入空拍、密钥变化和复位。
后两题替换了原文件式测试台，所得分数不能与原始ArchXBench直接比较。

CVDP只转换官方公开样例中的Galois LFSR（伽罗瓦结构的线性反馈移位寄存器），保留其参考RTL，
将Cocotb测试改为SystemVerilog，并扩展到全部255个非零种子。它不是完整CVDP题集。
完整CVDP公开发布不含全部参考答案，且使用另一套工程及验证契约，本次不声称已经整体移植。

RTLLM中的一个sample表示一次完整上游测试台的判定，不能与VerilogEval逐拍sample数量比较。
若测试台提前结束、没有到达明确判定出口或超时，不得计为通过。

## 质量门槛

`validate_datasets.py`按题调用未修改的 `selftest/run_selftest.sh --reference`，验证L1编译、L2仿真、L3综合。
随后调用官方 `veval-judge` 到L2，检查两种接口相同但输出分别恒零、恒未知值的候选。
编译失败不算成功检出功能错误。只有通过参考L3、两种负例均在仿真中被拒绝的题才进入候选清单。
原有两道明确要求输出恒零的题对恒零负例豁免，但仍要求未知值负例被拒绝。
再剔除去注释、去空白后参考代码完全相同的重复题。这只是保守文本去重，不代表证明了所有功能等价关系。

所有结果绑定题目内容指纹；题目变更后旧验证不得用于入选。
编译或综合失败、参考答案失配、测试覆盖不足、缺少验证和工具环境错误分别记录。
两种负例只是最低质量检查，不能证明测试台完备，也不能证明参考答案满足题面的每个约束。
例如参数化题可能只验证默认参数，相关限制保存在逐题适配记录中。
参考答案未通过的题可能没有执行负例；清单中的`mutant_not_rejected`也包含这种未验证情况，
不能把这些条目都解释为测试台已经接受错误答案。

## 题型与难度

题型分为组合逻辑、算术、寄存器与移位、计数与定时、状态机与协议、存储器与队列、
跨时钟域与数据接口、处理器部件、并行计算与信号处理、密码运算。
波形推导、改错、参数化、层次结构等作为附加标签，不与主考点混为一类。

难度依据题面估计，**不是模型实测通过率**：

- 基础：单一组合操作、基本寄存器、计数或小位宽算术。
- 进阶：多个条件、标志、优先级或状态与数据配合。
- 复杂：多周期算法、较复杂流水线、跨时钟域队列、协议与数据路径组合、系统加速器。

ChipBench与RTLLM按逐题主考点登记；VerilogEval使用题面规则和明确的复杂题列表。
所有标签及理由保存在 `catalog.json`。需要修订时可在 `dev/datasets/labels.json` 给出逐题覆盖，
不要手改自动生成的目录清单。

筛选默认目标60题，使用最小费用流，同时减小题型与难度计数的平方和。
难度平衡权重高于题型；同一题型与难度组合内轮换数据集，再用固定哈希打破并列。
这使结果可重复，并减少低题号和单一来源偏差。可用题不足的组合不补造题、不重复抽题，缺口列在 `selection.json`。
完整候选池和未入选原因始终保留，不用删除题目实现均衡。

## 复现与使用

在 `43240-agent/` 下操作。将表中四个上游仓库分别放到
`dev/datasets/upstream/{chipbench,rtllm,archxbench,cvdp}`，检出表中完整提交号。
转换器会拒绝其他版本。输出目录必须不存在或为空，避免覆盖已有题目。
以下命令默认转换到`../tasks/pool/`，验证和筛选均读取该目录，`--materialize`复制到`../tasks/balanced/`。

```bash
python3 dev/tools/datasets.py convert
python3 dev/tools/validate_datasets.py --jobs 4
python3 dev/tools/balance_datasets.py --size 60 --materialize
```

验证需要可正常工作的Vivado，所有结果放在 `dev/runs/dataset-validation/full/`。
已完成且题目指纹相同的结果可以复用；`--rerun`强制复验。`--prefix`支持按题名前缀选择。
长时间本机验证时应阻止休眠；不需要启动GPU实例或调用模型。

仓库根目录的`tasks/pool/`是全部已转换题目，`tasks/balanced/`是入选题的实际文件副本，不依赖符号链接。
现有运行器可将 `experiment.tasks.root` 指向其中任一目录；筛选清单为 `dev/configs/balanced.txt`。
`task.json`和其他判定文件只供开发侧官方判定使用，不得注入模型提示或修复上下文。
题面保留来源的表达方式，RTLLM及ArchXBench不一定采用VerilogEval的端口项目列表；
目录契约与评测接口相同，不表示题面被改写为相同文风。

```bash
# 验证均衡集的参考答案，沿用官方入口
../selftest/run_selftest.sh --reference --tasks ../tasks/balanced \
  --out dev/runs/balanced-reference

# 单元测试只检查转换与筛选契约
python3 -m unittest discover -s dev/tests -p test_datasets.py -v

# 使用现有实验入口；默认是假模型，只检查流程
LLM_BACKEND=mock python3 dev/tools/run.py --config dev/configs/balanced.yaml \
  --task chipbench_self_contain_prob000_four-to-one_multiplexer --tag balanced-smoke

# 配好LLM_MODEL、LLM_BASE_URL及对应凭据后，运行60题真实测评
LLM_BACKEND=openai python3 dev/tools/run.py --config dev/configs/balanced.yaml \
  --metrics runtime model judge --tag balanced-evaluation
```

`balanced.yaml`读取`tasks/pool/`和`balanced.txt`清单，因此不要求复制后的`tasks/balanced/`存在。
想更改题量可重新运行筛选器，例如`--size 90`；原始池和质量验证记录可复用。
`--report`可以把自动统计写入`dev/docs/`，现有目录非空时去掉`--materialize`即可仅更新清单和统计。

不同测试集的题型、测试覆盖和改编程度不同，实验报告应同时给出来源分项结果，
不要把这个混合题集的通过率写成VerilogEval、RTLLM、ArchXBench或CVDP的官方成绩。
