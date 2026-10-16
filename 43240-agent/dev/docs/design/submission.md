# 赛事要求与提交核对

核对日期：2026-10-16。来源为主办方提交 `9df176717fec16751d02f4fb5c67dbd40a22fc15`。
本地根目录、docs、selftest、example 是受保护的旧快照，不代表最新赛事规则。
当前要求以[上游 README](https://gitee.com/Vickyiii/rtlagent2026/blob/9df176717fec16751d02f4fb5c67dbd40a22fc15/README.md)、
[评分细则](https://gitee.com/Vickyiii/rtlagent2026/blob/9df176717fec16751d02f4fb5c67dbd40a22fc15/SCORING.md)和
[封存说明](https://gitee.com/Vickyiii/rtlagent2026/blob/9df176717fec16751d02f4fb5c67dbd40a22fc15/docs/SUBMISSION.md)为准。

## 时间与交付

以下均为北京时间 2026 年：

| 时间 | 要求 |
| --- | --- |
| 10 月 16 日至 30 日 | 验证窗口，在 Radeon Cloud 验证并完成 Gitee 邀请 |
| 10 月 31 日 10:00 前 | 方案进入 Gitee 私有仓库默认分支；投题服务就绪并报送端点 |
| 10 月 31 日 10:00 | 主办方拉取默认分支封存，随后开始按轮投题；此后推送不计入 |
| 11 月 4 日 18:00 前 | 大赛系统提交设计报告和与封存一致的 Gitee 仓库链接 |

赛事仓库和独立方案目录名为 `43240_rtlagent`；当前开发目录 `43240-agent/` 不必改名。
用 `dev/tools/submission.py --stage /tmp/43240_rtlagent` 导出明确文件清单，不能把开发仓库整体作为方案包。
Gitee 仓库必须为私有，邀请 `Vickyiii`（`daisycw@126.com`），授予只读或以上权限，建议 10 月 30 日前完成。
邀请、令牌、端点报送及系统提交均需单独办理；向当前 GitHub 开发仓库推送 PR 不等于赛事封存。

## 评分与题集

能力项为题集得分乘 30。增益项采用 `g=(方案−基线)/(1−基线)`，
得分为 `40×min(g/0.6,1)`，g 不大于 0 时为 0；基线为 1 时增益项计满分，基线为 0 时照常计算。
倍数只作诊断，不能继续用旧的 log 倍数公式计算现行增益分。

统一实验在配对有效样本覆盖一致时输出 `gain_g`、`gain_score` 与 `gain_ratio`；兼容字段 `gain`
仍是旧的倍数诊断。模拟投题客户端使用开发区的 `scoring.py`，复用官方等级聚合，不改动判定链路。
旧 `selftest/score.py`、历史 overview 工具与已保存实验仍使用旧口径，不能据此报现行分数。

上游建议排除 11 道 VerilogEval 缺陷题，按 145 题统计，并声明具体分母；当前题集与历史实验
不会自动删题或重算。缺陷清单及适用边界见[题集说明](datasets.md)。pass@1 用于计分，pass@5 仅诊断。

## 封存前仍需完成

- 确定正式模型、固定公开权重地址与 revision，完善 MODEL.md、manifest.json 和报告。
- 替换官方基础镜像占位值，验证干净容器中的 start.sh、run.sh 和 baseline；断网运行，不下载依赖或权重。
- 在目标单卡验证不超过 32 GB 的实际显存峰值、连续请求、Vivado 授权与完整链路。
- 与主办方核实 baseline 版本：本地受保护脚本不含上游新 strip_think，不能擅自改动或声称已字节对齐最新版本。
- 准备最终报告的真实结果和失败分析；封存时 REPORT.md 可为草稿，报告按系统最终提交为准。

`xsim` 与 `synth_design` 在上游说明的 Vivado 2026.1 环境中需要授权，`xvlog` 与 `xelab` 不需要；
授权失败应保留为环境错误，不能将缺失的仿真结果当作通过。
