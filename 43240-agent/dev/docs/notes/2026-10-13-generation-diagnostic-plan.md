# 五道退步题：thinking 与采样参数诊断

类型：实验计划与离线分析。日期：2026-10-13。状态：用户已授权执行；运行状态以会话记录为准。

## 范围与验收

先离线读原始响应，再依次运行三个设置；不改正式 workflow、提示模板、提取器、技能或模型。
开发网关统一覆盖两组的生成参数，官方 baseline.py 和 run_baseline.sh 保持字节不变。
网关函数 `apply_profile(body, profile)` 只改声明的生成字段；请求前落盘原始/实际请求及哈希，
响应后保存原文。普通网关无 profile 时仍逐字节转发，传输重试不改变实际请求字节。
接口为 `model_gateway.py --profile <name> --audit-dir <dir>`，没有审计目录则拒绝实验模式。

| 顺序 | 网关 profile | thinking | temperature / top_p | 其他 |
| --- | --- | --- | --- | --- |
| 1 | think-on-greedy | 开 | 0 / 1 | seed=20261013 |
| 2 | think-off-greedy | 关 | 0 / 1 | 同一 seed |
| 3 | think-on-sampled | 开 | 0.6 / 0.95 | top_k=20、min_p=0、同一 seed |

第一对只改变 thinking 开关。第三组与第一组比较的是完整采样配方，不是单独 temperature 的因果效应。
每组均为 5 题 × Agent/baseline × 1 样本，共 30 次求解；workflow 的额外生成/修复调用仍按原规则。
新 greedy 组也重新测量，不把旧结果当作本轮同时对照。首轮只做诊断，不启动 E1/E2 或扩大题集。

输出上限每次 8192 tokens；单次请求上限 300 秒（Agent 仍受剩余预算裁剪），
每题进程总预算 360 秒，Agent 预留 20 秒；求解与评分并发均为 1。不得增加输出预算“挽救”某组。
Agent 与 baseline 各自提示固定不变，但两者的提示本来不同；因此仍是完整系统对比，不是 Node 消融。
分支产生的第二次提示可能因反馈不同而不同；重点另核对同一题同一模式的第一次请求 messages 哈希。

验收：网关单元测试覆盖普通透传、实验字段、审计、重试；分类测试覆盖思考/RTL 截断、完整模块和错误模块。
运行前核对原实验正式源码哈希和题面输入；每组检查模型/判定工具错误，记录全部失败，不选择性重试。
记录 L0/L1/L3、完整最终 RTL、截断、tokens、求解时间；检查同一模式首个提示哈希跨组一致。
所有新结果独立保存，不能替换旧 quick-34 的五道题成绩。

## 离线观察

派生报告：[五道退步题离线诊断](../../runs/20261013-generation-diagnostic-offline/README.md)，
机器可读证据为同目录 `report.json`。运行命令：

```bash
python3 dev/tools/generation_diagnostic.py offline \
  --combined dev/runs/20261013-105000-autodl-qwen3-8b-a-fixed-quick34-resume-4e464cbc/combined \
  --out dev/runs/20261013-generation-diagnostic-offline
```

输出目录已存在，工具拒绝覆盖；复核时指定另一个新目录。

首个会话 `20261013-generation-diagnostic-five` 在启动预检查中因 tuple/list 的 JSON 往返比较差异
提前结束，未发出模型请求，也未跑任何题；模型随清理立即停止。此记录保留为 incomplete，
不是某道题失败后的选择性重试。已改为规范化 JSON 哈希比较并增加回归测试，且将再次预检查前移到 GPU 启动之前。
实际三组实验使用新会话 `20261013-generation-diagnostic-five-retry1`，不覆盖失败会话。

验证：全量测试 164 项中 162 项通过、2 项跳过；另新增网关证据匹配的 3 项测试均通过。
`submission.py` 检查无错误；shell 语法、`git diff --check` 与 baseline/example 字节比较通过。
新会话于 11:51:46 JST 启动，13:11:46 提醒、13:21:46 本地自动停止；
远端保护于 11:52:02 JST 安装，独立截止约 13:22:01 JST。
远端环境版本与既有运行一致，并重新记录 5 个权重分片及 4 个配置/tokenizer 文件的 SHA256。
实际运行汇总见[三组对照报告](../experiments/20261013-generation-diagnostic-five-retry1.md)。

来源：`20261012-225403-autodl-qwen3-8b-a-fixed-quick34-460c1d2a` 与
`20261013-105000-autodl-qwen3-8b-a-fixed-quick34-resume-4e464cbc/combined`。

- Prob101_circuit4、Prob109_fsm1、Prob115_shift18：Agent 两次均 length / 8192 tokens，
  原文 `<think>` 未闭合，没有可用最终 RTL。属于思考截断，而非已证明的提取器漏提取。
- Prob138_2012_q2fsm：第一轮同样思考截断；第二轮产出完整模块，但 `output z` 在 always 中赋值，
  Vivado 报 VRFC 10-1280。第二轮是重新生成而非已有候选修复，已消耗唯一补救机会，最后保留失败候选。
- Prob105_rotate100：完整代码并通过综合，官方功能测试失败。只对照题面和已有 solution.v：
  ena=01 本应右旋却实现左旋；ena=10 本应左旋，生成式 `{reg_data[1], reg_data[99:1]}`
  又错误复制 bit1 而丢弃 bit0。这里没有手工修补代码，也没有将评测反馈加入求解提示。
- 旧 baseline 未保存原始模型响应。其 trace 和最终代码可核对，但不能断言查看了其思考原文；
  新网关审计补齐两组响应证据。离线工具会明确标记 raw_response_available。

## 方法来源与限制

Qwen3 默认开启 thinking；vLLM 的 reasoning-parser 只是输出解析器。关闭使用
`chat_template_kwargs.enable_thinking=false`，不追加 /no_think 改动提示。
见 [vLLM 0.11.0 文档](https://docs.vllm.ai/en/v0.11.0/features/reasoning_outputs.html)。
Qwen 官方不建议 thinking 使用贪心解码，并给出第三组采样配方，见
[固定模型提交的说明](https://huggingface.co/Qwen/Qwen3-8B/blob/b968826d9c46dd6066d109eabc6255188de91218/README.md)。

这五题是按既有失败选择的开发诊断集，不能代表完整 quick-34 或 VerilogEval 的泛化能力。
固定 seed 不保证所有 GPU 实现绝对可复现；采样组目前一次测量不能当作稳定性结论。
采样组由开发网关覆盖官方 baseline 的固定参数，因此必须标为“开发采样对照”，
不能声称为原封不动的官方 baseline 参数成绩；没有修改 baseline 文件或官方判定器。

## 资源保护

运行放入 systemd 用户服务，保留本机阻止休眠和 SSH relay 自动重连。熄屏可继续，关机或断网不能保证继续。
本轮保守限制为 90 分钟，80 分钟桌面提醒；远端独立 watchdog 在本机断网时仍停止 vLLM。
正常结束立即停止模型、关闭隧道、撤销保护。停止 vLLM 只释放 GPU，不等于 AutoDL 平台关机停计费。
不重置或隐瞒已有会话的时间；本轮无旧实验运行，保护从本次启动计时，平台累计剩余额度仍需用户网页核对。
