# Agent 上下文、诊断与候选策略接口

日期：2026-10-14。状态：已实现；本文记录运行契约和验证边界。

## 上下文与 token

ContextAssembler 保留题面、接口、完整候选及原始反馈，可选资料按完整片段加入。
上下文记录包括消息哈希、资料来源、保留或省略原因和本地模板 token 计数。
LocalTokenCounter 仅从本地 tokenizer.json 与 tokenizer_config.json 加载数据，
用受限 Jinja 模板编码文字消息；不下载权重或执行模型仓库代码。

services.model 可配置 tokenizer_dir、tokenizer_sha256、template_sha256、context_limit、
strict_context、enable_thinking、token_total_limit 和 token_output_limit。
累计输入+输出、累计输出、上下文窗口和单次输出上限分别处理；默认不启用累计限额。
显式严格限额先预留实际可用输出，再装配资料；缺失 token 用量时保留预留额度，计数失配后停止严格模式新调用。
未知用量不算零。限制约束客户端请求，服务在请求失败后的实际计算成本不能由客户端账本完全确定。

enable_thinking 在普通生成和修复请求中同时用于 chat_template_kwargs 与本地模板计数。
默认 single_generate 使用 baseline_rtl，为保持官方请求一致，不注入此选项，也不把配置的选项用于计数；
按实际请求未指定选项的情况使用模板默认值，并记录 template_options_ignored。
因此此配置不能控制默认流程服务端的思考模式；其他流程的显式请求选项优先于服务配置。

## 自身工具诊断与短卡（简短修复资料）

Diagnostic 保留严重程度、完整错误码、实际工具与版本、原报告位置和可核实的候选行号。
只有当前 solution.sv/v 中有效行号才映射到候选；环境错误、未知错误和 warning 不改成代码错误。
版本查询使用有时限的受管理进程与独立临时目录。明确的 VRFC 10-1219 位选方向错误进入代码归因。

知识库由本地单独提供，内容不随 Git 上传。services.knowledge.corpus_path 默认 null，
显式配置时相对路径按 YAML 文件所在目录解析；没有配置、文件无法读取或格式校验失败时记录原因并保留原修复提示。
格式校验包括根对象、来源对象、卡片对象及字段类型；[]、null 和错误的卡片字段均记为 corpus_unavailable，继续原修复流程。
检索要求完整错误码、工具和版本匹配；卡片可用 message_contains_any 指定诊断文本条件，
只能由同一错误、工具及版本的 ERROR 满足，不能用其他错误或 warning 代替。
最多两张，并按字符和实际上下文额度整卡省略；候选数量上限造成的省略也记录。
记录命中、来源、哈希和省略；无命中不增加提示。语法修复卡不能证明功能正确。
新增卡片须保留来源、适用条件、验证记录指纹与限制；赛事参考答案和测试台不得进入资料或提示。

## 可选 Workflow

E1 是结构化修复与资料检索对照，E2 是修复次数与候选数量对照。短卡包含简短建议、适用条件与独立验证记录。

| Workflow | 行为 |
| --- | --- |
| evidence_a0 | 方案 A 同一首次提示与提取，自身检查后保存初始检查点，不修复 |
| evidence_a1 | 明确代码或提取失败后，最多一次结构化修复 |
| evidence_a2 | evidence_a1 加符合自身错误证据的短卡 |
| search_initial | 保存候选策略共用的首次候选和自身检查 |
| search_r1 / search_r2 | 最多一次 / 两次修复，通过自身检查即停止 |
| search_r2_guided | search_r2 加外置修复卡，按每轮最新自身错误检索；未配置时请求与 search_r2 一致 |
| search_c2 / search_c3 | 最多两份 / 三份独立候选，按自身检查证据选择 |

search_* 的 temperature、top_p、base_seed 在 Python Workflow 构造时声明；
默认 0.6、0.95 和 20261013，逐次 seed（随机种子）为 base_seed、base_seed+1、base_seed+2。
模型请求直接带这些字段。其他服务默认采样参数不由 Agent 推断，历史实验成绩不作为这些默认值的收益证明。
single_generate、evidence_repair 及 baseline 的默认参数保持原约定，默认 Workflow 未切换。

候选选择不读取官方判定。自身检查证据相同时保留早期候选；提取、工具或模型失败保留已有答案。
修复处理最新候选及其自身错误；独立生成只读原题面和接口。仅 search_* 的反馈统一临时工具路径，
原始工具日志仍完整保留。

## 检查点与停止点

runtime.initial_state 可指定 initial.json。加载时校验输入、源码、模型服务与工具身份，
拒绝未支持字段，恢复自身候选/检查并扣除首次阶段实际耗时和 token 成本，不读取整个判定目录。
缺失或未完成的初始请求不能伪装成已完成请求。

工具重放身份与单次运行中的检查缓存身份分别处理。重放身份包含工具真实路径及文件信息、ToolConfig，
以及库、编译器、Tcl/Python、许可证、语言和线程等相关环境；不包含 AGENT_WORKFLOW、输出位置等 Agent 调度变量。
切换 Workflow 可以重放，工具文件、器件配置或许可证环境变化仍拒绝重放；缓存继续保留更严格的环境校验。

search_r2/search_r2_guided/search_c3 支持直接启动及从 initial_state 重放。
直接启动时，首个请求和提取完成后保存本次 initial.json；首个请求失败、未形成检查点时不生成停止点。
在第三次调用前或提前停止时保存 stop_after_two.json，记录当时的答案、候选清单、账本与实际计时，
提前通过时如实记录只有一次调用。保存时使用已验证的初始信息，不重新读取外部检查点。
这是共享的前两次调用过程对应的停止点视图，不额外调用模型，也不伪造独立执行日志。
共享成本不能重复相加作为实际总成本；直接启动的初始耗时从 branch_wall_s 中扣除，重放耗时不能当连续部署性能。

## 本地验收

组件测试覆盖默认消息兼容、整片段省略、严格额度、未知 token 用量、计数失配、诊断归因、
短卡命中/回退、共享起点、第二次修复、独立候选、停止点、调用上限与失败保留。
dev/tools/validate_repair_cards.py 用独立的错误、修正和控制例验证修复原则；
dev/tools/validate_select_direction.py 验证位选错误归因。这些小例子不是赛事题目的参考答案。
提交包检查继续验证没有 dev 时默认入口可运行；工具和功能检查的通过不等同于完整题集收益。

本次审查修复的运行编号、提交、命令与本地证据位置见
[PR #33 审查修复验收记录](../notes/2026-10-14-pr33-review-validation.md)。
