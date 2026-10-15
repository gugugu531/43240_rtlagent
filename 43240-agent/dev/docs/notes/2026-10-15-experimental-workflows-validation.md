# 第四批实验工作流接入验收

日期：2026-10-15。类型：验证记录。状态：本地实现与 PR 材料准备，不推送、不发布 PR；无模型性能结论。

## 范围和来源

- 用户认可 [阶段计划](2026-10-15-experimental-workflows-plan.md)，并要求保留自己的实验策略，不把队长方案 A 当成唯一工作流。
- 适配基线：`bccfe4766b3f797a1f4a9561777abedb6cc7fc0f`，包含队长对第三批的证据和未知观察修补。
- 分支：`feat/experimental-workflows-20261015`；独立 Windows 副本 `pr-submissions/20261015-experimental-workflows/`。
- 实现接口与限制见 [可选实验工作流](../design/experimental-workflows.md)，本记录不重复字段表。
- 所有验证使用固定假模型、localhost 测试服务或本机 Vivado 2026.1，无商业 API 调用、云 GPU 和官方判定反馈。

与旧第四批补丁不同：移除旧 policies 依赖，复用受管理上下文、不可变检查证据、token 账本和主线检查点。
三个实验入口共用方案 A 的首稿消息与提取，选择策略独立。实际共用一份首稿须重放同一个检查点；不是独立调用三次模型就算配对。
正式 baseline 请求和提取不同，不能混作官方 baseline 等价实验。

## 提交前验收

本地日志均在 WSL 原生目录：
`/home/dev/projects/AMD_SocChina_2026/43240-agent/dev/runs/pr-fourth-20261015/`。
测试源码取自上述基线加本批明确差异的隔离快照，不直接运行原实验脏工作区。

| 运行 | 结果与范围 | 原始记录 |
| --- | --- | --- |
| `source-NPsh2U` | 全量 325 项：315 通过、9 项可选真实工具跳过、1 项失败；提交包检查 `errors=[]` | `test.log`、`submission.log` |
| `source-eJLgk0` | 新增 4 项真实 Vivado 集成全部通过 | `test.log` |
| `source-R6h3Gh` | 前两批专项 45 项全部通过，含 5 项真实 Vivado | `test.log` |
| `source-bxGrG3` | 未修改基线对照：监督专项 6 项中 5 通过，1 项与本批相同失败 | `test.log` |

新增 30 项离线集成测试在全量中全部通过，覆盖注册、首稿请求、2/3/4 次上限、零调用真值表、计划失败、编译修复后自测、
属性回退、端口变化、未知样本、综合失败保护、共用首稿扣账、已有 A0 检查点继续自测和三个入口脱离 dev 的运行。
提交前这次全量不是全绿，不能把当时运行写成“所有测试通过”；最终生产代码复验见文末后补记录。

四项真实工具集成验证：

1. 公开真值表反例触发修复，新稿完成相同自测和综合后才选中。
2. 编译失败修复成功后，先功能自测，再综合。
3. 把错误异步复位修正为同步复位，基于观察到的保持属性反例，而不是模型投票。
4. 模型末态预测错误时，复位探针仍使用实际观察前态；修正稿可以改善独立属性，但模型假设仍失配时保留该事实、以 stopped 结束，不宣称完整功能通过。

全量中跳过的 9 项真实工具测试，已在上述两个专项中分别启用并全部通过；不把专项与全量相加伪造独立测试数量。

## 已知失败和保留的历史

`test_http_small_deadline_bounds_blocking_model_without_five_second_floor` 的 `arrived.is_set()` 断言失败。
同环境、未修改的基线 `bccfe47` 也失败；不能据此断言具体根因，也不能承诺短截止链路完全稳定。
本批未改该测试、HTTP 服务、Supervisor 或时间断言；保留问题供独立排查，不掩盖或降低验收条件。

- 首次新专项 `source-saP7rq`：19 项，包含多个测试夹具预期错误（源码尾换行、工具组没有功能证据却期待修复）；后续修正新测试的预期，未改已有断言。
- 第二次新专项 `source-dGGp4Y`：19 项，剩下首次请求比较误包含实际剩余时间导致的 timeout 差异；改为比较真实 HTTP payload，继续验证采样一致。
- 扩展专项 `source-UhVWzU`：28 项全部通过。
- 首次真实集成 `source-QOhipI`：3 项，复位修复已经完成，但新测试误期待反例来源为 reset literal；实际是 observed registered hold。
  后续明确记录属性来源和输入历史，并校验真正的保持关系反例，新增错误末态预测反例。
- 首次全量 `source-eeSoSo`：324 项，315 通过、8 可选跳过、上述短截止项失败；包检查通过。

实现过程中另补强：只有功能检查完成、且所需综合有有效通过证据的新稿才能参与相应替换；
已有 lint 通过稿不能因为综合代码错误退出候选集合后绕过属性保护。规格组的纯综合代码错误和纯输出警告不强行修复替换。

## 复验和后续

在 Linux 原生源码副本的 `43240-agent/` 下：

```bash
python3 -m unittest discover -s dev/tests -p 'test_experimental_workflows.py' -v
RUN_VIVADO_TESTS=1 python3 -m unittest discover -s dev/tests -p 'test_experimental_vivado.py' -v
python3 -m unittest discover -s dev/tests -p 'test_*.py' -v
python3 dev/tools/submission.py
```

本地辅助脚本 `pr-submissions/check-experimental-workflows.sh` 保存了独立快照和全部日志，不进入参赛包或本批 PR。
真实工具需要安装环境和 `VIVADO_BIN`。隔离打包与新入口 smoke 在新增离线测试中执行，工具缺失时应如实回退。

下一步由用户检查 PR 材料和队长审核边界；第五批再做首稿/最终评分、保住/修好/改坏、重复采样及正式题集比较。
本批测试既不证明 Qwen3-8B 性能，也不证明实际题集增益；没有训练权重、难度自评或额外思考预算策略。

## 后补：最终生产代码复验

2026-10-15，生产代码已本地提交为 `5d5e1eb5c026db120d6bc8f0c208d7bface1a758`。
从该提交直接归档到独立原生目录，不再叠加工作区补丁，运行同一全量命令和原有全部断言。

- 运行编号 `source-HH1qix`：325 项，316 通过、9 项可选真实工具跳过、0 失败；提交包检查 `errors=[]`。
- 全量跳过的 9 项已在 `source-eJLgk0` 和 `source-R6h3Gh` 的真实工具专项分别启用通过。
- 原有短截止测试本次通过；未修改该测试或放宽条件，不代表此前重复失败已查明根因或已修复。
- 前述失败、未修改主线对照和原始日志保留。此后补只记录验收，不改变运行代码。
- 本地提交和补丁备份完成；尚未推送、创建 PR 或切换默认入口。
