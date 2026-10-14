> 2026-10-14 整理补注：本文保留当时验证结论；历史聊天附件或其他机器路径的当前可访问范围见[证据位置核对](2026-10-14-evidence-locations.md)。

# PR #33 审查修复验收记录

类型：验证记录。状态：本地验收完成，等待重新审查。日期：2026-10-14。
来源：[功能审查](https://github.com/gugugu531/AMD_SocChina_2026/pull/33#pullrequestreview-5505052655)、
[文档审查](https://github.com/gugugu531/AMD_SocChina_2026/pull/33#pullrequestreview-5505156978)及本地原始记录。

运行编号：`pr33-review-20261014`。被验证的功能修复提交：`2deb71f`；修复前 PR 提交：`17a9f1b`。
工作区：`/home/cloudia/FPGACHINA/worktrees/amd-agent-upload`。以下命令在其 `43240-agent/` 下执行。
本轮只执行本地回归和 mock 提交包检查，没有启动后续模型实验或云端实例。

## 反馈与修复

| 反馈 | 已实现行为 | 对应回归 |
| --- | --- | --- |
| 切换 Workflow 时工具身份变化 | 单独计算重放身份，保留工具文件、配置与相关环境校验，不计入 Agent 调度变量 | `test_entry_replay.py` 经正式 run.sh 切换 search_initial/search_r2；许可证、器件和工具文件变化仍拒绝 |
| 无效知识库中止修复 | 根对象、来源、卡片及字段类型统一校验，格式错误转换为 ValueError，记录 corpus_unavailable 后继续原修复 | `test_knowledge.py` 覆盖错误类型；`test_evidence_ablation.py` 验证 []、null 和错误嵌套对象的修复消息与无卡相同 |
| 直接运行缺少停止点 | 首次完成后建立本次初始检查点，第三次调用前或提前停止时保存真实状态；使用已验证信息，不再次读取外部检查点 | `test_search_ablation.py` 覆盖直接运行、重放、提前通过、检查不可用、提取失败、第三次请求失败和首个请求失败 |
| thinking 配置与计数不一致 | 普通请求按实际发送选项计数；baseline_rtl 不注入配置选项，也不按该配置计数，记录忽略原因 | `test_context_tokens.py` 同时检查请求字段及计数器选项；既有 baseline 差分测试保持通过 |
| 说明与证据不完整 | 同步 README、配置注释和运行接口，解释 E1/E2 与短卡，补充本记录及索引 | 本记录、接口文档与 PR 描述互相链接；原始日志不提交 |

## 本轮验收

| 检查 | 结果 | 本地证据（相对 43240-agent/） |
| --- | --- | --- |
| 完整组件回归 | 201 项，199 项通过，2 项跳过 | `dev/runs/pr33-review-20261014/component-tests.log` |
| 独立提交包 mock smoke | 退出码 0，输出 177 字节，stop_reason=completed | `dev/runs/pr33-review-20261014/package-smoke/smoke.json` |
| 提交包文件清单 | 不含 dev、实际知识库或本地凭据 | `dev/runs/pr33-review-20261014/submission-manifest.json` |
| baseline 一致性 | baseline.py 与 run_baseline.sh 均和 example 逐字节一致 | `dev/runs/pr33-review-20261014/summary.json` 的 baseline_sha256 |

两项跳过均因当前验证环境没有安装 FastAPI：HTTP 记录保留和 HTTP 请求短时限测试。
本轮保持原验证环境，未安装额外依赖。正式入口重放测试使用本地假工具及 mock 模型，
只检验流程，不冒充真实 Vivado 或真实模型收益。

实际验证用 Python 为 `/home/cloudia/FPGACHINA/worktrees/amd-p0-e1/43240-agent/dev/venv/bin/python`。
组件回归命令：

```bash
/home/cloudia/FPGACHINA/worktrees/amd-p0-e1/43240-agent/dev/venv/bin/python -m unittest discover -s dev/tests -p 'test_*.py' -v > dev/runs/pr33-review-20261014/component-tests.log 2>&1
```

提交包检查命令：

```bash
/home/cloudia/FPGACHINA/worktrees/amd-p0-e1/43240-agent/dev/venv/bin/python dev/tools/submission.py --stage /tmp/fpgachina-pr33-review-submission-20261014 --task /home/cloudia/FPGACHINA/AMD_SocChina_2026/tasks/ex03_lfsr8 --output dev/runs/pr33-review-20261014/package-smoke > dev/runs/pr33-review-20261014/package-check.log 2>&1
```

暂存包位于 `/tmp/fpgachina-pr33-review-submission-20261014`，它不含 dev。
清单副本和 smoke 原始输出保存在本地运行目录。
汇总文件 `dev/runs/pr33-review-20261014/summary.json` 关联提交、运行源码指纹与日志 SHA256。

## 之前 PR 数字的来源

以下是历史验收，不作为本轮重新执行的结果；保留原日志与报告，并复制到本地运行目录的 history/。

| 历史范围 | 数字与来源 | 本轮保留的证据副本 |
| --- | --- | --- |
| 92ed389 的外置知识库修改 | 186 项组件测试，184 项通过、2 项跳过；原日志 `/tmp/fpgachina-repair-knowledge-tests.log` | `dev/runs/pr33-review-20261014/history/186-component-tests.log` |
| 17a9f1b 的修复提示澄清 | 189 项组件测试，187 项通过、2 项跳过；原日志 `/tmp/fpgachina-repair-interface-tests.log` | `dev/runs/pr33-review-20261014/history/189-component-tests.log` |
| 独立 HDL 修复原则验证 | 运行编号 `repair-cards-v2-validation-20261013`，7 组错误/修正/控制例，共 21 例，all_valid=true | `dev/runs/pr33-review-20261014/history/21-hdl-validation.json` |

21 例的原始报告位于
`/home/cloudia/FPGACHINA/worktrees/amd-agent-pr/43240-agent/dev/runs/repair-cards-v2-validation-20261013/report.json`，
执行命令为 `python3 dev/tools/validate_repair_cards.py --out dev/runs/repair-cards-v2-validation-20261013`，
执行前加载本机 Vivado 2026.1 环境。报告中的 tool_sha256 与本 PR 的验证工具源码一致。
报告验证的是这些独立小例子的工具行为，不证明完整题集收益；本轮没有重跑这 21 例。
原始路径与副本 SHA256 另见 `dev/runs/pr33-review-20261014/historical-evidence.json`。

## 远端检查与边界

通过 GitHub API 读取修复前 PR 头 17a9f1b 的检查结果：check-runs 为 0，提交状态条目为 0。
没有可核实的 CI 结果，汇总文件中 CI 结论留空；不能把本地通过称为远端 CI 通过。
审查反馈及检查响应只保存在本地运行目录。

本记录只上传验收说明；知识库、原始日志、暂存包、模型权重、凭据和远程实验工具均不上传。
没有修改或追加已有 E1/E2 实验结果，也没有执行后续消融实验。
