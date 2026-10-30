# 技能包

本目录保存可复用的 RTL 方法。运行机制见 [Skill 与知识检索](../docs/knowledge.md)。方案根 README 保持为空。

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

程序只扫描 `skill/` 的直接子目录，忽略根目录说明和没有技能文件的目录，不递归读取任意文档，也不执行技能附带的脚本。拒绝符号链接、重复字段、未知元数据字段、名称不符和超过 32 KiB 的技能文件。发现阶段无 32 个技能的数量上限；每次请求仍最多选择两个完整技能，避免无差别堆积正文。

可选 frontmatter：

```yaml
phases: [generate, repair]
conflict_group: alternative-methods
review_status: frozen_default_fixed
```

- `phases` 默认 `[generate, repair]`，可以仅声明某一阶段。
- `conflict_group` 默认不设；相同组的技能不能同时使用。
- `review_status` 默认 `frozen_default_fixed`，表示允许自动选择，不代表已证明有效。`frozen_candidate_not_default` 禁止自动选择但允许显式选择；`frozen_rejected_fixed_ab` 不允许选择。

## 自动进入工作流

- `guided_verify` 每题首次使用时发现技能并建立快照，把允许自动选择的名称与描述提供给规划器。模型最多选择两个，宿主按阶段、状态和冲突组校验后注入首稿或修复。`retrieval_mode=off` 只关闭 RAG 卡片，不关闭 Skill。
- 通用 `rtl_generate` 默认自动发现，通过 BM25（基于词项匹配的相关性排序）按题面与公开接口检索技能描述，再做相同准入检查；至少匹配两个不同词项才会入选。可显式使用 `skill_ids` 或 `skill_mode: off/shadow/on`；shadow 只记录、不注入。已有显式关闭技能的 RAG 配置仍保持关闭。
- 默认 `single_generate` 使用 baseline 节点，不加载技能，保持基线对齐；上述自动行为适用于 guided 和使用 `rtl_generate` 的工作流。
- 每题使用固定技能快照；新文件或修改在下一题生效，不改变在途题目。记录本次内容 SHA256，不需人工更新哈希或版本。
- 自动发现不等于每题必用；模型或相关性检索可以不选。非法技能会明确报错，不静默忽略。

技能只提供方法，不覆盖公开题面、接口或真实工具证据。任意新求解技能不会进入独立检查器；checker 继续只读取固定的 `rtl-behavior-check-keycases` 方法，不读取候选 RTL。不得写入参考答案、官方测试台、判定反馈或任务身份映射。

## 现有技能与来源

原有时序技能保留自动准入；v3 时序技能和关键 case 技能保留候选状态；位宽、组合完整性、FSM 技能保留原有拒绝状态。`rtl-module-interface-contract/SKILL.md` 现由目录发现机制加载。状态由各运行文件 frontmatter 声明，不再使用 `knowledge/catalog.json`。

时序、位宽、组合和 FSM 方法来自 [MIT 上游分支](https://github.com/wyc888-crypto/amd-rtlagent-prompt-engineering/tree/fb1c2803e5db0f32b59b9ba9100877f2a0d26412)，原文及版权说明保留在各目录。`rtl-behavior-check-keycases` 是团队原创，其来源说明见 [PROVENANCE.md](rtl-behavior-check-keycases/PROVENANCE.md)。历史来源与准入状态不构成当前模型效果证明。
