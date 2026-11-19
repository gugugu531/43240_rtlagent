# 工作流实时事件

在求解子进程中设置环境变量 `RTLAGENT_LIVE_EVENTS=1`，记录器会在本题输出目录创建 `live.jsonl`。每一行都是一个完整的 JSON 对象，写完立即刷新。在 basic 和 full 两种记录等级下，实时文件的位置和格式相同。`AGENT_RECORD_ROOT` 控制 full 记录的位置。

```bash
RTLAGENT_LIVE_EVENTS=1 ./run.sh /tmp/my-public-task /tmp/my-run
```

## 事件格式

每行都有版本号 `v=1`、Unix 秒时间戳 `ts` 和事件类别 `type`。

| 类别 | 主要字段 | 含义 |
| --- | --- | --- |
| `graph` | `workflow`、`entrypoint`、`nodes`、`edges` | Burr 实际建成的图。节点包含静态别名 `id`、标题 `label` 和可选的 `role`。边给出 `from`、`to` 和转移条件 `condition`。 |
| `node_start` | `id`、`node`、`label`、`role`、`previous` | `node` 指向图中的别名。`id` 标识本次执行。循环再次进入同一节点时会得到新的 `id`。`previous` 指向上一次实际执行的节点实例，第一步为 `null`。 |
| `node_end` | `id`、`status`、可选的 `elapsed_s` | `finished` 表示节点执行返回，`failed` 表示节点执行失败。验证结果在对应节点的详情中。 |
| `detail` | `id`、`label`、`kind`、`value`、可选的 `status` | `id` 指向详情所属的执行实例。在节点外记录时为 `null`。`text` 和 `code` 的值为字符串，`json` 的值为对象或数组。 |
| `call_context` | `id`、`call_id`、`purpose`、`messages` | 生成请求交给传输层时记录。消息按发送顺序保留角色、正文和关联的工具调用。连接或传输随后仍可能失败。 |
| `call_response` | `id`、`call_id`、`purpose`，以及响应带有的 `content`、`finish_reason`、`tool_calls`、`reasoning_content`、`reasoning` | 对应客户端收到并解析的那条模型回复。正文可以缺失、为 `null` 或为空字符串。独立推理字段按模型服务的实际响应记录。 |
| `run_end` | `status`、`submission_mode`、`candidate_id`、`stop_reason`、`elapsed_s`、`calls`、`tokens_in`、`tokens_out` | 整轮运行的结束状态、实际交付候选和资源用量。后端未提供的 token 数保留为 `null`。 |

读取方按行处理完整记录。用 `id` 找到工作流节点的这一次执行，再按 `call_id` 关联该次调用的上下文、生命周期及回复。工作台按实际执行的工作流节点绘图，模型调用的起止和结果可在节点详情中查看。`call_context` 和 `call_response` 保留在事件接口中。新旧 v1 日志共用同一界面。进程被强行终止时，末行可能只写了一部分，也可能尚未产生 `run_end`。运行完成和检查表通过各有独立字段。行为检查的 `compared_bits` 给出实际比对的位数，`unknown_bits` 给出未知位数。未运行、不可用、部分通过和失败各保留自己的状态。

详情中绝对值超过 `2^53 - 1` 的整数使用十进制字符串表示，浏览器可以精确显示 64 位和 256 位信号及其掩码。

## RTL 工作流展示的证据

- 策略节点展示检查方法、选择原因、关注点和选中的技能。作者节点另记入实际送入本次请求的技能。
- 每个候选有完整的 RTL、候选编号、来源调用和内容摘要值。改稿会记录父候选、子候选和代码是否发生变化。
- 接口检查、编译与展开（lint）、综合分别给出结果、候选身份和公开诊断。结构汇总列出本轮尚未执行的工具。
- 注册工具的起止事件用 `value.origin` 记录调用入口。`framework` 来自工作流的 `ctx.call`，`model` 来自工具分派入口 `ctx.dispatch`。模型回复中的 `tool_calls` 只表示请求，工具是否实际执行以工具事件为准。
- 独立检查表按测试点记录解释、施加的输入、采样阶段和期望值。执行后，各点记录结果、实际比较的位数、未知位和差异。在候选内容、检查表、采样计划和采样批次一致时，详情还展示每个显式比较的期望值及实测值。实测值中的 `known` 掩码标识已知位。
- 作者的提交、改稿、请求复核和检查员的复核决定各带原始简短理由。最终交付给出候选身份、交付模式、结构及行为检查状态。

## 给新工作流添加详情

通过 `agent.kit` 注册的新工作流会自动获得图结构、静态分支、执行顺序和节点生命周期。节点装饰器可以用 `label` 和 `role` 设置显示标题与角色。省略标题时使用节点别名或内置实现的中文标题。节点内用 `ctx.record.live_detail` 展示要公开的业务数据。

```python
from agent.kit import Ctx, State, node


@node("count_inputs", reads=["ports"], writes=["input_count"], label="统计输入", role="接口分析员")
def count_inputs(ctx: Ctx, state: State) -> State:
    names = [p["name"] for p in state["ports"] if p["direction"] == "input"]
    ctx.record.live_detail("输入端口", {"names": names, "count": len(names)})
    return state.update(input_count=len(names))
```

`live_detail(label, value, *, kind=None, status=None)` 会将字符串显示为文本，将对象和数组显示为 JSON。展示代码时显式传入 `kind="code"`。扩展作者应逐项选取公开内容。使用框架模型客户端的新工作流会自动生成调用的消息和回复事件。记录器过滤公开副本中的凭据及宿主路径。关闭实时记录时，记录器直接返回。展示文件写入失败时，求解继续执行。
