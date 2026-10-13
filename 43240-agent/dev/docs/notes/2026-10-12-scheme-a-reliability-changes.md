# 方案 A：连接恢复、错误分类和公平对比

类型：实现与验证记录。日期：2026-10-12。状态：代码验证通过；2026-10-13 补跑完成，34/34 题有效配对。

## 本轮变化

- `dev/tools/remote/tunnel.sh` 用 systemd 用户服务管理 SSH/socat 转发和本地 HTTP
  gateway，进程退出后 3 秒重启。gateway 对网络传输异常在 270 秒内重试相同请求字节，
  两组共用；每次重试写入 journal，上游 HTTP 错误直接透传。
- `agent/services/vivado.py` 识别已实际遇到的 `VRFC 10-1280`、`10-9336`，并保留
  环境错误的优先级。用上一轮 8 次 lint 失败的摘要回放，全部归类为 `code`。
- `evidence_repair` 在所有候选都检查失败时保留完整候选并记录
  `failed_check_fallback`；已有检查结果不变。修复回复不完整或模型调用失败时，已有候选
  仍然保留。原有 `repair_loop` 的严格筛选规则不变。
- 方案 A 默认参数改为 8192 tokens、temperature 0、top_p 1、单次模型上限 300 秒，
  对齐原始 baseline；本题总预算仍为 360 秒并预留 20 秒。
- 开发侧汇总排除已记录模型调用失败的样本。双方完整有效的配对才计算 gain；原始
  judge 结果保留，官方计分器和 baseline 文件不变。
- 源码快照增加开发工具 shell/YAML 与方案 README，便于重放运行条件。

## 验证

运行命令：`python3 -m unittest discover -s dev/tests -p 'test_*.py'`。
145 项测试，143 项通过、2 项跳过。另运行配置回归、`submission.py`、shell 语法检查、
`git diff --check`，并比较两个 baseline 文件与赛事原始 example 的字节一致性，均通过。

真实恢复验证：东京时间 22:49:38 主动终止 relay 主进程；22:49:41 systemd 自动重启，
`NRestarts=1`。HTTP 回归覆盖中途中断后以相同 POST 字节重试、恢复超时返回 502、
上游 503 直接返回。

单题运行：`20261012-225021-autodl-qwen3-8b-a-fixed-smoke-57c8efca`。
`ex03_lfsr8` 的 agent 与 baseline 均为 L3，无模型调用失败。

完整运行：`20261012-225403-autodl-qwen3-8b-a-fixed-quick34-460c1d2a`。
使用同一个自托管 Qwen3-8B 服务；34 题、双方各 1 样本、求解和评分并发均为 1。
本轮于东京时间 22:49:41 启动会话，03:19:41 提醒、03:29:41 自动暂停；远端独立
保护也已安装，正常完成会提前停止 vLLM。

2026-10-13 00:32:45（东京时间）按用户要求安全暂停。已保留 58 个有效评分样本，剩余
5 题双方共 10 项需要补跑；本地服务和旧定时器均已停止，远端 vLLM 已退出、GPU 显存为
0 MiB。远端 watchdog 撤销时的 Python 路径问题已手动处理，下次启动前需修正。
本次不宣称 full quick-34 完成，完整暂停记录和补跑配置见
[实验记录](../experiments/20261012-225403-autodl-qwen3-8b-a-fixed-quick34-460c1d2a.md)。

后续更新：2026-10-13 10:50:00—11:19:53（东京时间）完成剩余 5 题共 10 个样本。
合并前核对正式代码、有效配置及题目输入一致，完整 68 个样本的模型和判定工具错误均为 0；
Agent 系数均值 0.5294、baseline 0.5647，gain 约 0.9375，尚未优于 baseline。
远端 Python 路径问题已修正并实际验证保护器启动/撤销；GPU 已释放，平台实例仍需用户网页关机。
本次补跑工具和合并工具均在开发区，没有改正式求解策略。
完整报告见[34 题合并结果](../experiments/20261013-105000-autodl-qwen3-8b-a-fixed-quick34-resume-4e464cbc.md)。

## 解释范围

本轮对齐采样参数后，提示模板和提取策略仍不同，因此它比较的是两套完整求解方式，不能
单独归因为某一个 Node 的增益。每题一个样本也不能代替多次重复的稳定性实验。

网络中断后的 POST 重试可能重复远端推理，所以耗时分析要同时检查 gateway 日志。
`source_complete=false` 来自快照对开发工具 `_common.sh` 和 `serve/README.md` 中
占位 key 文本的脱敏；正式 `agent/`、baseline 和 `serve/vllm.sh` 的代码快照未受影响。
工作区仍为 dirty，各文件 SHA256 已保存在运行目录的 `source/manifest.json`。
