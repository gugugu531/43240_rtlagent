# 11 题生成设置对照：执行计划与验收

类型：运行记录。日期：2026-10-13。状态：中断后的三项补跑完成，44/44 项有效评分。
结论见[11 题完成记录](2026-10-13-diagnostic-eleven-results.md)；以下保留启动、中断与恢复历史。

## 当前政策与补跑：取消整轮固定时限

用户本轮明确取消今后整轮实验的 5 小时等固定截止；以下原始 90 分钟保护属于历史设置，
不再用于本次补跑。单次请求 300 秒、单题 360 秒及 20 秒预留不变；正常完成、异常和手动停止
仍清理 vLLM 与连接。AutoDL 网页实例关机和余额不由这些脚本控制。

旧保护已在 14:32:53 JST 触发，旧会话记录 incomplete、采样组 cancelled；14:33:25 停止 vLLM，
14:38:21 JST 远端检查显存 0 MiB、利用率 0%，watchdog PID 文件不存在。不是收到新指令后主动暂停。
原采样组 22 次、推荐采样组 19 次已有有效评分，共 41/44 次；保留所有成绩，包括 L0/L1。
仅补 `Prob043_vector5/baseline`、`Prob058_alwaysblock2/agent`、`Prob058_alwaysblock2/baseline`。

恢复接口：`generation_resume.py prepare <新会话> --previous <旧会话>` 冻结原证据哈希和取消样本清单，
`verify` 拒绝源码、题面、原记录变化或非取消错误；`run` 只过滤统一 ExperimentRunner 的 SampleSpec，
不另写求解循环。完成后核对实际 profile、首次 messages 与原采样组一致，使用 combine_runs 合并
19+3 项，记录来源。中断时未收到响应的旧 baseline 请求单独保留，不伪造完成或计入成绩。

验收：取消样本选择与缺失/重复/模型失败保护测试、网关审计测试、原始文件哈希、正式源码与 baseline
字节检查、44 项完整配对验证、结束后的远端 GPU 检查。旧会话和旧报告不覆盖。

当前启动脚本通过 `autodl_session_limit.sh` 应用政策：`AUTODL_SESSION_LIMIT_S` 默认 0，
撤销遗留本地 timer 和远端 watchdog；只有未来用户明确要求时才设置正数重新启用。

补跑会话：`dev/runs/20261013-generation-diagnostic-eleven-resume1`；
[补跑后生成报告](../experiments/20261013-generation-diagnostic-eleven-resume1.md)。
14:43:25 JST 作为独立 systemd 服务启动，14:43:40 确认无整轮固定截止，
14:44:15 开始统一 runner 的 3 样本补跑；9 个远端模型/配置/tokenizer 指纹与原会话一致。
离线恢复与审计/合并测试共 24 项通过，原 baseline 字节检查及 shell 语法通过。

[下一阶段顺序](2026-10-13-after-generation-experiment-order.md)只写建议，本轮不自动启动 E1/E2。

14:48:44 JST 完成补跑和 44 项汇总；14:48:45 vLLM 停止，14:48:49 隧道关闭。
14:49:29 SSH 核实显存 0 MiB、利用率 0%、无 vLLM/watchdog；本地各项后台服务已停止，
无本地截止 timer。平台实例本身未关机。

## 已执行的检查与启动

全量单元测试 172 项中 170 项通过、2 项跳过；正式源码、题面哈希、baseline/example 字节对比、
shell 语法和 git diff --check 通过。远端 vLLM 0.11.0、PyTorch 2.8.0+cu128 与上一轮一致，
重新核对 9 个权重/配置/tokenizer 文件 SHA256 全部匹配。

会话：`dev/runs/20261013-generation-diagnostic-eleven`。
[当前生成报告](../experiments/20261013-generation-diagnostic-eleven.md)在每组开始/完成时更新；
state.json 保存设置顺序、已完成组及其原始 run 路径。

后台服务于 13:02:53 JST 启动；13:03:43 JST 模型就绪并开始原采样组。
首个实际请求已落审计，确认 enable_thinking=true、temperature=0、top_p=1、max_tokens=8192、
seed=20261013，messages 与客户端原请求一致。
本地 14:22:53 JST 提醒、14:32:53 JST 自动停止（北京时间 13:22:53 / 13:32:53）；
远端独立保护截止约 14:33:08 JST，正常完成会提前清理。

准备/复核命令（会话目录已存在，不要重复 prepare）：

```bash
python3 dev/tools/generation_sweep.py prepare dev/runs/20261013-generation-diagnostic-eleven \
  --config dev/configs/generation-diagnostic-eleven.yaml \
  --profiles think-on-greedy think-on-sampled
python3 dev/tools/generation_sweep.py verify dev/runs/20261013-generation-diagnostic-eleven
```

verify 只接受 prepared 会话；运行后请只读检查 state.json，不要将 running 状态改回 prepared。

### 运行中检查：14:19 JST

原采样组已完整结束并通过配对验证；推荐采样组运行中。14:17:45 JST 检查时已求解 29/44、
已评分 28/44；原采样组有 1 次网关传输重试后成功，原始 HTTP 响应均为 200。
重试可能重复上游推理，后续解释耗时和成本时必须保留该事实，不据此选择性删除样本。

发现本地单调时钟计时器显示的截止时间晚于原定墙钟时间，显示约 14:56:19 JST，
但远端独立 watchdog 仍约 14:33:08 JST 截止。尚未定位偏移原因，不宣称是 RTL 或模型故障。
14:19:52 JST 将本地两项保护改为带 Asia/Tokyo 时区的固定日历时间：14:22:53 提醒、14:32:53 停止，
恢复原定更早的截止，不延长远端保护，也不重启实验、改参数或触碰已完成结果。
正常清理仍会停止同名 timer，避免任务提前结束后留下会影响后续实验的保护器。

同期仅在独立 dev/knowledge 和新开发工具中建立知识卡片，21 项离线检索测试通过，
未调用模型或 Vivado；复核本轮冻结的正式源码、配置、题面及 profile 哈希仍一致。

## 本轮范围

使用[已冻结的 11 题](2026-10-13-diagnostic-eleven-plan.md)，依次运行两个预先指定设置：

| 顺序 | profile | thinking | temperature / top_p | 其他 |
| --- | --- | --- | --- | --- |
| 1 | think-on-greedy | 开 | 0 / 1 | seed=20261013 |
| 2 | think-on-sampled | 开 | 0.6 / 0.95 | top_k=20、min_p=0、seed=20261013 |

每组 11 题 × Agent/baseline × 1 样本，总计 44 次求解。不开 thinking-off 组，不启动不同 seed
重复、E1/E2 或 Ross；本轮只验证推荐采样是否在扩展开发集保住原有优势和稳定题。
沿用 evidence_repair、相同模型与各自提示、8192 输出 tokens、300 秒单次上限、360 秒单题预算、
20 秒 Agent 预留、求解与评分并发均为 1。Agent 的额外生成/修复仍按原规则决定。

旧五题测量不拼入本轮，新题集两组均从头完整运行。官方 baseline 文件不改；共享开发网关覆盖
实际采样，因此成绩属于开发参数对照，不能冒称官方固定 baseline 参数成绩。

## 开发工具的最小改动

`generation_sweep.py prepare <新会话目录> --config <配置> --profiles <有序设置>`
冻结配置路径、源码/题面哈希和设置顺序；run/verify 从 state.json 读取已冻结信息，不在中途变更。
仅允许已声明的 5/11 题配置；拒绝错误数量、额外样本、并发变化、不同预算或重复设置。
子进程清除可覆盖 YAML 的环境配置，但保留 Vivado PATH 等工具环境。

每组开始与完成时更新生成报告，明确“已完整汇总”的样本数；在途组的部分成绩保留在原始 run 目录。
收到停止信号时记录 incomplete，不把未结束组计入已完成表。
远端启动前再次核对 vLLM/PyTorch 版本与上一轮 9 个模型/配置文件的 SHA256。

验收：参数顺序、旧会话兼容、44 项报告、环境覆盖防护、两组审计匹配与错误停止测试；
正式源码与题面哈希、baseline/example 字节一致、shell 语法和 git diff --check。
每组完整有效才汇总，校验双方实际生成参数和首次 messages 哈希跨组一致，保留全部失败。

## 资源保护与解释边界

独立 systemd 后台执行，熄屏可继续；不能保证本机关机或长期断网后继续。
本轮最多 90 分钟，80 分钟提醒；远端 watchdog 独立停止 vLLM，正常完成提前清理。
这不是重置 AutoDL 累计额度；网页余额与关机计费仍需用户核对。

每题每组只有一次测量，11 题仍是有意选择的开发集。结论只用于决定是否值得进行不同 seed 的重复，
不替代 quick-34 验收或独立留出验证；本轮不直接采用新设置作为正式默认配置。
