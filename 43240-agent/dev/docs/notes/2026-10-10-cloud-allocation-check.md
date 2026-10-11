# Proposal 修订期间的云端分配检查

| 项目 | 内容 |
| --- | --- |
| 类型 | 环境检查记录，不是模型评分实验 |
| 状态 | 已归档；该次检查已结束，资源不足，未分配成功 |
| 日期 | 2026-10-10，Asia/Shanghai；检查摘要保存于 21:30 |
| 来源 | 本次 `cloud.py` 凭据检查、启动任务及最终状态查询的实际返回 |
| 工作区版本 | `d4ca06e`；另有 proposal 文档改动与用户原有未跟踪实验记录 |
| 关联提案 | [RTL Agent proposal](2026-10-10-rtl-agent-proposal.md) |

用户已授权在能够分配远端实例时做适量测试。本次使用更新后的 `remote.env`，没有输出 Cookie、API key 或 SSH 私钥，也没有修改该文件。

## 归档说明（2026-10-11）

本页仅记录 10 月 10 日这一次分配失败。下文“没有新增模型数据”和“下一次”的说明保留当时语境；后续已在 AutoDL 完成独立实验，见[Qwen3 实测汇总](2026-10-11-autodl-qwen3-results.md)。本页不据此改写为分配成功，也不把本次资源不足解释为模型失败。

当时按 48GB 前提提出的后续安排已不作为最新执行指令；AutoDL 本轮采用用户随后指定的 32GB 限额。原始检查摘要和清理结果保留。

## 检查与结果

1. 登录凭据有效，账号已验证，SSH 公钥已设置；开始时实例状态为 `not_found`。
2. 为这次小规模诊断启动本机防休眠，并申请一台实例。覆盖本次等待时间为平台就绪最多 180 秒、SSH 最多 180 秒；计划实例就绪后使用 45 分钟看门狗上限，不沿用配置中的 250 分钟。
3. 启动任务 `edc357e4-13ad-4367-b7b1-0eae6ebe171b` 从 `running` 进入 `failed`，错误码为 `resource_capacity_insufficient`。平台说明为：`No matching Node has enough free CPU, memory, and GPUs for this launch`。
4. `cloud.py` 在失败路径调用销毁；随后再次查询，确认 `not_found`、`ready=False`，无运行实例。
5. 停止本次防休眠进程。没有进入 SSH、权重下载、推理服务启动或模型测试阶段。

启动命令如下；它是本次环境操作的记录，不是自动重试任务：

```bash
RC_READY_TIMEOUT=180 RC_SSH_TIMEOUT=180 \
  python3 43240-agent/dev/tools/remote/cloud.py up --max-minutes 45
python3 43240-agent/dev/tools/remote/cloud.py status
```

本次只尝试分配一次，没有持续轮询申请，也没有创建后续自动任务。
摘要保存在 `dev/runs/20261010-proposal-cloud-check/summary.json`，依据本次工具返回整理，不冒充原始 API 响应文件。

## 对 proposal 的影响

- 目前没有新增 Qwen3 分数、耗时、显存或思考模式对比数据；提案中的历史数字仍保持历史证据标识。
- 分配失败说明这次请求没有获得足够平台资源，不说明 Qwen3 或项目代码不可运行，也不说明平台会持续缺货。
- 近期实验按用户明确的初赛 48GB 条件设计；不因未测试而假定 32GB 限制下的表现。
- 下一次资源可用时，从固定 Qwen3-8B 的小批生成诊断开始，不对占位 `repair_loop` 做默认优化或跑分背书。
