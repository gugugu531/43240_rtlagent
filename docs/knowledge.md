# Skill 与诊断 RAG

[文档入口](index.md) · [架构](architecture.md) · [扩展规范](development.md)

本功能把本地 Skill（完整方法）与 RAG（检索增强生成）的通用知识卡加入 RTL 生成请求。它是 `rtl_generate` 的可选能力，适用于 `repair_loop` 和 `design_verify_loop`；不增加工作流，也不改变答案选择规则。原有预设默认关闭，`single_generate` 继续使用 baseline 固定消息。

## 使用

从方案目录运行；依赖、模型和工具须预先准备：

```bash
LLM_BACKEND=mock ./run.sh <公开题面目录> <新输出目录> --config config/repair_knowledge.yaml
```

[修复预设](../config/repair_knowledge.yaml) 与 [设计预设](../config/design_verify_knowledge.yaml) 分别沿用原流程的生成预算和采样设置，只启用冻结的时序 Skill v2；RAG 保持关闭。默认选中的时序 Skill 适用于寄存器、计数器、移位等公开题面，不代表对所有题型适用。选择方法由配置负责，当前不按题号、目录名或模型自动路由。

RAG 与 Skill 已分离冻结。[RAG 影子预设](../config/repair_rag_shadow.yaml) 只启用当前候选代码失败上的 K=1 exact 检索，不加载 Skill，也不是默认运行配置。开发集上的 BM25、Qwen3-Embedding-0.6B dense 和 RRF hybrid 只用于离线影子比较；未通过跨题族正确率门槛，因此没有导入运行包或替换 exact 路径。

| `nodes.generate.params` 参数 | 默认值与含义 |
| --- | --- |
| `skill_ids` | `[]`；固定选取最多两个不同 Skill |
| `skill_phases` | `[generate, repair]`；在哪些阶段尝试加入完整方法 |
| `rag` | `false`；启用当前代码检查失败的精确检索 |
| `knowledge_max_tokens` | `2048`，范围 0～8192；可选知识相对必要消息的最大 token 增量 |

只启用 RAG 可设置 `skill_ids: []`、`rag: true`。只启用 Skill 则设置 `rag: false`。同一对照应保持其余参数、模型、题面和工具一致；不要拿 baseline 与修复流程的差异归因为知识收益。YAML 节点覆盖仍替换整个组件的参数，省略的字段使用函数默认值。

## 资产

[目录清单](../knowledge/catalog.json) 登记五个方法：时序 v2、时序 v3、位宽与符号、组合逻辑完整性、FSM 状态与输出。时序 v2 冻结为通用固定正文；v3 因存在局部正确性收益但有稳定长尾，保留为非默认候选。位宽、组合逻辑和 FSM 候选在固定正文 A/B 中未通过正确性／成本门槛，冻结为拒绝状态，运行时会拒绝装配。v2/v3 共用冲突组，禁止同时选择。任务类型字段是维护者的说明，不是自动匹配器。原接口示范 `SKILL.md` 不在运行目录清单中。

[卡库](../knowledge/cards.json) 含六类方法：过程赋值变量、ANSI 重复声明、局部语法、未声明标识符、异常字符、多驱动。每张卡保留适用／不适用条件、方法、验证要求、反例与来源。来源固定为上游分支提交 `fb1c2803e5db0f32b59b9ba9100877f2a0d26412`，采用 MIT 许可；方法正文按当前接口与完整文件要求修订，版本带 `burr.1`。`frozen_exact_shadow_not_default` 表示正文和 exact 触发边界已冻结为影子条件，不表示真实模型收益、官方通过或允许扩大默认检索范围。

运行时只从方案 `knowledge/` 与 `skill/` 读取固定资产，不访问上游仓库或开发区。来源元数据中的上游路径仅用于追溯，不是待加载路径。实验族、人工指定正确卡、检索标签、参考答案、官方测试台和判定反馈未导入。

加载器拒绝额外字段、重复键、重复 ID、错误类型、路径越界、符号链接、超大文件，以及 Skill 正文哈希或 frontmatter 不符。每题首次使用时固定资产对象；修改资产须启动新运行。卡库身份以实际文件哈希记录，Skill 额外由目录清单校验正文哈希；哈希不是对内容正确性的证明。

## 检索和证据

`check_stages()` 和设计流程的最终综合交接本次 `CheckResult`，分配独立 `execution_id`。每次生成开始消费一次交接，即使知识关闭或后续提取失败也不会复用。

只有以下条件同时成立才检索：

- 当前父候选 ID、代码哈希、检查器哈希均匹配；检查类型为 `lint` 或 `synth`。
- 状态为 `failed`、失败类型为 `code`；环境失败、未知、超时、功能失配、提取失败和成功检查上的警告不触发。
- 逐命令诊断完整，且错误来自失败命令，具有明确工具与版本。
- 错误码、工具、版本、错误正文词组同时匹配卡片触发条件；连带诊断不作为根因。

检索不使用题号、任务路径或候选代码做搜索词。结果按卡片 ID 排序，最多选一张；其它命中记为 `injection_limit`。语义上的适用与不适用限制随正文保留，由生成模型结合公开题面核查；当前没有用程序证明每条自然语言适用条件。只支持卡片声明的 Vivado 2026.1，未知或其它版本不匹配。错误词组和当前代码失败归因白名单都可能限制召回。

单条诊断的工具取实际命令名，版本取该命令的 banner；`xvlog` 无 banner 时允许在剩余检查时间内调用相同可执行文件的 `--version`，每题缓存探测结果并记录来源。未知探测结果仍保留未知。原 `repair_diagnostics` 保持原格式，新来源信息在 `knowledge_diagnostics/knowledge_commands/knowledge_version_probes` 中。

## 上下文和预算

先渲染完整原消息，保留公开题面、接口、当前候选、反馈和计划。固定 Skill 按配置顺序尝试，然后尝试知识卡；方法正文保持完整。通过统一模型客户端对完整消息分词，只有总输入加原 `max_tokens` 不超过上下文上限，且增量不超过 `knowledge_max_tokens` 时才加入。否则整段省略，不截掉限制或压缩必要内容。原消息已挤占输出空间时省略所有知识，保留原客户端的处理方式。

底层 `agent.knowledge.context.prepare()` 支持显式 `diagnostic_first=True`：存在父候选时先装配匹配的诊断卡，再按原顺序装配 Skill，并记录选择。默认值为 false，当前 `rtl_generate` 保持原顺序。`adaptive_verify` 将通过原文引用校验的短分析映射为至多两个固定 Skill ID，修复时启用诊断卡优先；旧工作流的固定选择不变，详见[自适应工作流](adaptive.md)。

知识放在明确标记的 user 参考区，不替换 system 消息。最多两条 Skill 加一张卡，额外分词最多四次；实际生成仍沿用客户端最终分词。知识准备、模型发现、分词与生成共享节点请求时间窗及全题截止。分词不可用明确失败，不用字符估算替代；mock 的近似分词仅验证流程。

## 独立性和记录

知识不进入规划、检查器构造、审核、修订或独立验收；`structured.request()` 和这些节点保持原输入边界。功能检查不因检索命中而视为通过。

- `source.json` 增加 `skill/knowledge` 文件哈希。
- `knowledge/check_evidence` 记录本次执行引用与候选身份。
- `knowledge/resources` 记录本题实际加载资源。
- `knowledge/assembly` 记录命中、拒绝、整段加入或省略、预算、消息哈希及父候选绑定；full 模式另存 `knowledge/<assembly_id>.json`。
- `knowledge/model_result` 关联成功返回的模型调用；实际发送内容以对应 `calls/` 请求为准。装配完成不等于模型已收到，脱敏后的记录也不一定与发送字节相同。

新增卡或方法必须审核来源、边界与许可证，并用正反例检查加载、匹配、拒绝和预算。检索命中、模型修改、子候选重新检查、功能通过和官方成绩分别记录。无开发目录的包已能加载资源，并不代替正式镜像、真实模型或目标 GPU 验收。
