> **文档状态：归档验证记录：只说明该次版本和测试范围。** 历史证据保留，当前框架用法与限制以[详细参考](../user-manual.md)为准。

# 第五阶段进展：目录、规范与提交检查

| 项 | 内容 |
| --- | --- |
| 状态 | 经审阅范围已实施，本地回归和独立目录验证完成 |
| 日期 | 2026-10-05 |
| 范围 | 行为保持的模块迁移、开发目录收敛、打包检查 |
| 边界 | 不新增模型策略、历史重放或新实验比较；未启动云端 |

## 已完成

运行器、上下文、监督、候选和接口归入 agent/core；实际 Vivado 工具归入 services/vivado；
原子产物归入 recording/artifacts；提取逻辑归入 nodes/extraction；提示构造和技能选择归入
prompts。相关导入、资源根目录、测试、服务、源码快照和公开示例均使用新位置，没有旧路径兼容层。
Supervisor.run 的实际返回仍是 WorkflowResult，没有新增计划示例中提到的 SupervisorResult。

开发区已收敛为 tools、configs、tests、runs、docs。远程管理位于 tools/remote，历史分析位于
 tools/analysis；任务子集和分类表集中在 configs。旧 run_eval.py 已移除，远程联合脚本和
remote_eval.sh 使用统一 run.py；参考答案链路验证使用未修改的官方 --reference 入口，产物放
 dev/runs。显存采样新增退出清理，避免统一实验异常退出后继续采样。

团队文档集中在 docs/design、notes、experiments，开发规范位于 docs/conventions.md；
AGENTS.md、dev/README.md 和方案 README 已更新。迁移保留历史数字、身份、来源和生成块，只调整
引用路径；旧记录仍使用原格式，历史分析工具不被宣称支持新实验格式。

remote.env、cloud.state、cloud_known_hosts 随目录迁移，未改内容，由 dev/.gitignore 排除。
用户未提交笔记 `dev/experiments/20261004-212040-joint-cur-qwen3-8b-quick.md` 保留原位和内容，
未纳入本阶段提交；因此原 experiments/ 目录暂时只为这份文件保留。

Dockerfile 补齐 config/ 和 baseline.py。新增 dev/tools/submission.py，按明确文件清单检查并
暂存方案，拒绝已有或位于源码树内的目标；保存文件哈希，在没有 dev、没有继承 PYTHONPATH 的
目录中运行默认 mock。具体接口与限制见[目录与提交说明](../design/layout-and-submission.md)。

## 验证

```bash
PYTHONPATH=/tmp/fpgachina-stage1-deps python3 -m unittest discover -s 43240-agent/dev/tests
python3 43240-agent/dev/tools/submission.py \
  --stage /tmp/fpgachina-stage5-submission-final \
  --task tasks/ex03_lfsr8 --output /tmp/fpgachina-stage5-submission-final-smoke
```

123 项测试通过，日志 `/tmp/fpgachina-stage5-tests.log`，约 9.98 秒。原 116 项全部保留；新增检查
覆盖两个独立打包入口、缺失默认配置、Docker 缺失 baseline、开发依赖与符号链接、目标覆盖保护、
离线远程路径加载，以及远程联合脚本从其他工作目录调用统一入口并停止显存采样。
测试中使用本地假模型服务和远程命令替代，不代表真实模型或云端验证。

独立暂存 smoke 成功：177 字节答案，监督状态 completed，没有未回收后代，证据位于
`/tmp/fpgachina-stage5-submission-final-smoke/`，清单位于暂存目录旁。暂存 baseline 测试使用本地
HTTP 服务，未进行 RTL 功能判定。检查逻辑同时核对当前 Docker COPY 的目标路径。

统一入口迁移后 smoke 见[实验记录](../experiments/20261005-201406-stage5-mock-9f5cfd91.md)：
ex03，mock，1 个样本完成，不启用 judge。任务配置离线解析结果：joint-quick 选中 34 题，
joint-full 选中 155 题、排除 4 题；只验证清单，不代表已经跑分。

全部维护文档的本地 Markdown 文件链接检查通过，12 个维护 Shell 脚本语法检查通过；
Python 编译检查、git diff --check 和两个 baseline 的逐字节对照通过。
新远程凭据和状态路径的 git check-ignore 检查通过，原用户笔记未修改。

## 当前边界

本轮没有启动云端，没有调用真实模型或 Vivado，也没有改变模型声明和服务策略。
本机 Docker 可用，但没有 Dockerfile 所需的官方基础镜像；未执行需要拉取镜像或安装依赖的
完整构建。静态复制检查和临时目录 smoke 不能替代真实官方镜像、断网依赖、权重准备或最终 GPU 验证。

打包检查只覆盖明确文件、直接导入和当前简单 COPY 声明；动态导入、隐藏秘密和参考答案仍需
人工审核。外置模型权重不被打包。历史重放、新实验比较和求解能力扩展继续后置，下一阶段仍先审阅计划。
本阶段只在现有独立分支作本地提交，不推送或创建 PR。
