# Skill 与 RAG

[文档入口](index.md) · [架构](architecture.md) · [扩展规范](development.md)

本页描述当前仓库中 Skill、RAG 研究目录和检索接口的使用边界。详细的批次审计、
运行手册和实验记录已移到工作区 `dev/archives/20261029-rag-rc46/`，不随参赛包分发。

新合并的 rc4.6 研究路线（`catalog-v3`、pregen/feedback、dense embedding）尚未接入
`guided_verify`。`guided_verify` 目前仍使用既有的 legacy `runtime-v1` bundle：
`_shortlist` 对 legacy cards 做 BM25，planner 选中的 knowledge 再由
`_skill_and_card_material` 注入 solve。不能把 rc4.6 的新状态说成 guided 的默认行为。

## 默认行为

- `single_generate`、`repair_loop`、`design_verify_loop` 和 `adaptive_verify`
  的默认配置都不启用 rc4.6 RAG。
- `guided_verify` 不读取 `rag_mode`，但保留既有 legacy 检索：对 `runtime-v1`
  bundle 的 cards 做 BM25 候选，planner 选中的 knowledge 注入 solve。这是当前
  已实现行为，不等同于 rc4.6 研究路线接入。
- `skill_mode`、`rag_mode` 的取值为 `off`、`shadow`、`on`。
  - `off`：不检索、不装配。
  - `shadow`：执行检索和准入并记录结果，但不改变模型消息。
  - `on`：只有通过准入和预算的完整知识段才进入请求。
- `adaptive_verify` 默认自动 Skill on、RAG off；只有经过自动准入的 Skill 才会进入
  生成装配。
- rc4.6 RAG 开启需要显式配置文件或参数，不会因知识资产存在而自动生效。

## 目录与资产

| 路径 | 用途 |
|---|---|
| `agent/domain/knowledge/` | 检索、准入、预生成、反馈、发布和目录验证实现 |
| `knowledge/catalog.json`、`cards.json`、`runtime-v1.json`、`runtime-lock.json` | 默认诊断库及发布锁 |
| `knowledge/catalog-v3.json` | 统一研究目录，绑定卡片状态与受限准入 |
| `knowledge/research-v*.json`、`research-*-vectors.json`、`*-lock.json` | 研究目录、向量和哈希锁 |
| `knowledge/embedding-runtime-lock.json` | dense embedding 运行身份 |
| `serve/embedding_service.py` | 可选的本机 embedding 服务；不是默认启动路径 |
| `config/rag_catalog_v3_shadow.yaml` | 统一目录 shadow 观察配置 |
| `config/rag97_pregen_bm25.yaml` | 首轮生成 BM25 显式配置 |
| `config/rag97_pregen_dense.yaml` | 首轮生成 dense shadow 配置 |
| `config/rag97_feedback_shadow.yaml` | 功能反馈 shadow 配置 |

研究资产属于当前 RAG 路线的代码产物，保留在仓库中；其中的卡片和测试夹具只使用
公开题面或公开方法事实，不包含题库参考答案、官方测试台或判定反馈。

## 卡片状态与准入

研究目录中的卡片状态包括：

- `legacy_policy`：原诊断策略路径；
- `restricted`：满足显式谓词和装配条件时可注入；
- `shadow`：只观察，不改变模型消息；
- `hold`、`mechanical_only`：不进入当前注入路径。

检索先验证卡片身份、版本、发布锁、状态、工具诊断和阶段权限。`shadow` 记录检索与
准入结果，但不授权注入。`restricted` 还必须在实际装配阶段重新检查，不能仅凭检索排名
或 `admitted` 字段判断已发送。未知、冲突、资产或服务错误按失败关闭处理，不能算作
`correct_empty`。

## 使用方式

```bash
# 只做 shadow 观察；不改变生成消息
AGENT_CONFIG=config/rag_catalog_v3_shadow.yaml ./run.sh <input> <output>

# BM25 首轮生成；只在显式配置下运行
AGENT_CONFIG=config/rag97_pregen_bm25.yaml ./run.sh <input> <output>
```

dense 配置需要匹配的 embedding 服务：

```bash
.venv/bin/python serve/embedding_service.py \
  --binary /path/to/llama-server \
  --model /path/to/embedding-model.gguf
```

`--binary` 是 llama.cpp 服务端可执行文件，`--model` 是 embedding 权重文件；两者都是
必填项。启动前会用锁文件校验程序、动态库和权重哈希。可用 `--check-only` 只做身份和
命令检查。HTTP 不跟随代理或跳转；超时、结构不合法、模型身份不一致或向量非法时安全
返回空，并记录 `embedding_error` 或 `retrieval_unavailable`，不能把服务失败算成知识收益。

## 发布与验证

知识资产变更必须通过发布脚本重新生成锁文件和摘要，不能手改向量：

```bash
python -m agent.domain.knowledge.publish <实验仓库>
```

运行加载会校验文件摘要、发布锁、卡片哈希和向量身份。当前仓库的默认测试：

```bash
pytest
```

测试只使用公开题面和合成检查输入；真实模型、Vivado 和官方判定需要另行执行，
mock 通过不等于知识收益或官方成绩。

## 与 guided_verify 的关系

`guided_verify` 当前保留既有 legacy 检索行为，但不接入新合并的 rc4.6 研究目录。
具体来说：

- `_shortlist` 使用 legacy `runtime-v1` bundle 的 cards 做 BM25，最多返回配置数量的
  候选；
- planner 从候选中选择 knowledge，`_skill_and_card_material` 把选中卡片的公开文本
  注入 solve；
- 这条路径不读取 `rag_mode`，也不使用 `catalog-v3` 的 activation state、pregen/
  feedback 或 dense embedding。

未来把 rc4.6 接入 `guided_verify` 时需要明确：

1. rc4.6 检索发生在 planner、solve 还是检查阶段；
2. shadow 结果是否只进入记录，不进入模型请求；
3. 知识段预算与 guided 的 completion、token 预算如何共同限制；
4. 检索失败、资产失败和空返回如何与 guided 的 checker invalid 区分；
5. 新路径与现有 legacy BM25 注入如何避免重复或冲突；
6. 任何注入都不能把参考实现、官方测试台或判定反馈带入模型提示。

在这些条件落实前，现有 legacy 行为不变，rc4.6 不自动启用。
