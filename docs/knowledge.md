# Skill 与知识检索

[文档入口](index.md) · [架构](architecture.md) · [Guided Verify](guided-verify.md)

知识库现在只保存卡片正文和可检索文本。卡片版本、sha256、文件路径、release lock 和向量
文件哈希不再维护。Skill 文件和 prompt 模板保持现状。

## 1. 文件

```text
knowledge/cards.json     129 张卡片正文
knowledge/vectors.json   129 个 card_id + 向量
knowledge/catalog.json   Skill 目录
config/rag_embedding.yaml embedding 运行参数
config/rag97_pregen_bm25.yaml
config/rag97_pregen_dense.yaml
config/rag_catalog_v3_shadow.yaml
config/guided_verify_rag_bm25.yaml
config/guided_verify_rag_dense.yaml
```

`knowledge/cards.json` 的卡片来自合并分支的 129 张唯一卡片：32 张 legacy、38 张
restricted、33 张 shadow、26 张 mechanical_only。每张卡片保留标题、适用/拒绝条件、
方法正文、验证/停止条件和必要的 activation state。

## 2. 检索模式

`agent/domain/knowledge/guided.py` 提供：

```python
load_cards()
load_vectors()
retrieve(query, mode="legacy", limit=5, strategy="bm25")
card_text(card)
```

模式：

- `legacy`：只取 `legacy_policy` 卡片，保持 guided 原有行为；
- `rag`：取 `legacy_policy` 和 `restricted` 卡片；
- `all`：包含 shadow 和 mechanical_only，仅用于开发检查；
- `off`：不检索。

`guided_verify` 默认 `retrieval_mode=legacy`、`retrieval_strategy=bm25`。RAG 路线通过
显式配置选择；dense 失败时返回空候选并在 `knowledge/retrieval` 记录
`embedding_unavailable`，不会静默回退到 BM25：

```bash
AGENT_CONFIG=config/guided_verify_rag_bm25.yaml ./run.sh <input> <output>
```

## 3. dense embedding

dense 需要 `serve/embedding_service.py`，参数为：

```bash
.venv/bin/python serve/embedding_service.py \
  --binary /path/to/llama-server \
  --model /path/to/Qwen3-Embedding-0.6B-Q8_0.gguf
```

模型与查询投影参数在 `config/rag_embedding.yaml`：

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

建库和查询都必须使用同一模型、同一维度、同一 pooling/归一化和同一 query 投影。
`knowledge/vectors.json` 只保存向量，不重复保存模型元数据。

## 4. 单路线 RAG

`config/rag97_pregen_bm25.yaml`、`config/rag97_pregen_dense.yaml` 和
`config/rag_catalog_v3_shadow.yaml` 仍使用 `single_generate` 的
`rtl_generate`/`rtl_extract` 节点：

```text
generate -> extract -> select -> finish
```

它们作为显式 RAG 路线保留，不等于默认求解流程。

## 5. 边界

- 卡片只包含公开方法文本，不包含参考实现、官方测试台或判定反馈。
- 检索失败、空结果或 embedding 不可用时，请求继续使用原题面和接口，不把失败算作知识收益。
- 当前没有 release lock、卡片版本比较或文件哈希校验；修改卡片或向量后应重新验证检索结果。
- `guided_verify` 的 RAG 模式仍是可选项，默认使用 legacy 检索。
