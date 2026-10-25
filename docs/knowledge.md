# Skill 与 RAG 框架 v1

[文档入口](index.md) · [架构](architecture.md) · [扩展规范](development.md)

本版是运行接口与小型机械验收，不代表知识收益验收或全系统效果冻结。默认 RAG 关闭，包括 `adaptive_verify`。`single_generate` 的 baseline 固定消息与实现保持不变。

英文发布版 `framework-v1-en.1` 将系统／修复提示、知识包装、接口反馈摘要及六张历史卡统一为英文。32 张英文卡正文、向量和准入决策不变；自然语言缺失事实描述只做翻译，不因此开放注入。用户题面、工具原始输出按原样保留，不自动翻译；中文识别正则和开发文档不是模型包装残余。

## 模式与准入

`rtl_generate` 节点支持 `skill_mode`、`rag_mode`，均为 `off / shadow / on`。自适应工作流的同名参数位于顶层 `params`。

- `off` 不检索、不装配。
- `shadow` 检索并记录准入，但不更改生成消息，也不请求知识装配的 tokenizer。记录的是“准入后待装配”，不宣称已通过 token 预算。
- `on` 只有通过准入和预算的完整知识段才进入请求。

工具编译输出没有版本时，RAG 可额外探测版本用于检索准入和日志。自适应修复的基础消息只保留编译输出自身携带的版本；额外探测所得版本及探测标识不进入基础消息，因此 `shadow` 不会借由诊断元数据改变求解提示。原始检查记录和检索使用的版本证据完整保留。

旧配置兼容：未设置模式时，非空 `skill_ids` 表示 Skill on；`rag: true` 表示 RAG on。显式模式与旧 `rag: true` 冲突时报配置错误。自适应 Skill 默认 on，保留原主机映射，经同一个准入层过滤。

时序 v2 可自动准入；v3 仅供固定注入实验，自动选择不启用非默认候选。位宽、组合逻辑、FSM 仍处于 fixed A/B 拒绝状态。显式选择拒绝／未知／冲突 Skill 在构图阶段报错，模型请求之前停止；自动选择记录拒绝原因并继续无知识生成。自动路由入口是主线 `choose_route`，离线旧路由器不被视为第二个运行时权威。路由收益尚未验收。

## 统一检索接口

`retrieval` 配置：

| 字段 | 默认值 |
| --- | --- |
| `strategy` | `exact`；可选 `bm25 / dense / hybrid` |
| `retrieve_k` | 5，上限 32 |
| `inject_k` | 1，本版固定上限 |
| `fallback` | `empty`；可显式改为 `exact` |
| `release_id` | `framework-v1-en.1` |
| `release_sha256 / policy_sha256` | 未显式设置时使用随包 `runtime-lock.json`；显式值必须与锁文件一致 |
| `embedding_url` | 空；服务根 URL，客户端追加 `/v1/embeddings` |
| `embedding_transport` | `http`；可选 `ssh` |
| `embedding_timeout_s` | 2 秒，最大 10 秒 |
| `embedding_ssh_host / embedding_ssh_port` | 空 / 22；仅 SSH 使用 |

HTTP 不使用环境代理，不跟随跳转。SSH 要求已有可信主机密钥，服务 URL 必须是远端 loopback HTTP；只运行固定 curl 请求，查询通过标准输入传输。模型别名、1024 维度、有限数值和非零向量均验证。别名校验不能替代服务端权重哈希审计。

发布包包含 32 张英文卡及冻结文档向量，不含开发查询、标签、参考 RTL 或判定结果。BM25 使用冻结分词与参数；dense 为精确点积；hybrid 为 exact/BM25/dense 的 RRF（常数 60）。F24 是额外受限 exact 通道，没有伪造向量，trace 用 `lane: restricted_exact` 区分。完整系统排名不能直接冒充原 32 卡离线指标。

embedding 只接收限长、路径脱敏后的首个有效工具诊断及工具元数据，不接收完整题面或 RTL。知识准备最多使用剩余请求窗口的 10% 且不超过 5 秒；embedding 超时进一步限制在该窗口的一半，给生成保留时间。超时、断连、响应 JSON 结构不合法、模型／向量不兼容按配置降级，记录有效后端及延迟；HTTP 200 也必须通过结构校验。服务失败使用 `retrieval_unavailable`，不算正确空返回；还应检查 `embedding_error` 和 `effective_strategy`。

## 保守准入边界

检索先检查候选 ID／哈希、执行 ID、检查器哈希、状态、诊断完整性和版本。只采用工具顺序中的首个非级联 error，次生诊断不能授权注入。

32 卡原政策中的 `model_not_needed`、`correct_empty_by_default`、缺功能夹具等直接拒绝。自然语言“缺失事实”不能靠词面猜测：尚无机械证据时记录 `missing_fact_not_mechanically_established`，不开放注入。明确反馈片段以及候选／原始反馈哈希绑定的 correct_empty 检查点也能拒绝；自适应反馈不是旧检查点原始格式时，不伪造哈希命中。

本版正向注入路径是 F24：lint、xvlog 2026.1、首诊断 VRFC 10-4982 且 `syntax error near ','`、当前代码存在错误复制项拼接形态；先排除注释与字符串。无候选形态、未知版本、次生错误、已提供相同方法均不注入。正则是受限形态守卫，不是完整 Verilog 语法证明，仍须重新检查和功能验证。

原 `knowledge/cards.json` 六卡快照保留为历史资产，不是本版检索入口。不要把六卡宽匹配称为 F24 准入。K=1 天然禁止卡间共同注入；扩大 K 必须实现并验收冲突政策，不能仅修改上限。

## 发布与记录

`python -m agent.knowledge.publish <实验仓库>` 从声明源文件生成 `knowledge/runtime-v1.json` 与摘要。发布验证 corpus/index 配对和 F24 投影哈希；运行加载再检查文件摘要、唯一 ID、文档投影哈希和向量。Skill 仍使用 catalog 的版本／正文哈希／状态校验。源文件变更需重新发布和验收，禁止直接手改向量。

英文发布采用 schema 2，并生成 `runtime-lock.json`。每条准入规则、检查点规则和文档向量元数据都绑定实际英文卡的 `card_version` 与规范 JSON 的 `card_sha256`。旧策略版本仅保留在 `source_card_version` 作来源记录，不能参与当前卡版本匹配。F24 的卡哈希与确定性谓词 ID 单独绑定；发布锁同时固定准入策略、索引和六卡快照的摘要。历史六卡版本更新为 `1.0.1-burr.en.1`，其原 `source` 仍表示上游来源，不冒充译文哈希。

`repair_rag_shadow.yaml` 显式固定发布／策略摘要；其它开启 RAG 的配置至少使用同一锁文件，显式错误 pin 在模型调用前拒绝。重新发布后应同步显式 pin 并运行测试，不能只改外层文件摘要。翻译改变了生成提示的语言，因此旧效果结果不自动成为本版收益证据。

每次装配记录 `skill_selected / skill_rejected`、`retrieval.retrieved / admitted / rejected`、完整段预算结果和 `sent`，并保存原消息／实际消息哈希与耗时。`model_result` 绑定 call ID。可选资源或 tokenizer 失败保留原消息继续求解；配置错误由预检处理，硬性总任务超时不吞掉。

`framework-outcome.json` 的汇总 schema 为 2，汇总完整新稿交付、候选选择、solution 哈希、工具结果和阶段成本。`latest_complete_candidate_id` 只统计有明确 `complete_new_draft: true` 交付证据的候选，按候选创建顺序取最后一份；交付通过候选 ID 绑定，只有未记录候选 ID 的旧式自适应事件才通过唯一的模型调用 ID 关联。创建候选、保存答案和默认 `extraction_status` 均不能证明完整性。

`selected_candidate_complete` 为 true／false／null，表示明确完整、明确不完整或缺少证据。baseline 保持主办方提取行为，未执行完整性验证时为 null；此时 `selected_latest_complete` 也为 null。`selected_latest_complete` 不等于“本次修复成功”：没有新稿时 latest complete 仍可能是旧稿，须同时检查 `deliveries`；完整交付也不代表 RTL 通过编译或功能检查。外部评分与评分候选默认为 null，不猜测尚未运行的主办方评分。

## 验收与后续

`python -m unittest discover -s tests -v` 使用合成场景，不依赖题库、参考答案或在线模型。包括命中、correct_empty、版本／候选拒绝、自动 Skill 拒绝、预算不足、服务失败、未交付，以及实际 Burr 修复图的 off/shadow 消息逐项相同检查。

机械验收后仍需：逐卡补足缺失事实可执行谓词；固定框架优化 Skill 正文；固定资产比较检索器；独立优化准入与表达；最后验证自动路由、联合使用、留出集与 balanced60。默认 RAG 不因框架连通而打开。
