# 赛事要求与提交核对

核对日期：2026-10-17。来源为主办方提交 `f7a8bd465c2a820e006c7a00ecc7df468974635b`。
本地根目录、docs、selftest、example 已按用户本次明确的同步请求原样更新至该版本，
之后仍作为主办方原始文件维护，不做队伍定制修改。
当前要求以[上游 README](https://gitee.com/Vickyiii/rtlagent2026/blob/f7a8bd465c2a820e006c7a00ecc7df468974635b/README.md)、
[评分细则](https://gitee.com/Vickyiii/rtlagent2026/blob/f7a8bd465c2a820e006c7a00ecc7df468974635b/SCORING.md)和
[封存说明](https://gitee.com/Vickyiii/rtlagent2026/blob/f7a8bd465c2a820e006c7a00ecc7df468974635b/docs/SUBMISSION.md)为准。

## 时间与交付

以下均为北京时间 2026 年：

| 时间 | 要求 |
| --- | --- |
| 10 月 16 日至 30 日 | 验证窗口，在 Radeon Cloud 验证并完成仓库协作者邀请 |
| 10 月 31 日 10:00 前 | 方案进入 Gitee 或 GitHub 私有仓库默认分支；投题服务就绪并报送端点 |
| 10 月 31 日 10:00 | 主办方拉取默认分支封存，随后开始按轮投题；此后推送不计入 |
| 11 月 4 日 18:00 前 | 大赛系统提交设计报告和与封存一致的仓库链接 |

赛事仓库和独立方案目录名为 `43240_rtlagent`；当前开发目录 `43240-agent/` 不必改名。
用 `dev/tools/submission.py --stage /tmp/43240_rtlagent` 导出明确文件清单，不能把开发仓库整体作为方案包。
默认模式检查结构、Docker COPY、四个 Shell 入口执行权限和固定官方 baseline 摘要，并可运行独立 mock smoke。
正式封存声明另用 `--release` 检查，支持与 `--stage` 同用；声明检查失败不会导出。
该模式核对固定 revision、MODEL.md 来源和版本、显存声明、服务版本及镜像占位项，
不证明 URL 公开可访问、GPU 测量有效或基础镜像来源；当前四类占位信息仍使检查失败。
两个平台任选一个，仓库必须为私有；Gitee 邀请 `Vickyiii`（`daisycw@126.com`），GitHub 邀请 `vickyiii`，授予只读或以上权限，建议 10 月 30 日前完成。
邀请、令牌、端点报送及系统提交均需单独办理；向当前 GitHub 开发仓库推送 PR 不等于赛事封存。

## 评分与题集

能力项为题集得分乘 30。增益项采用 `g=(方案−基线)/(1−基线)`，
得分为 `40×min(g/0.6,1)`，g 不大于 0 时为 0；基线为 1 时增益项计满分，基线为 0 时照常计算。
倍数只作诊断，不能继续用旧的 log 倍数公式计算现行增益分。

统一实验在配对有效样本覆盖一致时输出 `gain_g`、`gain_score` 与 `gain_ratio`；兼容字段 `gain`
仍是旧的倍数诊断。模拟投题客户端使用开发区的 `scoring.py`，复用官方等级聚合，不改动判定链路。
`selftest/score.py` 已原样更新至现行公式；历史 overview 工具与已保存实验仍保留旧口径，不能据此报现行分数。

上游建议排除 11 道 VerilogEval 缺陷题，按 145 题统计，并声明具体分母；当前题集与历史实验
不会自动删题或重算。缺陷清单及适用边界见[题集说明](datasets.md)。pass@1 用于计分，pass@5 仅诊断。

## 封存前仍需完成

- 确定正式模型、固定公开权重地址与 revision，完善 MODEL.md、manifest.json 和报告。
- 替换官方基础镜像占位值，验证干净容器中的 start.sh、run.sh 和 baseline；断网运行，不下载依赖或权重。
- 在目标单卡验证不超过 32 GB 的实际显存峰值、连续请求、Vivado 授权与完整链路。
- 官方 baseline 已字节对齐 `f7a8bd4`，包含 strip_think；以后只原样同步主办方版本，不做自定义修改。
- 正式时限 900 秒，baseline 请求 840 秒、输出 16384；声明共享 generation 思考设置及辅助模型。
  所有流程在 generation 为空时也禁止另加思考参数，YAML 仅可重复一致的共享选项。
- 评测题由赛事方专门准备，不取自公开数据集，VerilogEval 仅用于开发自测。
- 演示视频和报告第 12 节大模型协作记录为必交材料；投题令牌预计 10 月 20 日发到注册邮箱。
- 准备最终报告的真实结果和失败分析；封存时 REPORT.md 可为草稿，报告按系统最终提交为准。

`xsim` 与 `synth_design` 在上游说明的 Vivado 2026.1 环境中需要授权，`xvlog` 与 `xelab` 不需要；
授权失败应保留为环境错误，不能将缺失的仿真结果当作通过。
