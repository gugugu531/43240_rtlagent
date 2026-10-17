# 主办方最新源码同步

- 类型：同步与验收记录
- 日期：2026-10-17
- 状态：已同步到独立本地分支并验证
- 来源：[主办方仓库](https://gitee.com/Vickyiii/rtlagent2026)，`f7a8bd465c2a820e006c7a00ecc7df468974635b`，2026-10-17 10:38（北京时间）

## 范围

用户本轮明确要求拉取主办方最新更改并同步到工作区仓库。因此本轮对原来只读的主办方文件
执行官方版本原样更新，不再只在开发文档中标注差异，也不对原始内容作队伍定制修改。
前序 PR #40 已合并，本轮从 origin/main 的 fafaf6a 建立 codex/sync-upstream-20261017。
开始时工作区干净，队伍在 main 上已有的开发与训练资料一并保留。

上游共 60 个文件均有本地对应：根目录赛事文件、docs、example、selftest 原样更新，补充 notebook。
任务仍保存在已整理的 tasks/example/：18 个示例题文件按目录映射核对，三份 task.json 只保留
本地 task_id 与 original_task_id，其余字段一致；题面、参考实现与测试台逐字节一致。
不复制重复题库，不覆盖其他来源题目，不修改个人 selftest/env.sh 或 remote.env。

43240-agent/baseline.py 和 run_baseline.sh 同步为主办方原文件，与 example 逐字节一致，
没有自定义补丁。该更新由本轮同步请求授权；后续日常开发仍遵守原文件保护规则。

## 主要变化及适配

上游新增正式 900 秒时限、baseline 16384 输出和 840 秒请求上限、共享 manifest generation、
辅助模型声明、GitHub 提交选项、视频与大模型协作记录；明确正式评测题由赛事方专门准备，
不取自公开数据集。云端部署按新说明将临时目录设到 /var/tmp，避免 /tmp 的 4 GB 内存盘限制。

- 默认 HTTP、运行配置和 RunOptions 的单题预算改为 900 秒；默认 single_generate 从官方常量取得新额度。
- ModelRequest 支持官方接受的标量 chat_template_kwargs 与 reasoning_effort；ModelService 复用官方加载器，
  对所有流程应用共享思考声明并拒绝冲突。计数与请求使用一致的模板选项。
- manifest 加入 generation 与 auxiliary_models；当前为空，保留服务端默认，未擅自选择最终模型思考策略。
- 初始检查点指纹包含 manifest.json，避免修改声明后误用旧检查点。
- evidence_repair 等可选实验保留原来显式的 8192/300 等预算，不把历史实验改写成新版 baseline 条件。
  对应测试改为验证保留的实验预算，文档删除“与新版 baseline 相同”的旧说法。
- 当前方案、模型、报告、服务与提交指南同步更新；历史实验、测量与旧笔记正文不重写。

官方 notebook 原样保留，默认使用其自身克隆的 rtlagent2026 原始布局。
若在本开发工作区复用单元格，需把 tasks/ex01_popcount8 等路径改指 tasks/example/example_ex01_popcount8，
不得因此声称本工作区完整跑过该 GPU notebook。

## 验证

临时环境 /tmp/rtl-upstream-sync-venv，依赖来自仓库 requirements.txt 与本机 HTTP 测试所需 httpx。

```bash
python -m unittest discover -s dev/tests -p 'test_*.py' -v
python dev/tools/submission.py --stage /tmp/43240_rtlagent-sync-20261017 \
  --task ../tasks/example/example_ex03_lfsr8 --output /tmp/rtl-upstream-sync-smoke-20261017
```

- 全量 347 项：338 项通过，9 项真实 Vivado 测试按默认设置跳过，无失败或错误。
- 新增 4 项：共享思考声明与计数、冲突拒绝、manifest 检查点指纹、独立方案包中 baseline/Agent
  的真实本机 HTTP 请求及思考文本提取一致；含忽略非白名单配置与嵌套值的验证。
- 上游 60 文件对应检查通过；18 题库文件保留的目录/元数据映射外无差异；两个 baseline 字节检查通过。
- notebook JSON 可解析，共 29 个单元格；未执行需要 GPU、下载模型或云实例的单元格。
- 独立方案包不含 dev 或题库；mock 单题退出码 0、答案 177 字节、监督 completed。
- git diff --check 通过。第一次全量检查发现两项旧常量断言，按新版默认与保留实验预算的不同契约更新后复验通过。

临时测试日志为 /tmp/rtl-upstream-sync-tests-final.log，打包输出为 /tmp/rtl-upstream-sync-layout.json。
未启动付费实例，未做目标 GPU 实测；正式模型与官方镜像占位项仍待最终选择和测量。
本轮范围是同步工作区，不自行推送远程或合并 main。

## 2026-10-17 后续审查

用户随后授权复查后提交、推送 GitHub 并创建 PR，暂不合并。后续发现的配置边界、权限遗漏与
350 项验证见[提交前审查](2026-10-17-upstream-sync-review.md)，本记录保留首次同步时的范围和验证数字。
