# 技能包

本目录保存可复用的 RTL（寄存器传输级）设计与检查方法，每项方法称为一个技能（Skill）。运行机制见[技能与知识检索](../docs/knowledge.md)，运行入口见[方案 README](../README.md)。

## 添加技能

新增 `skill/<id>/skill.md`，无需改 Python、YAML 配置或知识清单：

```markdown
---
name: rtl-example-method
description: Describe when this method helps with RTL generation or repair.
---

# Method

Describe applicability, inputs, steps, verification and limitations here.
```

目录名必须与 `name` 相同，名称使用小写英文字母开头，后接小写字母、数字或连字符。`description` 和正文不能为空。新增文件使用小写 `skill.md`；为读取已有技能，也支持目录内只有 `SKILL.md` 的情况。两者同时存在时只加载小写文件，不能在小写文件非法时回退到大写原文。

程序只扫描 `skill/` 的直接子目录，忽略根目录说明和没有技能文件的目录，不递归读取任意文档，也不执行技能附带的脚本。拒绝符号链接、重复字段、未知元数据字段、名称不符和超过 32 KiB 的技能文件。扫描时不限制技能总数为 32 项；每次请求仍最多选择两个完整技能，避免一次发送过多正文。

可选 YAML 文件头元数据（frontmatter）：

```yaml
phases: [generate, repair]
conflict_group: alternative-methods
review_status: frozen_default_fixed
```

- `phases` 默认 `[generate, repair]`，可以仅声明某一阶段。
- `conflict_group` 默认不设；相同组的技能不能同时使用。
- `review_status` 默认 `frozen_default_fixed`，表示允许自动选择，不代表已证明有效。`frozen_candidate_not_default` 禁止自动选择但允许显式选择；`frozen_rejected_fixed_ab` 不允许选择。

## 工作流如何选择技能

- `guided_verify` 每题首次使用时扫描技能目录并建立快照，把允许自动选择的名称与描述提供给规划器。模型最多选择两个，程序按阶段、状态和冲突组校验后，将正文加入首稿生成或修复请求。`retrieval_mode=off` 只关闭 RAG（检索增强生成）的知识卡片检索，不关闭技能选择。
- 通用生成节点 `rtl_generate` 默认自动扫描，通过 BM25（基于词项匹配的相关性排序算法）按题面与公开接口检索技能描述，再检查是否允许使用；至少匹配两个不同词项才会入选。可显式使用 `skill_ids` 或 `skill_mode: off/shadow/on`；三个模式分别表示关闭、只记录选择、实际加入请求。已有显式关闭技能的 RAG 配置仍保持关闭。
- `single_generate` 的默认基线节点不加载技能；上述自动选择适用于 `guided_verify` 和使用 `rtl_generate` 的工作流。
- 每题使用固定技能快照；新文件或修改在下一题生效，不改变正在处理的题目。程序记录本次内容的 SHA-256 校验值，不需人工更新哈希或版本。
- 自动发现不等于每题必用；模型或相关性检索可以不选。非法技能会明确报错，不静默忽略。

技能只提供方法，不覆盖公开题面、接口或真实工具证据。新增求解技能不会进入独立检查器；检查器构造节点继续只读取固定的 `rtl-behavior-check-keycases` 方法，不读取候选 RTL。不得写入参考答案、官方测试台、判定反馈或题目身份与答案的对应关系。

## 现有技能与来源

以下七个专项技能的文本由本项目编写，描述的是通用 RTL 设计方法。它们允许自动选择，可用于生成和修复；这不代表通用方法由本项目首创，也不代表已验证真实模型收益。技能正文沿用英文运行格式，按公开题意选择，不按题号、平台或参考答案匹配：

| 技能 | 适用问题与重点 | 不覆盖的范围 |
| --- | --- | --- |
| [rtl-counter-terminal-events](rtl-counter-terminal-events/skill.md) | 计数终点、周期首末拍、同拍级联进位 | 不把计数使能当作新时钟 |
| [rtl-lfsr-topology](rtl-lfsr-topology/skill.md) | 线性反馈移位寄存器的反馈拓扑、抽头编号与逐位映射 | 不由多项式名称猜抽头或最大周期 |
| [rtl-stream-word-boundaries](rtl-stream-word-boundaries/skill.md) | 串并转换、数据分组、非整数倍位宽转换 | 不假设未声明的握手或中断行为 |
| [rtl-memory-accepted-transactions](rtl-memory-accepted-transactions/skill.md) | 单时钟 FIFO（先进先出队列）的有效操作、RAM（随机存取存储器）冲突与读延迟 | 不覆盖异步 FIFO 的跨时钟实现 |
| [rtl-pipeline-transaction-alignment](rtl-pipeline-transaction-alignment/skill.md) | 流水线数据、部分结果、有效位和控制信号对齐 | 不新增原接口没有的 ready/valid 协议 |
| [rtl-packed-index-neighborhood](rtl-packed-index-neighborhood/skill.md) | 打包向量切片、网格邻居、边界及同步更新 | 不把非法索引截断或猜成零 |
| [rtl-kmap-coordinate-mapping](rtl-kmap-coordinate-mapping/skill.md) | 卡诺图坐标、最小项编号、有效输入域与等价核验 | 不替代通用组合完整性技能 |

这些方法细化常见解题步骤；已有通用时序技能仍可用于寄存器、移位与计数。自动选择仍最多两项，新增专项技能可能改变描述检索或规划器的选择；应查看实际发送记录，不能从目录存在推断已经使用。题目分类、来源链接和选题分析只保存在工作区开发资料，不随技能包提交。

原有时序技能保留自动选择状态；v3 时序技能和关键场景检查技能保留候选状态；位宽、组合完整性、FSM（有限状态机）技能保留禁用状态。接口技能 `rtl-module-interface-contract/SKILL.md` 由目录扫描机制加载。状态由各技能文件的文件头元数据声明，不再使用 `knowledge/catalog.json`。关键场景技能不参与求解技能的自动选择，但检查器构造节点固定读取它。

时序、时序 v3、位宽、组合完整性和 FSM 技能从 [amd-rtlagent-prompt-engineering 固定分支](https://github.com/wyc888-crypto/amd-rtlagent-prompt-engineering/tree/fb1c2803e5db0f32b59b9ba9100877f2a0d26412) 迁入，保留文件中的版权与 MIT 许可证声明。接口技能来自主办方示例，保留 AMD 版权与 MIT 许可。`rtl-behavior-check-keycases` 的文本由本项目编写，见[来源说明](rtl-behavior-check-keycases/PROVENANCE.md)。这些来源记录和使用状态均不构成当前模型效果证明。
