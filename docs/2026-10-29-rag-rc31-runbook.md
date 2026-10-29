# RAG目录rc3.1：十二类候选谓词与四类受限注入

当前研究版本 `rag-catalog-v3-rc3.1` 登记原32张和新增97张，39张仍冻结。四类受限方法保持conditional-X、定宽动态切片、NBA采样、sticky-event。第42批的六类新方法已有真实准入谓词，但状态仍为shadow；carry及算术右移也仍shadow。其余方法按原状态执行。

六类新方法是逐位掩码、无符号饱和减法、采样边沿、限定模数、饱和计数、双项打包。它们要求明确公开合同，源码格式不作题号或夹具哈希匹配。计数需要可表示的数字边界；边沿需要历史初值；打包当前仅覆盖先接收项低位、后接收项高位。缺条件返回unknown，不适用或已给事实返回not_needed，服务或资产异常返回failure。

rc3.1增加了跨方法保护：保存前一采样用于边沿比较，不独自授权NBA采样卡。NBA还要求公开合同明确输出／发布前一采样值。该修正在96条同集真实embedding查询中复测，并重建核对原四个首次生成请求一致；不是新模型观察。

## 使用与证据边界

默认使用 `config/rag_catalog_v3_shadow.yaml`。shadow记录检索和准入，模型消息与同条件off基线一致。on只发送restricted且谓词、预算通过的整张卡。研究卡不因 `injection_eligible` 或检索命中而跨过状态守卫。

第42批云端包冻结在rc3，独立目录 `/root/rtl-rag-cohort42-20261029-r1`。六类新方法是显式固定卡首次生成筛选，另四张hold卡是修复对照。它们不授予新六类生产on权限。复现时使用原归档代码，不能用rc3.1覆盖旧包。

目录状态仍为legacy_policy 32、restricted 4、shadow 62、hold 5、mechanical_only 26。mixed-sign有再次退步的观察；卡片继续hold。模型输出必须经工具检查，卡片正确示例并不能保证模型遵循。

## 环境

生成服务继续使用两机已有 `http://127.0.0.1:8010/v1`、模型别名 `qwen38-27b-q4-k-m`。thinking由根manifest显式开启。

embedding保留Qwen3-Embedding-0.6B-Q8_0，1024维、last pooling、客户端L2。程序、四个动态库和权重均按 `knowledge/embedding-runtime-lock.json` 及模型声明核对。CPU启动器为 `serve/embedding_service.py`：

```bash
.venv/bin/python serve/embedding_service.py \
  --binary /home/cloudia/.cache/rtlagent-embedding/runtime/build/bin/llama-server \
  --model /home/cloudia/.cache/rtlagent-embedding/models/Qwen3-Embedding-0.6B-Q8_0.gguf \
  --check-only
```

去掉check-only后前台监听127.0.0.1:8020。云端程序路径为 `/root/rtl-rag-v29-20261028-r1/dev/optimization-v29/portable/bin/llama-server`，权重为 `/root/rtl-rag-models/Qwen3-Embedding-0.6B-Q8_0.gguf`。使用已配置Python3.12环境，不替换正在运行的生成服务。

## 回退与交接

原rc2最终交付归档仍在 `dev/optimization-v41/`。回退时隔离解包并使用它自己的资产和实现锁；也可以使用off或旧32张诊断配置。正式比赛模型申报占位字段仍需提交阶段单独填写。

本批工作安排：[第42批](2026-10-29-rag-batch42-expansion.md)。本地真实embedding扩展查询证据在 `dev/optimization-v43/results.json` 和修订后 `dev/optimization-v43/rc3-1/results.json`；初始跨方法误准入保留原件。云端完成、成本和处置结论以独立审计文件为准。
