# 统一知识目录 v3：运行与回退

当前交付为 `rag-catalog-v3-rc2` 研究发布候选。129张登记项由旧32张与新增97张组成。默认配置仍按原策略运行；首次生成研究使用 `config/rag_catalog_v3_shadow.yaml`。

根目录 manifest 已显式设置 `generation.chat_template_kwargs.enable_thinking=true`，baseline和方案读取同一设置。云端本批实验也已逐请求显式开启thinking；不要依赖服务默认值。manifest的正式模型申报占位字段仍需在正式提交阶段填写，本次知识库交付不声称完成赛事提交材料。

rc2收紧X/Z准入：只提到未知选择器不足以授权合并方法；题面需明确合并或对应的逐位关系。已有事实的证据位置保持原文偏移。反馈后支持两个窄源码事实拒绝：实际输出的字面量宽度 indexed select，以及实际移位左操作数的明确 signed 来源。它们只在执行证据已绑定后使用。

mixed-sign最新修订使用“原宽signed中间量→目标宽signed中间量”，已通过256个输入及两个错误变体区分；该版本尚无模型配对，保持hold。其余云端实验冻结在rc1，原始证据保留。四类受限题面卡的实际渲染未变，rc2对原四个首次生成场景的消息已独立重构比较。

## 环境与服务

使用已有Python依赖环境。云端验证使用 `/root/rtl-rag-v27-20261028/.venv312/bin/python`，不能直接用云端默认Python3.14替代。生成服务为已有8010端口，模型别名 `qwen38-27b-q4-k-m`。

embedding启动器检查权重、CPU程序及四个动态库哈希；使用已复现的f114f91版本、last pooling、4线程，客户端执行L2归一化。示例中的路径按本机或云端选择：

```bash
.venv/bin/python serve/embedding_service.py \
  --binary /home/cloudia/.cache/rtlagent-embedding/runtime/build/bin/llama-server \
  --model /home/cloudia/.cache/rtlagent-embedding/models/Qwen3-Embedding-0.6B-Q8_0.gguf \
  --check-only
```

去掉 `--check-only` 后在前台运行，仅监听127.0.0.1:8020。云端相应程序路径为 `/root/rtl-rag-v29-20261028-r1/dev/optimization-v29/portable/bin/llama-server`，模型路径为 `/root/rtl-rag-models/Qwen3-Embedding-0.6B-Q8_0.gguf`。不要替换既有8010生成服务。

在另一个终端执行实际任务（这会调用生成模型）：

```bash
.venv/bin/python -m agent.main \
  --input /absolute/path/to/task \
  --output /absolute/path/to/new-output \
  --config config/rag_catalog_v3_shadow.yaml
```

输入目录提供 `prompt.txt`；接口按现有任务协议从题面读取。shadow执行检索／准入记录，生成消息与同条件基线一致。受限on必须使用单独实验配置并核对卡片状态、实际发送清单和知识预算；不要直接批量修改所有卡为可注入。

## 资产和证据

- `knowledge/research-v3.json`、`research-v3-lock.json`：统一目录正文、规则和实现身份。
- `knowledge/catalog-v3.json`：逐卡状态、阶段和旧诊断策略适配关系。
- `knowledge/research-v3-vectors.json`及其锁：真实向量与文本／版本绑定。
- `knowledge/embedding-runtime-lock.json`：部署程序及动态库身份。
- 原32卡继续使用原诊断策略与F24专门路径，未将研究目录中的旧卡映射当成新注入许可。

shadow、hold、mechanical_only不获得普通on注入许可。没有谓词或缺少证据返回unknown；明确重复／不适用为not_needed；服务／资产异常为failure。

## 回退

恢复使用原配置的off模式或原32卡诊断路径即可停止研究目录注入。原 `knowledge/runtime-v1.json`及锁、旧v2研究文件均保留。需要复现旧实验时，在其冻结归档的隔离目录中运行，不能用当前rc2代码解释rc1实现哈希。

候选交付包不含模型权重和工具安装，不自动切换线上配置；完整性收据、版本和报告一并保存于 `dev/optimization-v39/`。
