# 技能包

本目录保存可复用的 RTL 方法。运行时能力及配置见 [Skill 与诊断 RAG](../docs/knowledge.md)。方案根 README 按约定保持为空。

当前 `repair_loop` 与 `design_verify_loop` 的 `rtl_generate` 可通过 `skill_ids` 固定选择完整方法，默认不加载。`single_generate` 继续使用 baseline 消息。技能只供 RTL 生成／修复参考，不进入独立检查器；知识不能覆盖公开题面、接口或实际工具证据。

| 技能 ID | 用途 |
| --- | --- |
| `rtl-sequential-state-update` | 时序状态、复位、控制优先级、移位和计数 |
| `rtl-sequential-state-update-v3` | 同主题候选版本，增加声明与拼接交付检查；不可与 v2 同时选择 |
| `rtl-width-signed-arithmetic` | 位宽、signedness、扩展和截断 |
| `rtl-combinational-completeness` | 组合赋值完整性、优先级与非预期存储 |
| `rtl-fsm-state-output` | 状态转移与 Moore／Mealy 输出时序 |

这些资产来自 [上游分支](https://github.com/wyc888-crypto/amd-rtlagent-prompt-engineering/tree/fb1c2803e5db0f32b59b9ba9100877f2a0d26412)，按 MIT 许可迁移。完整正文用英文，目录清单保存来源版本、原文哈希与移植后哈希；已修正与本方案冲突的单模块限制，保留原版权说明。它们尚未通过本方案的真实模型效果实验。

新方法文件使用 `skill/<id>/skill.md`，frontmatter 只有 `name` 和 `description`，必须与 [目录清单](../knowledge/catalog.json) 一致。正文保留适用／不适用条件、输入、步骤、验证、输出和行为边界。变更正文后必须同步清单哈希与版本，不能将完整方法截成无边界的片段。

原有 `rtl-module-interface-contract/SKILL.md` 保留为人工阅读示范，未列入运行目录清单。其历史证据不作为新功能效果证明；新运行只读取清单声明的资产。不得把参考答案、官方测试台、判定反馈或任务身份映射写入技能。
