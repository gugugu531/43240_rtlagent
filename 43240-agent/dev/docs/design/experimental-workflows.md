# 可选实验工作流

日期：2026-10-15。状态：本地实现，验收与 PR 准备中；没有模型性能增益结论。

## 与队长已有方案的关系

复用预算、模型、工具、日志和 solver-only（仅求解信息）检查点接口，保持选择策略独立。
方案 A 只是共用首次消息、采样和提取的参照，不是这三个 Workflow 的父流程。
不修改 `single_generate`、`repair_loop`、`evidence_repair` 或 E1/E2；默认入口仍为 `single_generate`。
无逐题难度自评、训练、官方测试台或判定反馈。

| Workflow | 策略 | 模型请求上限 |
| --- | --- | --- |
| `tool_feedback` | 一份首稿，自身接口/编译/综合诊断或受支持的输出驱动警告，最多一次修复 | 2 |
| `spec_test_repair` | 一份首稿，独立公共规格计划、自建测试台、可靠公开属性反例，最多一次修复 | 3 |
| `behavior_divergence` | 两份独立初始候选、同一计划/激励、记录分歧；有独立依据时最多一次修复 | 4 |

公开完整真值表用程序枚举，不调用模型；请求错误不重试，已经开始的失败请求仍记账。
调用计数包括重放首稿；时间、token 与请求数分别限制和记录，不把额度耗尽伪装成超时。
双候选的行为分歧只记录，不凭分歧、两稿一致、投票或模型自述推断哪份正确。

## 首稿与检查点

三个入口首次都使用方案 A 的 `rtl_generate(prompt_style='repair', use_skills=False)` 和 `rtl_extract`，
默认 8192 tokens、temperature=0、top_p=1；实际请求超时同时受模型服务和整题剩余时间约束。
第二候选 temperature=0.4、top_p=1，只看公共题面，不看第一稿；修复 temperature=0、top_p=1。
计划节点沿用 temperature=0、top_p=1，且只看公共题面与接口。

这些首稿不是官方 baseline 的消息和提取规则，不能写成与 `single_generate` 请求等价。
后续配对实验应以共享首稿为无修复对照，并把官方 baseline 作为另外一项报告。
三份 quick 配置分别直接运行，只保证首次请求条件一致，不保证模型恰好返回同一份代码。
真正的共用首稿对照必须给各组配置同一个 `runtime.initial_state`，且模型服务、代码和工具身份一致。

直接启动时先持久保存首稿，再做接口/编译，保存 `initial.json`，随后才计划、第二候选或修复。
可用 `runtime.initial_state` 或构造参数 `initial_state` 重放；沿用既有身份和完整性检查，不读取评分目录。
本批额外要求仅一个初始请求、相同首稿采样与实际输出上限，检查记录只能有接口、编译和综合。
实际输出上限按当前 token 策略在首次调用前的额度计算，允许预算降低配置上限；计算时不重复扣除导入成本。
实际采样上限发生变化时仍拒绝重放。
导入的首稿时间和 token 仍扣账。检查点里 `synth_passed` 不让规格组提前跳过自己的功能阶段。
重放结果不是零成本运行，也不能直接当成连续部署延迟；批量统计工具属于后续阶段。

## 功能检查和替换规则

接口后做编译；规格组只有编译通过才生成计划、运行自测，自测通过才进入综合。
编译失败修复成功后，即使修复次数已经用完，也会尝试计划和功能自测。
计划不可用时停止、标记功能未验证，不用综合冒充功能检查。
编译修复稿可作为更强的编译证据回退，但不声称其功能正确。

新候选完成所需验证前不参与替换：自测前截止、自测失败未知、综合超时/环境失败，均不能提前顶掉已保存旧稿。
模型期望值只是模型假设，不能单独触发功能修复。
确定的公共属性反例才可进入规格修复；反馈保留首次属性失配及必要输入历史。
替换沿用第三批同计划、同属性集合、严格减少失败、保住全部旧通过属性、工具通过证据、完整端口和复位探针区分度的保护。
本批不放松计划校验、不扩大时序或端口支持范围；未知 X/Z 和 TB 故障不作 DUT 错误。

工具组的输出驱动警告修复仍要求完整新旧综合证据、端口语义相同和无驱动集合严格减少。
规格组不为纯警告另开替换通道；已编译、已自测通过但仅有综合代码错误的情况，也不会绕过属性严格改进条件强行修复替换。
这些情况保留旧稿并标明未完成；工具组可另行试验它们，不承诺每次修好。
基础选择函数会排除代码失败稿，本批在工作流层额外保护已有 lint 通过的旧稿，避免综合失败导致它退出比较后绕过保护。

## 显式启动

开发配置均使用假模型，不配置商业服务或官方评分：

```bash
cd 43240-agent
python3 dev/tools/run.py --config dev/configs/workflow-tool-quick.yaml
python3 dev/tools/run.py --config dev/configs/workflow-spec-quick.yaml
python3 dev/tools/run.py --config dev/configs/workflow-divergence-quick.yaml
```

假模型可能返回不合格计划，工具未安装时也会回退；入口跑完不代表功能通过。
正式试验前应显式配置模型、服务版本和题集，不把商业强模型或小例子结果当作 Qwen3-8B 部署收益。
已存在 `LLM_*` 或 `AGENT_*` 环境变量时须检查有效配置，避免覆盖 YAML 的假模型设置。

回归命令：

```bash
python3 -m unittest discover -s dev/tests -p 'test_experimental_workflows.py' -v
RUN_VIVADO_TESTS=1 python3 -m unittest discover -s dev/tests -p 'test_experimental_vivado.py' -v
python3 -m unittest discover -s dev/tests -p 'test_*.py' -v
python3 dev/tools/submission.py
```

真实工具测试沿用正式工具配置解析，支持从 `PATH` 查找 Vivado，也可设置 `VIVADO_BIN`；
使用人工构造电路、固定假模型和自己的测试台。
验证记录另存开发笔记，不在本文预填通过数，不宣称正式题集收益。
