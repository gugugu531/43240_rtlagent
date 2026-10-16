# 上游文档与开发工具复查

- 类型：审查与验收记录
- 状态：已实施并验证，用户授权审查后推送开发远端
- 日期：2026-10-16
- 来源：主办方 `9df176717fec16751d02f4fb5c67dbd40a22fc15`；本轮重新 fetch，master 未更新
- 前序：[服务对齐验收](2026-10-16-upstream-serving-alignment.md)，本轮补查其余文档和开发调用方

## 发现与处理

| 核查范围 | 发现 | 处理 |
| --- | --- | --- |
| REPORT.md | 旧示范三轮流程、旧增益、4096 输出和手动后台启动命令 | 改为当前方案草稿，正式模型与实测保持待填写，不填写虚构结果 |
| 评分说明与开发汇总 | 上游已采用归一化增益，旧倍数字段含义不清 | 增加 gain_g、gain_score、gain_ratio；gain 保留倍数诊断兼容；有效样本必须配对 |
| 模拟投题客户端 | 仍要求同步 200 和直接 solution | 支持 202、查询状态、任务标识校验；总墙钟从投题到查到 done，超时不重投 |
| 模拟投题成绩与记录 | 直接调用受保护的旧 score.py，会产生旧增益分 | 开发侧 scoring.py 复用官方等级聚合，按现行 g 与 0.6 计算；记录器兼容新旧结果 |
| 远端启动 | 默认 GPU_UTIL=0.90 覆盖上轮的新预算 | 新默认留空，采用 vllm.sh 自动预算；已有个人 remote.env 不修改，文档提醒显式值仍生效 |
| 提交要求 | 缺封存日程、Gitee 私有仓库名、默认分支和邀请要求 | 新增提交核对专题，方案 README 写入独立包可读的要求与上游链接 |
| 题集文档 | 本地旧自测文档只列 1 道缺陷 | 开发说明补充上游 11 道、145 题分母建议；历史数据、清单及题目不自动改写 |
| 授权说明 | 旧 FAQ 声称无需 license | 新核对专题注明上游 2026.1 的仿真和综合授权要求 |
| 技能来源 | 旧示范把 AMD Skills 当成通用方案技能库 | 按上游区分 Ross 的 FPGA 设计与 AMD Skills 的 ROCm/量化用途；不宣称已完整兼容或导入 |
| 最新上游其他文件 | 新 notebook 和原始文档更改 | 可选 notebook 不引入；受保护文件保持原快照，当前指南明确指向固定版本上游 |

现行公式：`g=(方案−基线)/(1−基线)`，增益得分 `40×min(g/0.6,1)`；g≤0 为零分，
基线满分时增益项满分。旧历史 overview、旧 selftest CLI 和历史实验记录仍保留旧口径，不用于现行计分。

## 审查边界

审查整个分支相对 origin/main 的差异，核对入站鉴权、nonce 线程安全、后台生命周期、
包含排队的时限、进程组清理、trace 输出、启动幂等、显存预算及新增开发调用方。
本轮还核对了原始 README、SCORING、REPORT_TEMPLATE、docs、example 和 selftest 的上游差异。

根目录主办方文件、docs、selftest、example 与两个 baseline 保持不变。上游新版 baseline
包含 strip_think，本地受保护文件仍是旧版本；已在当前报告与提交核对中明确，需要封存前核实。
旧实验的测量值与历史笔记不重写。正式模型、权重 revision、官方镜像与 GPU 实测占位项仍未完成，
不把此次源码推送写成已完成 Gitee 封存、协作者邀请、服务报送或系统提交。

## 验证

使用 `/tmp/rtl-async-service-venv/bin/python`，在需要本机套接字时解除沙箱网络限制；
未调用外部模型、未启动云端 GPU。

```bash
python -m unittest discover -s dev/tests -p 'test_*.py' -v
python dev/tools/submission.py --stage /tmp/43240_rtlagent-audit-20261016 \
  --task ../tasks/example/example_ex03_lfsr8 --output /tmp/rtl-upstream-audit-smoke-20261016
bash -n dev/tools/remote/remote_vllm.sh
git diff --check
```

- 343 项：334 项通过，9 项真实 Vivado 测试按默认设置跳过，无失败或错误。
- 新增 7 项回归覆盖上游评分示例、基线为 0/1、负增益、不配对样本、实际 sample ID 不一致、
  当前实验字段兼容、202/查询响应、错误标识与状态、缺失结果、总超时及不重投。
- 独立包不含 dev 和题库，mock 单题 `ok=true`、答案 177 字节，监督状态 completed。
- 真实本机 uvicorn 与命令行 submit_client 闭环：
  `dev/runs/20261016-160307-upstream-audit/`，1 道题、agent/baseline 各 1 次，
  两个答案均 59 字节，传输错误 0。模型为本机 HTTP 替身，不是能力或 GPU 实验。
- 首次 10 秒集成检查沿用默认 20 秒清理预留，Agent 按预算约束未启动；显式设置
  `AGENT_RESERVE_S=1` 后完成上述闭环，未为通过测试修改正式默认值。
- 受保护文件相对 origin/main 无差异，两个 baseline 与本地 example 逐字节一致。

临时日志：`/tmp/rtl-upstream-audit-tests-20261016.log`；打包输出：
`/tmp/rtl-upstream-audit-layout-20261016.json`。临时验证脚本与日志不纳入 Git。

## 云端交付范围

用户授权本轮审查后提交云端。使用当前 origin，即 GitHub 开发仓库；独立分支推送并创建 PR，
不向 main 直接提交、推送或自行合并。赛事 Gitee 建仓与邀请需另行办理，见[提交核对](../design/submission.md)。
