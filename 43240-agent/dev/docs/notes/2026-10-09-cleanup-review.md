# 文档与测试清理清单

- 类型：清理计划与执行记录
- 状态：用户批准后已执行，本地验证完成，未提交或推送
- 日期：2026-10-09
- 审查基线：`d8c4d7f`，本地分支 `codex/cleanup-review`
- 来源：当前源码、测试断言、文档内容与引用关系的静态检查

## 结论与范围

本次确认可以删除的是一个未使用的测试辅助函数；尚未发现有充分依据可以整份删除的测试文件。
文档主要问题是当前手册与专题重复维护、少量说明遗漏，以及长期指南混有某次迁移的现场状态。
建议先修正这些问题，再有条件地合并专题。不能仅凭日期较早或文件名带 stage 就认定内容失效。

审查范围为队伍目录的当前指南、设计专题、历史记录索引及 `dev/tests/`。
未清理运行数据、缓存、模型权重或凭据；未启动云端实例、模型服务或 Vivado。
以下路径除特别说明外，均相对于 `43240-agent/`。链接指向当前文件，行号以审查基线为准。

当前有 12 个 Python 测试模块，静态统计共 119 个 `test_*` 方法，另有一个 JavaScript 测试文件。
这是审查时的源码数量；执行后的测试结果见文末。下列清单保留审查时的建议，完成状态以执行结果为准。

## 第一批：明确建议处理

| 编号 | 对象与依据 | 建议操作 | 影响与验收 |
| --- | --- | --- | --- |
| C01 | [test_tools.py](../../tests/test_tools.py) 第 145 行 `_pid_is_running`：在当前队伍 Python 文件中只有定义，没有调用或导入 | 删除这个辅助函数，保留所有测试及 `_write_executable` | 不减少测试断言；重新搜索符号并运行 `test_tools.py` |
| C02 | [User Manual](../user-manual.md) 第 737 行仅列出 `ok/failed/timeout`；[processes.py](../../../agent/services/processes.py) 启动失败会返回 `unavailable`，`ProcessStatusTests` 已覆盖 | 补全 `unavailable` 的含义：命令无法启动，并说明与运行后失败、超时的区别 | 文档修正，不修改状态语义；对照实现和既有断言 |
| C03 | [目录与提交](../user-manual.md#13-测试打包与限制) 第 25、37、41 行包含“本次”“本阶段”“本轮开始前云端已销毁”等现场描述 | 当前指南只留下稳定规则；将具有历史价值的迁移结论保留在有日期和来源的阶段记录中，避免被读成当前云端状态 | 不据此判断或改变云端实例状态；检查相关阶段记录和链接后再移除重复句子 |
| C04 | [历史实验分析工具](../design/historical-analysis.md) 第 4 行以“本阶段仅迁移路径”描述当前工具 | 改为明确的格式适用范围；迁移经过保留在历史记录，保留工具清单与生成命令 | 不删除分析脚本，不改写旧实验数据 |

## 第二批：合并重复文档，满足条件后才能删除原文件

这些文件仍有有效内容，属于“可整合”，不是“已废弃”。建议以 Quickstart 负责快速上手、User Manual
负责完整用法，减少同一接口在多处重复说明。每份专题都需要逐节比较，不能直接删除后只补一个链接。

| 编号 | 候选文件 | 主要承接位置 | 删除前必须保留的内容 |
| --- | --- | --- | --- |
| M01 | [python-workflows.md](../user-manual.md#10-python-组件与扩展) | User Manual 第 9—11 节 | 注册与构造约束、直接构造的元数据规则、上下文接口、自定义组件示例、依赖注入与生产边界 |
| M02 | [runtime-reliability.md](../user-manual.md#11-上下文服务与运行监督) | User Manual 第 5—7、11 节 | 候选比较与失败次数边界、检查缓存键及禁用条件、检查点恢复、进程组回收、取消与后端推理的区别 |
| M03 | [configuration-and-experiments.md](../user-manual.md#12-开发实验与指标) | User Manual 第 2、8、12 节，配置字段说明保留在 example.yaml | 配置优先级与来源、路径解析、实验产物、指标异常及未知值、Agent 与 baseline 边界 |
| M04 | [layout-and-submission.md](../user-manual.md#13-测试打包与限制) | User Manual 第 1、13 节；开发规则引用 conventions.md | 打包 API、允许复制的文件、目标目录限制、独立 smoke 的环境清理与验证局限；历史迁移结论另行保留 |

建议按 M01—M04 分别实施。每项完成后更新文档索引、手册及其他入站链接；历史记录的结论、命令和
测量结果保持原样，仅在必要时修复导航或补充当前指南入口。若某节尚无等价承接内容，保留该专题。

不建议继续扩大 User Manual 中的格式细节重复：保留 [trace-schema.md](../design/trace-schema.md)
作为记录格式的专题参考，手册侧重输出用途、目录和排查方法。日志查看器、远程工具、历史分析也有独立
操作场景，应保留专题，而不是把所有文档都塞入一份手册。

## 第三批：测试组织调整，不删有效覆盖

| 编号 | 当前对象 | 建议 | 必须保留的覆盖与依赖 |
| --- | --- | --- | --- |
| T01 | `dev/tests/test_stage3.py`，20 个测试 | 后续按修复决策、缓存、监督及证据记录拆分，文件名表达职责 | 超时强停、后代进程回收、检查点恢复、取消、真实与复用检查计数、日志脱敏均仍对应当前代码 |
| T02 | `dev/tests/test_stage4.py`，19 个测试 | 按配置、实验执行、指标拆分 | 配置校验与来源、样本隔离、本地假 HTTP 服务、实验取消、异常与未知指标，不因“阶段四”名称删除 |
| T03 | `dev/tests/test_stage5.py`，6 个测试 | 改为提交检查相关名称，必要时单独拆出远程包装脚本测试 | 独立 Agent/baseline 入口、缺失文件、开发依赖和符号链接、拒绝覆盖、远端工具离线加载 |
| T04 | `test_candidate_flow.py` 中被其他测试导入的公共辅助对象 | 若执行 T01，先将共享假模型、假工具及构造函数迁入测试辅助模块，再调整引用 | `test_workflows.py` 与 `test_stage3.py` 都直接导入该测试模块；不能将其当成孤立旧测试删除 |

测试拆分不是本轮清理的必要前提，优先级低于 C01—C04。迁移应保留原有断言和发现规则，不能以减少
文件数量为目标把不同层次的测试合并掉。例如答案原子写入、Runner 选择一致性和 Supervisor 中断恢复
分别验证不同边界，即便都涉及 `solution.v`，也不算重复测试。

`test_log_viewer.cjs` 同时验证官方 baseline 和新版精简 Node 事件。查看器需要读取已有运行记录，
对旧格式的支持具有实际用途，不能因记录格式已简化而删除这些断言。

## 保留与排除清单

| 对象 | 处理意见与原因 |
| --- | --- |
| Quickstart、User Manual、`config/example.yaml` | 保留，作为当前使用入口；合并专题时同步维护 |
| `43240-agent/README.md` | 保留必要的独立使用说明；dev 不随方案提交，不能仅用指向开发手册的链接替代它 |
| `dev/docs/notes/` 的阶段计划、验证、决策及失败分析 | 保留历史正文，通过索引和状态区分历史与当前指南 |
| `dev/docs/experiments/`、历史统计生成内容 | 保留实验来源和数字，不因接口变化批量删除或重新生成 |
| `dev/tools/analysis/` | 仍用于历史格式及生成旧分析表；没有充分依据整体删除 |
| 其他当前测试模块 | 保留；覆盖提取、接口、模型、候选、记录、Workflow 和入口契约，未确认整份失效 |
| `REPORT.md` 等提交声明或报告文件 | 不因占位内容而删除；实测结论补写属于后续提交准备 |
| 主办方文件、`baseline.py`、`run_baseline.sh` | 本次清理排除，遵守仓库只读边界 |
| 本地运行产物、缓存、模型及凭据 | 未审计保留期限和使用情况，不纳入本次删除清单 |

保留历史记录依据 [开发规范](../conventions.md)：“历史笔记在索引中归档并注明状态，保留当时结论；
不得删除实验、验证、决策及类似记录。”这里的归档指更新状态与索引，不创建 archive 目录。

审查开始时已有两个未跟踪文件，均未修改或移动：

- `dev/docs/experiments/20261007-221221-cloud-single-review-691f4b83.md`
- `dev/experiments/20261004-212040-joint-cur-qwen3-8b-quick.md`

它们不自动进入清理提交。是否整理第二个文件的位置、是否将两者纳入版本控制，需要单独确定其归属；
文档索引已经说明旧路径下存在用户本地笔记，不应直接当作遗漏垃圾删除。

## 实施顺序与验收

建议先批准并实施 C01—C04，再决定是否实施 M01—M04；T01—T04 可以单独安排。
本清单不包含更改 Agent 算法、模型配置、云端资源或历史实验结果。

1. 实施前复查 Git 状态，只改本清单批准的对象，保护用户已有文件。
2. 删除辅助函数时搜索其引用，并在方案目录执行 `python3 -m unittest discover -s dev/tests -p test_tools.py -v`。
3. 合并专题时逐节核对承接内容，搜索旧文件名，修复当前导航并检查 Markdown 本地链接。
4. 若迁移测试，迁移前后都执行 `python3 -m unittest discover -s dev/tests -v`，核对用例名称、数量、跳过及失败原因；数量相同不能代替断言核对。
5. 若涉及查看器或其测试，再执行 `node dev/tests/test_log_viewer.cjs`。本清单没有要求删除其兼容逻辑。
6. 检查 diff，确认没有历史数字、凭据、运行产物或受保护文件混入；若后续改变方案结构或行为，同步维护方案 README。

验收报告分别写明“已删除”“已合并”“已保留”和检查结果。未实际运行的测试不得报告通过；
环境导致的跳过和失败应单列。初次审查仅新增清单；用户随后批准继续推进，实际执行结果如下。


## 执行结果（2026-10-09）

C01—C04、M01—M04、T01—T04 均已处理。方案运行代码和配置未改变。

### 已删除与修正

- 删除 `test_tools.py` 的未调用辅助函数 `_pid_is_running`。
- 补全 ProcessResult 的 `unavailable` 状态与语义。
- 移除当前指南中容易被误认为即时状态的迁移叙述；迁移经过继续由第五阶段记录承载。
  原目录专题曾记载该次迁移前云端已销毁，这只是当时状态，本次没有查询或改变云端状态。
- 修正历史分析工具的格式适用范围，并补充历史迁移记录入口。
- 合并时另外清除了两处已失效的候选保存开关说明，修正模型响应保存和排错文件说明。

### 已合并的文档

删除 `design/python-workflows.md`、`design/runtime-reliability.md`、
`design/configuration-and-experiments.md` 和 `design/layout-and-submission.md`。
有效内容由 User Manual 对应章节承接，补充了构造元数据、异常传递、配置来源、缓存身份、
进程状态及回收、实验指标边界、打包 API 与独立验证限制。

方案 README、文档索引和历史笔记的当前指南链接已更新。历史笔记仅改导航，原结论、命令和数字未改。
Quickstart、example.yaml、记录格式、查看器、远端管理和历史分析专题保留。

### 测试迁移对照

| 原位置 | 当前文件 | 用例数 |
| --- | --- | --- |
| test_stage3.py | [test_repair_decisions.py](../../tests/test_repair_decisions.py) | 8 |
| test_stage3.py | [test_check_cache.py](../../tests/test_check_cache.py) | 2 |
| test_stage3.py | [test_supervision.py](../../tests/test_supervision.py) | 6 |
| test_stage3.py | [test_evidence.py](../../tests/test_evidence.py) | 4 |
| test_stage4.py | [test_configuration.py](../../tests/test_configuration.py) | 6 |
| test_stage4.py | [test_experiments.py](../../tests/test_experiments.py) | 10 |
| test_stage4.py | [test_metrics.py](../../tests/test_metrics.py) | 3 |
| test_stage5.py | [test_submission.py](../../tests/test_submission.py) | 6 |

共享假模型、假工具和辅助函数移至 [support.py](../../tests/support.py)。移除了拆分后无用的导入与
辅助定义，其他测试模块继续保留。通过 AST（抽象语法树）逐个比对，全部 119 个测试方法的正文及装饰器
与清理前一致；迁移改变模块名，提交检查类改名为 SubmissionTests。

### 验证结果

- 清理前：119 项，117 项通过，2 项因未安装 FastAPI 跳过；日志 `/tmp/cleanup-before-unrestricted.log`。
- 清理后：119 项，117 项通过，同样 2 项跳过；日志 `/tmp/cleanup-after.log`。
- 跳过项为 `test_http_preserves_records_outside_request_temporary_directory` 和
  `test_http_small_deadline_bounds_blocking_model_without_five_second_floor`，本轮没有验证这两项 HTTP 行为。
- 首次沙箱内运行有 3 项因禁止绑定本地 HTTP 端口失败；使用允许本地端口的执行环境重跑后通过，未修改测试以绕过限制。
- `node dev/tests/test_log_viewer.cjs` 通过，兼容性断言保留。
- `python3 dev/tools/submission.py` 检查无错误。
- 当前维护文档及本记录的本地文件链接检查通过；`git diff --check` 通过。

没有启动云端、真实模型或 Vivado。受保护文件和用户已有两份未跟踪笔记均保留；
改动留在本地 `codex/cleanup-review` 分支，未提交、推送或创建 PR。
