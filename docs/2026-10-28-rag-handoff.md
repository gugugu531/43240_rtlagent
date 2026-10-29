# RAG 工作交接：本地、33376、33589

> 2026-10-29 rc4.6 工作区更新：第四批 10 张卡已完成当前版本双臂模型对照、公开合同门禁和发布后双路由检查，当前为 32 legacy_policy／38 restricted／33 shadow／26 mechanical_only。有效晋升证据使用 20 次生成调用；另 2 次发现 `division-equality-boundary` 的 card 臂编译失败，该卡保持 shadow，由 `toggle-divider-period` 替补。BM25 排名 1–5、dense 排名 1–2，最终均只接纳目标卡；无重试、未使用生产 cohort、未切换在线配置。详见 [rc4.6 运行说明](2026-10-29-rag-rc46-runbook.md)。

> 2026-10-29 rc4.5 工作区更新：第三批 10 张卡完成门禁和发布后双机路由，当前为 32 legacy_policy／28 restricted／43 shadow／26 mechanical_only。BM25 全部前二，dense 最差第四，最终均只接纳目标卡；没有新增生成调用。rc4.4 的四个明确不适用规则和标量输出结构守卫已修复。详见 [rc4.5 运行说明](2026-10-29-rag-rc45-runbook.md) 与 [restricted 生产化方案](2026-10-29-rag-restricted-to-production-plan.md)。

> 2026-10-29 rc4.4 工作区更新：第二批 10 张卡已通过公开合同正向、已知、冲突、信息不足、不适用、篡改、tokenizer、BM25 与两台主机 dense 路由门禁，并全部晋升为 `restricted / pre_generation_only`。当前统计为 32 legacy_policy／18 restricted／53 shadow／26 mechanical_only。发布后 10/10 的 BM25 与远端 dense 实际接纳通过，全量 139 项测试通过；没有新增生成调用、没有切换在线配置、没有提交或推送。证据见 `dev/optimization-v54/` 和 [rc4.4 运行说明](2026-10-29-rag-rc44-runbook.md)。

> 2026-10-29 当前接手入口：[第45批完成报告](2026-10-29-rag-batch45-results.md)、[rc4.2运行说明](2026-10-29-rag-rc42-runbook.md)。16次真实生成全部完成并独立审计；原件两机`/root/rtl-rag-cohort45-20261029-r2`，回传及审计在`dev/optimization-v46/`。当前资产rc4.2为32 legacy／5 restricted／66 shadow／26 mechanical_only，题面候选谓词15类；packer新增权限仅首次生成，并补齐发布沿及复位极性合同，mixed-sign和empty-star只转shadow。默认配置不变，39张冻结、Skill暂停。最终候选与两机隔离加载收据在`dev/optimization-v48/`；rc4.1未部署包保留。下文当前／最新均按各条历史日期理解。

> 2026-10-29 后续完成更新：[第42批结果](2026-10-29-rag-batch42-results.md)，20次真实生成已回传并审计。活动候选rc3.2，12类候选谓词，4类受限注入。六类新版保持shadow，serial／triangle／grid由hold转shadow；mixed-sign及empty-star仍hold。云端本批原实验根为 `/root/rtl-rag-cohort42-20261029-r1`，其rc3冻结实现不得覆盖；旧候选包和历史状态保留。

> 最新完成状态（2026-10-29）：[六小时实施和双机结果](2026-10-29-rag-six-hour-results.md)已独立审计，28次真实生成结束。最终候选 `rag-catalog-v3-rc2` 的权威归档／收据在 `dev/optimization-v41/`，两机均已验证并保存于 `/root/rtl-rag-catalog-v3-rc2-final-20261029`。活动研究资产改为 `knowledge/research-v3.json`、对应锁和v3向量；旧v2文件保留用于回退。未切换默认在线配置，Skill暂停、39张冻结。下文环境配置仍可参考，早期资产路径与活动状态以本条和完成报告覆盖。

> 2026-10-29 完成更新：[v35 夜间审计](2026-10-29-rag-night35-audit.md)。两机队列已结束；98 次新调用，无卡 46/49、有卡 45/49。原始回传、97 卡台账和具体修复建议已保存；此次没有追加实验或更新运行资产。后文“已启动”是历史状态。

更新日期：2026-10-28（日本时间）。本次仅整理和核对本地文件，未查询实时主机负载、修改云端配置或启动新实验。

> 后续更新：v29 已在新批次中复核，v32 两机各 10 张已启动后台队列。当前活动任务以 [v32 审计与执行](2026-10-28-rag-v32-audit-and-execution.md)及其实际状态文件为准；下文“当前尚无新批次”等为交接初版历史状态。

> 2026-10-29 最新接手入口：[夜间 v35 计划与交接](2026-10-29-rag-night35-plan-and-handoff.md)。v32 已完成，新夜间目录、预算和状态均独立，不能按旧 v27/v32 的状态脚本判断本夜进度。

下一轮执行以[剩余不足一天的批量卡片与 embedding 计划](2026-10-28-rag-final-day-batch-and-embedding-plan.md)为准。本文件负责环境、历史状态、证据入口及接手步骤；计划文件负责调度与预算。旧文档中的“运行中”“许可证阻塞”均须按下述时间线理解。

## 1. 当前目标与不可混淆的范围

- 研究对象是 97 张已有机械证据的候选卡，另 27 张部分合同卡、12 张能力阻塞卡合计 39 张冻结；Skill 修复与扩展暂停。
- 原 32 张运行库保留。129 张目录向量不等于 129 张统一运行准入；新反馈选择器研究范围为 97 张，原 32 张诊断路径独立。
- 六类首次生成谓词已经接通真实检索、准入和装配；其中四类完成 v27 真实生成实验。另三条结构谓词仅完成本地反馈路径验证，未发布；不能说运行版已具备九类首次生成谓词。
- 97 张的机械证据可在版本与合同匹配时复用，不要求全部重新制作。旧的预期值直接作为实际准入结果的记录不能作为准入通过证据。
- 当前重点是扩大新卡有效覆盖、补真实准入和查询评测；默认自动注入保持关闭／实验 shadow 配置原状。实际 on 只由冻结实验配置选择。
- thinking 保持开启；不把截断 thinking 当可信计划，不把旧稿或复用结果算作新稿成功，不将开发回归当未见任务验收。

## 2. 本地位置与环境

仓库：`/home/cloudia/Documents/Codex/2026-10-25/new-chat/43240_rtlagent`。

| 项目 | 路径／说明 |
| --- | --- |
| 本地常用 Python | 仓库 `.venv/bin/python`；已有 `.venv312`，按脚本依赖使用 |
| 本地 Vivado | `/home/cloudia/Downloads/FPGAVitis/2026.1/Vivado/bin` |
| 当前研究资产及发布锁 | `knowledge/research-v2.json`、`knowledge/research-v2-lock.json` |
| 范围守卫 | `knowledge/research-scope.json` |
| 真实向量 | `knowledge/research-vectors.json` 及相应锁 |
| 模型缓存 | `/home/cloudia/.cache/rtlagent-embedding/models/Qwen3-Embedding-0.6B-Q8_0.gguf` |
| 本地 CPU embedding 程序及库 | `/home/cloudia/.cache/rtlagent-embedding/runtime/build/bin/` |
| 当前实现入口 | `agent/domain/knowledge/pregen.py`、`feedback.py`、`context.py`、`runtime.py`、`research.py` |

工作树有大量已有未提交修改，不应 reset、clean 或覆盖。交接不表示已提交或推送。修改发布实现后必须建立新实验身份与有效锁；不能只改哈希来绕过检查，也不能使用新工作树去复跑旧冻结实验。

## 3. 两台云端的已配置环境

```bash
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -p 33376 root@36.150.116.206
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -p 33589 root@36.150.116.206
```

31778 不参与。SSH 密钥沿用本机配置，不在文档保存私钥、令牌或密码。已完成实验不等于主机当前一定空闲，启动前仍读健康状态、槽位及模型锁。

### 生成服务，两机既有配置

| 项目 | 值 |
| --- | --- |
| API | `http://127.0.0.1:8010/v1` |
| 模型别名 | `qwen38-27b-q4-k-m` |
| 权重 | `/root/rtl-workflows-20261020/models/Qwen3.8-27B-Q4_K_M.gguf` |
| 权重 SHA-256 | `c600de0300ae8a0eb3a6c0b8b5561b8b96f16bd2c863c2a66c42de29d391a747` |
| MTP 权重 | `/workspace/rtl-runs/20261023-mtp-benchmark/mtp-Qwen3.8-27B-Q4_0.gguf` |
| MTP SHA-256 | `c5be331f82fb61f5304adfa00ccd60c6743c8ce52255d66fa863446231d49ba4` |
| 程序 | `/opt/llamacpp/llama-server`，b1-f114f91 |
| 上下文／槽位 | 65536／1 |
| 服务配置 | 线程 16、批处理线程 16、Flash Attention on、GPU offload、reasoning-budget=-1、draft-mtp、n-max=3 |
| 实验请求 | thinking=true、temperature=0、top_p=1、max_tokens=16384，同题同 seed，超时 800 秒 |
| 共享模型锁 | `/root/rtlagent-v12-model-8010.lock` |

服务默认采样与实际请求采样不同，以真实 request.json 为准。单机串行生成，不重启已有 8010 服务，不操作无关 8011 服务。完整迁移配置见[迁移记录](../dev/model-migration-20261028/README.md)。

### Python 与 Vivado

- 两机 Vivado：`/tools/Xilinx/2026.1/Vivado/bin`，2026.1。执行工具时显式加入 PATH。
- 默认 `/opt/python/bin/python` 为 3.14，旧依赖安装曾在 PydanticCore 构建处失败；实验改用 `/usr/bin/python3` 的 3.12.3 创建的隔离环境。
- 两机可复用的实验解释器：`/root/rtl-rag-v27-20261028/.venv312/bin/python`。33589 的 r2 也使用此环境，不假定 r2 根目录有另一个 venv。
- 离线依赖包括 apache-burr 0.43.0、pydantic 2.11.7、pydantic-settings 2.6.1、httpx 0.28.1、Jinja2 3.1.6、PyYAML 6.0.3；轮子及摘要见 `dev/optimization-v27/dependencies-lock.json` 和 `wheelhouse/`。不修改全局 Python。

### 许可证：已解决，保留初次失败

33589 迁移初次 xsim 日志报告许可证失败，之后已按 33376 的既有浮动服务器配置解决。两机使用 `/root/.flexlmrc` 中的连接项：

```text
XILINXD_LICENSE_FILE=2100@vivado-lic.fpgachina.svc.cluster.local
```

33589 后续复用原 XOR RTL，真实 xvlog/xelab/xsim 检查 65,536 组输入通过，未再调用生成模型。不能因旧迁移 README 的阻塞描述而重传权重或重建生成服务。

- 配置与验证脚本：`dev/optimization-v27/setup_license.py`。
- 本地收据：[license-validation-33589.json](../dev/optimization-v27/license-validation-33589.json)。
- 云端工具验证目录：`/root/rtl-workflows-20261028/license-validation-v27`。
- 初次失败原件：`/root/rtl-workflows-20261028/qwen38-service/smoke-20261028-110806`。

进程返回码 0 不足以证明仿真成功，还应核对日志中的许可证错误与实际测试完成标志。未来连接失效只报告基础设施失败，不计 correct_empty。

## 4. embedding：固定模型，统一运行程序

| 项目 | 固定配置 |
| --- | --- |
| 模型 | Qwen3-Embedding-0.6B-Q8_0.gguf |
| SHA-256 | `06507c7b42688469c4e7298b0a1e16deff06caf291cf0a5b278c308249c3e439` |
| 云端权重 | `/root/rtl-rag-models/Qwen3-Embedding-0.6B-Q8_0.gguf` |
| 别名 | `qwen3-embedding-0.6b-q8-0` |
| 输出 | 1024 维、last pooling、L2 归一化 |
| 服务 | 自有 CPU 进程，`127.0.0.1:8020`，context 4096、4 线程、GPU 层数 0 |
| 33589 已验证 portable 程序 | `/root/rtl-rag-cpu-f114f91/bin/llama-server`，同目录动态库 |
| 本地部署归档 | `dev/optimization-v27/portable-cpu-runtime.tar.gz` |

portable 程序带有原本地构建路径，远端启动须将其 bin 目录加入 `LD_LIBRARY_PATH`；仅传可执行文件而不传运行库不够。当前 `bootstrap.py` 支持 `--embedding-binary` 并设置库路径，但属于历史批次脚本，不能直接当作新批次通用启动器。

33589 首版使用云端既有程序，129 向量与本地最小余弦约 0.999557，低于预设 0.9999，生成前停止。r2 改用本地同款 CPU 程序和库，最小余弦约 1.0，通过原门槛。初次失败没有被覆盖。差异只能定位至运行程序／数值执行路径，未确定具体 CPU 指令原因。

33376 的 v27 r1 使用原云端程序；下一轮应在新目录部署同款 portable runtime 并验证一致性，不能说两机旧实验使用完全相同的 embedding 数值环境。当前模型无需更换或微调。

客户端独立核对 `/v1/models`，同时检查响应身份、索引、维度和有限值。返回 model 名会被服务回填，因此仅核对该字段不够；独立清单也不是远端权重的密码学证明。服务失效安全空返回并记 failure。

## 5. 已完成工作和证据入口

| 阶段 | 已完成 | 尚不能声称 |
| --- | --- | --- |
| v25 | 97/39 范围守卫；六方法首次生成装配；真实准入与请求测试；机械夹具 | 97 张均已支持自动注入 |
| v26 | 129 张真实向量；48+30 查询；服务身份修复；97 张反馈观察入口；34 个示例编译 | 全库生成收益或全量准入完成 |
| v27 33376 | 16 对、32 次真实生成，用户最新审计确认完成且一致性通过 | dense 优于 BM25，或 16 个独立知识类型 |
| v27 33589 r2 | embedding 严格复现；8 个上下文，16 次真实生成、8 次复用；本地复核通过 | 24 次独立生成，或存在检索器生成收益差异 |
| v28 本地 | 三谓词、9 案例、27 机械变体、72 条真实准入检查通过；当时 110 项快速回归通过 | 三谓词已发布，或新增生成收益已验证 |

v26 全 129 张目录的 48 条查询 Recall@5 为 BM25 66.7%、dense 91.7%；30 条反馈查询两者均 100%，首位命中率 83.3%／90%。两套合计覆盖 36 张目标卡，不是 97 张全覆盖；实际六卡阶段池结果另报。

33376 用户最新审计：control／dense 新稿交付 13/16→16/16，成功 11/16→16/16；3 次未交付、2 次新稿编译错误均在 control。总体 token 减少 54.1%，但去掉 X/Z 类后其余总 token 增加约 4.7%。重点保留 X/Z 和动态切片；进位、算术右移先收回 shadow。这里未重新取回 33376 原始审计文件，应在接手时确认本地归档位置。

33589 两条 X/Z 新题有合同问题，暂不计可靠救援；其他六题两侧均通过。BM25/dense 八组完整请求相同。见[合同复查](../dev/optimization-v27/context-contract-review.md)。thinking 仅作归因线索，尤其不能把 finish_reason=stop 且正文为空一律解释为 token 耗尽。

v28 的首次 slice 已知事实识别漏判保存在 `runs/local-v1/`；修复语序识别后 `runs/local-v2/validation-results.json` 通过。见[v28 说明](../dev/optimization-v28/README.md)。当前剩余工作口径是运行版六谓词＋91 张待准入，其中三张有未发布开发实现、88 张仍待补。

## 6. 冻结包、结果目录与审计陷阱

| 项目 | 位置 |
| --- | --- |
| 33376 完成批次 r1 | `/root/rtl-rag-v27-20261028` |
| 33589 首次 embedding 失败原件 r1 | `/root/rtl-rag-v27-20261028`，生成前停止 |
| 33589 完成批次 r2 | `/root/rtl-rag-v27r2-20261028` |
| r1 本地包 | `dev/optimization-v27/cloud-package/rag97-v27.tar.gz` |
| r2 本地包 | `dev/optimization-v27/cloud-package/rag97-v27-r2.tar.gz` |
| r1 清单和复现失败记录 | `dev/optimization-v27/frozen-r1/` |
| 33589 本地回传 | `dev/optimization-v27/returned/33589-r2/` |
| 33589 回传原归档 | `dev/optimization-v27/returned-33589-r2.tar.gz` |

r1 包 SHA-256：`768fcd92169a01b587769932e894386d1683521704a9cbb92729054697207a7e`。

r2 包 SHA-256：`09c803966522d041dd862eed7f50a7420bb705ed054bb220b5b6c4cd36a1be54`。

两份 package receipt 均记载 126 个归档文件；用户审计中的“125 个完整性文件”不应直接与归档计数混用，需核对是否包含清单文件及统计范围。

**当前本地 `dev/optimization-v27/package-manifest.json` 和 campaign 清单对应 r2；33376 跑的是 r1。** 审计33376要使用隔离解包的 r1 实现和清单，不能用当前 r2 清单造成错误的身份不一致结论，也不能改原结果使其匹配新清单。

各批次根目录内：

```text
dev/optimization-v27/runs/33376-main/queue-status.json
dev/optimization-v27/runs/33376-main/generation/status.json
dev/optimization-v27/runs/33376-main/generation/audit-results.json

dev/optimization-v27/runs/33589-context/queue-status.json
dev/optimization-v27/runs/33589-context/generation/status.json
dev/optimization-v27/runs/33589-context/generation/audit-results.json
```

33589 的本地同构目录还保存 `audit-remote.json` 与本地重审结果。回传要保留实际请求、完整回复、thinking、用量、新稿、公开测试台及工具日志；可不回传庞大的可再生成编译缓存。云端原件保留。

## 7. 接手检查与命令入口

在本地仓库根目录执行以下状态读取会通过 SSH 只读查询远端，但会更新本地 `launch-status.json`：

```bash
.venv/bin/python dev/optimization-v27/status.py
```

它只观察旧批次，不启动实验。旧文件中 21:21 的运行中状态不是最新状态；用户已提供 33376 于 21:37:59 完成的审计。没有活跃监控自动化可依赖，后续跟进需另明确安排。

快速回归入口（实现改动后运行；纯文档不要求重跑）：

```bash
.venv/bin/python -m unittest discover -s tests -q
```

v28 机械验证入口如下，输出目录必须新建身份、不得覆盖 `local-v1`／`local-v2`：

```bash
.venv/bin/python dev/optimization-v28/validate.py \
  --output dev/optimization-v28/runs/handoff-new-validation \
  --vivado-bin /home/cloudia/Downloads/FPGAVitis/2026.1/Vivado/bin
```

旧批次审计命令结构为 `对应冻结环境的 python dev/optimization-v27/audit.py <generation目录>`。此脚本会写 `audit-results.json`，不是纯只读工具；需要保留旧报告时在回传副本上执行。33376 必须配 r1 清单；33589 配 r2 清单。

不得直接重跑旧 `prepare.py` 覆盖已冻结包，或重新运行旧 `bootstrap.py` 追加／重启已完成批次。v27 bootstrap 的 campaign、任务和审计存在固定绑定；新批次须先制作新任务清单、策略身份与匹配 runner。交接编写时尚无已经启动的新批次；此后的 v29 小批次与评测进展见下方第 10 节。

## 8. 接下来按什么顺序做

1. **核对并归档现状。** 读取两机状态与 8010 健康、槽位，确认没有其他占用；定位／回传 33376 完成审计，保持 r1 身份。更新逐卡证据台账，不重复旧有效实验。
2. **本地持续制作。** 接通三条反馈谓词的版本化实验策略；优先选择有现成夹具的其他卡补准入。修 X/Z 数据域及独立期望表；收紧已有事实、冲突与不适用判断。每批约 8–10 张，不等整批全部完成才上传。
3. **33376 优先首次生成筛选。** 首批目标约 10 卡／20 次生成，新卡占主要名额，X/Z、切片各最多一个修订上下文；先统一 portable embedding 部署。只有就绪卡才启动，缺少首次生成谓词时可接收已就绪反馈任务。
4. **33589 跑反馈筛选与检索。** 首批目标约 10 卡／20 次生成，先含三条新反馈谓词；CPU embedding 穿插评测冻结查询，若资源争用影响生成则串行。
5. **扩大 embedding 评测。** 目标为 97 卡各三类查询槽位、约 291 条候选；标签独立冻结，不用查询数冒充卡覆盖。全目录与阶段池分别报告。BM25/dense 最终请求不同且合同有效时才做少量同机生成比较；相同完整请求复用，不重复计独立结果。
6. **边审边收尾。** 普通失败保留后继续，不自动重试；卡片退步暂停该版本追加，共享评分或身份异常暂停受影响队列。最后至少 20% 时间留给审计和回传。

新一轮初始目标 40 次生成，所有新卡、历史修订复测、拒绝抽查及检索器差异试验共享最多 60 次新增生成上限；这是计划预算，尚未消费。部署、夹具准备不足或剩余时间不足时主动减少，不为凑数量放宽准入。每机先完成三个配对后更新容量预测。

结果必须区分：候选／shadow／受限实验注入／待修订；机械通过／相关性召回／真实生成收益；新增开发家族／历史回归；新调用／相同请求复用；not_needed／unknown／failure。最终提供 97 张逐卡处置和未完成缺口，不承诺当天全量自动注入。

## 9. 必读入口

- [剩余时间的执行计划](2026-10-28-rag-final-day-batch-and-embedding-plan.md)：分工、查询覆盖与总预算。
- [三线部署历史](2026-10-28-rag-three-lane-cloud-plan.md)：许可证、r1/r2 与状态时间线。
- [v26 本地完成说明](../dev/optimization-v26/README.md)：真实 embedding、服务保护及研究发布边界。
- [v27 脚本说明](../dev/optimization-v27/README.md)：历史执行和审计机制，路径以本交接的 r1/r2 对照为准。
- [v28 开发准入](../dev/optimization-v28/README.md)：三条谓词及真实机械检查。
- [知识总记录](knowledge.md)：前序批次、失败修订与当前统计口径。

## 10. 本次续接增量

已按两份文档执行 v29 三卡受限反馈小批次、97 卡正向检索评测及两个历史合同修订预检。详见[本轮结果与剩余缺口](2026-10-28-rag-v29-progress.md)。新增生成 6/60 次，无自动重试；默认关闭状态与旧冻结身份保持不变。新运行目录和修订审计入口以该进展文档为准。
