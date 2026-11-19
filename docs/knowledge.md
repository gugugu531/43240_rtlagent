# 技能与知识检索

[文档入口](index.md) · [架构](architecture.md) · [guided_verify 工作流](guided-verify.md)

本项目把可复用的方法分为技能（Skill）和知识卡片。技能由程序扫描目录后选择，知识卡片通过 RAG（检索增强生成）加入模型请求。当前默认 `guided_verify` 启用技能选择，关闭知识卡片检索；这两项设置相互独立。

知识库保存卡片内容和可检索文本；卡片与向量文件不保存版本、文件路径、SHA-256 校验值或发布版本锁定信息。技能文件则在每题首次读取时建立固定快照，并记录内容校验值。提示模板使用 Markdown，由 Jinja2 渲染。

## 1. 文件与技能选择

```text
knowledge/cards.json        129 张知识卡片
knowledge/vectors.json      129 组卡片标识 card_id 及对应向量
skill/<id>/skill.md         技能正文及文件头元数据
config/rag_embedding.yaml   文本嵌入模型与查询格式
```

129 张卡片沿用四种状态标记：`legacy_policy`（早期诊断方法）32 张、`restricted`（按条件使用）38 张、`shadow`（研究观察）33 张、`mechanical_only`（原计划仅供程序检查）26 张。这些是历史分类名称；是否允许加入当前请求，还取决于卡片的 `injection_eligible` 和 `phases` 字段。卡片保留标题、适用与拒绝条件、方法、验证及停止条件。

新增技能只需添加 `skill/<id>/skill.md`，声明 `name`、`description` 并填写正文，无需维护 `knowledge/catalog.json` 或手动填写内容校验值。已有目录也可读取 `SKILL.md`；两者同时存在时优先读取小写文件。程序只扫描直接子目录，技能总数不限制为 32 项。文件格式、可选字段和来源要求见[技能扩展指南](../skill/README.md)。

现有专项技能覆盖计数终点、反馈移位、流式分组、单时钟存储、流水线对齐、打包向量索引和卡诺图坐标。它们只描述通用方法，不含题目身份与答案的对应关系。新增专项方法允许自动选择，已有技能的候选或禁用状态保持不变；这些设置不代表已验证真实模型收益。

- `guided_verify` 每题先建立技能快照，策略角色从允许自动选择的名称和描述中最多选两个。即使行为表无法处理本题的接口或时钟，仍可选技能。首稿按 `generate` 筛选正文，结构修复和解题决策按 `repair` 筛选正文。独立行为检查角色建表、修正自身回复格式和复核指定点时使用固定的 `rtl-behavior-check-keycases`。
- 通用生成节点 `rtl_generate` 默认使用 BM25（基于词项匹配的相关性排序算法）检索技能描述，至少匹配两个不同词项才会入选，同样最多选择两个。也可通过 `skill_ids` 显式选择，或设置 `skill_mode=off/shadow/on`；三个值分别表示关闭、只记录选择、实际加入请求。
- `single_generate` 的默认基线节点不加载技能。显式 RAG 配置可将其节点替换为 `rtl_generate`，详见第 4 节。

完整记录中的 `guided/material*.json` 保存构造请求时加入的技能、知识卡、拒绝原因、阶段和技能快照校验值。核对实际发送情况时，查看 `guided/request-outcomes.json` 和 `guided/completion-ledger.json` 中已分配 `call_id` 的生成调用，再查 `calls/<call_id>/request.json`。`rtl_generate` 使用 `knowledge/skills` 事件记录技能选择。同一题处理期间沿用技能快照，文件修改自下一题生效。候选或禁用状态保存在 YAML 文件头元数据（frontmatter）中，文件格式非法时明确报错。

## 2. 知识卡片检索模式

当前工作流通过 `agent/domain/knowledge/guided.py` 读取随包卡片与向量。扩展代码也可直接使用下列接口。技能扫描使用 `assets.load_assets(skills=True)`。同一函数的 `rag=True` 分支要求顶层 `schema_version`，直接用它打开随包的 `cards.json` 会出现格式校验错误。

```python
load_cards()
load_vectors()
retrieve(query, mode="legacy", limit=5, strategy="bm25")
card_text(card)
```

检索先按状态和使用阶段筛选卡片，再排序。所有启用模式都要求 `injection_eligible=true`，且卡片允许当前阶段；若还声明了 `injection_stages`，也必须满足该字段。

| 模式 | 状态范围与当前行为 |
| --- | --- |
| `legacy` | 仅考虑 `legacy_policy`。现有 32 张卡片均为 `post_diagnostic`（诊断之后），且不允许加入请求，因此当前首稿检索结果为空。 |
| `rag` | 考虑 `legacy_policy` 和 `restricted`。当前首稿阶段可使用符合条件的 `restricted` 卡片。 |
| `all` | 将 `shadow` 和 `mechanical_only` 也列入状态筛选范围，仍检查阶段和使用许可，不代表所有卡片都可加入请求。该模式用于开发检查。 |
| `off` | 不检索。 |

`guided_verify` 默认 `retrieval_mode=off`、`retrieval_strategy=bm25`，不发送知识卡片。启用时可选择 BM25，或 `dense`（稠密向量检索）。策略角色看到检索候选并选卡，程序只在首稿生成及其空正文恢复时加入允许的知识卡正文。向量检索失败会返回空候选，在 `knowledge/retrieval` 中记录 `embedding_unavailable`，不会自动改用 BM25。

可选配置 `guided_verify_rag_bm25.yaml` 和 `guided_verify_rag_dense.yaml` 仍保留早期小模型规划服务，需要先核对[历史小模型说明](guided-verify.md#8-历史小模型研究与当前技能)，不能直接视为默认主模型配置。准备对应服务后，在方案仓库根目录运行，例如：

```bash
AGENT_CONFIG=config/guided_verify_rag_bm25.yaml ./run.sh /path/to/input /path/to/output
```

## 3. 文本嵌入与向量检索

向量检索用文本嵌入（embedding）模型把查询转换为数值向量。服务入口为 `serve/embedding_service.py`，在方案仓库根目录运行：

```bash
.venv/bin/python serve/embedding_service.py \
  --binary /path/to/llama-server \
  --model /path/to/Qwen3-Embedding-0.6B-Q8_0.gguf
```

以上路径须替换为已准备的 Python 环境、服务程序和模型文件。运行参数和查询模板位于 `config/rag_embedding.yaml`：

```yaml
model_alias: qwen3-embedding-0.6b-q8-0
dimensions: 1024
pooling: last
normalization: l2
similarity: exact_cosine_dot_product
max_length: 4096
query_instruction: ...
query_template: ...
```

建库与查询使用的模型、1024 维向量和池化方式必须兼容。`pooling: last` 表示取最后一个词元的表示；`normalization: l2` 表示将向量缩放到单位长度，随后用点积计算余弦相似度。查询按 `query_instruction` 和 `query_template` 组织文本，修改模板后需要重新核验检索结果。`knowledge/vectors.json` 只保存卡片标识与向量，不重复保存上述模型参数。

## 4. 单次生成的 RAG 配置

`config/rag97_pregen_bm25.yaml`、`config/rag97_pregen_dense.yaml` 和 `config/rag_catalog_v3_shadow.yaml` 使用 `single_generate` 工作流，但将生成与提取节点设为 `rtl_generate`、`rtl_extract`：

```text
generate -> extract -> select -> finish
```

三个研究预设都显式关闭技能，知识卡另受 `rag_mode` 控制。`rag97_pregen_bm25.yaml` 使用 `mock` 后端和 `on` 模式，符合条件的卡可进入生成请求。`rag97_pregen_dense.yaml` 使用 `mock`，`rag_catalog_v3_shadow.yaml` 使用 `openai`，二者均以 `shadow` 模式只记录稠密检索结果。`on` 模式下，`rtl_generate` 按 Python 字符串长度计算 `knowledge_max_tokens` 的卡片文本上限。

## 5. 来源与验证边界

- 技能来源、实际复用范围和许可见[技能扩展指南](../skill/README.md#现有技能与来源)。相关研究的思想借鉴见[报告](../REPORT.md)，不能把方法相似或配置存在写成复现了论文系统。
- 卡片只包含公开方法，不包含参考实现、官方测试台或判定反馈。
- 检索关闭、没有命中或向量服务不可用时，解题可沿用公开题面和接口继续。技能文件和知识卡文件仍须满足各自加载器的格式要求。
- 当前没有卡片发布版本锁定、版本比较或文件校验机制；修改卡片、向量或查询模板后需要重新验证检索结果。
- 当前默认关闭 RAG，保留可选配置不能证明其在当前模型、预算和完整题集上有效。
