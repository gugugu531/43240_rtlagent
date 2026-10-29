# RAG rc4.4 第二批 restricted 运行说明

`rag-catalog-v3-rc4.4` 是第二批十卡晋升后的本地候选。129 张目录卡中有 32 张 `legacy_policy`、18 张 `restricted`、53 张 `shadow` 和 26 张 `mechanical_only`。本轮新增以下十张受限卡：

- `v8-lfsr-feedback-seed`
- `v8-packer-valid-count`
- `v8-pipeline-valid-alignment`
- `v8-ram-port-write-mode`
- `v8-result-backpressure-retention`
- `v8-serializer-snapshot`
- `v8-stack-boundary-guards`
- `v9-public-am-pm-phase`
- `v9-public-carry-lookahead-composition`
- `v9-public-division-remainder-invariant`

所有新增卡只允许在 `pre_generation` 阶段接入。题面先通过卡片专属公开合同谓词；检索只提供候选，不能覆盖准入。已知方法、冲突要求、信息不足、明确不适用、卡片篡改或 embedding 服务失败都会安全返回空结果。默认配置没有改变。

`dev/optimization-v54/gate-results.json` 保存晋升前的 10/10 门禁结果。每张卡都完成正向、已知、冲突、信息不足、不适用、篡改、tokenizer、BM25 与真实 dense 路由检查。模型效果证据复用 v49 的同卡版本双臂结果；v49 与 v51 的 prompt、interface、target、reference、adjacent 和 bench 完全一致，十张均为 `both_pass`。本轮没有新增生成调用。

晋升后的 `dev/optimization-v54/post-promotion-smoke.json` 使用两台主机的 `127.0.0.1:8020` 服务重新检查实际运行状态。十张卡在 BM25 和 dense 两条路径都只接纳目标卡：BM25 排名为 1–5，dense 全部排名第一。两台 embedding 服务保持回环监听，未重启，在线生成配置没有切换。

卡片投影文本没有变化，129 个向量全部复用；文档绑定、目录、规则、实现及向量锁已更新到 rc4.4。全量 139 项单元测试通过。当前工作区没有提交或推送；已暂存的 rc4.3 仍是独立检查点，rc4.4 改动位于未暂存工作区。

后续若继续按十张一批推进，应先选取 active 版本有有效双臂结果、v49/v51 夹具完全一致且 BM25/dense 均位于 top-5 的卡。每张仍须补独立的公开合同谓词和五类拒绝检查。任何题面路由排名超过 top-5、模型版本不一致、夹具变化或出现退步的卡继续保持 shadow。
