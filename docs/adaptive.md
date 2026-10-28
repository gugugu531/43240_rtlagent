# 自适应工作流与检查

本页描述已实现的 `adaptive_verify`。`refactor/adaptive-orchestration` 分支的 `run.sh` 默认使用 `adaptive_verify`，显式 `AGENT_CONFIG` 仍可覆盖；`main` 在封存前保持 `single_generate`。机制验收、离线重放与真实小样本分别记录；`ready`、`approved`、`completed` 只表示对应阶段的状态，不代表题目功能正确或官方成绩。本版本已包含远端 llama.cpp 开发服务与 Vivado lint/综合的单题结构冒烟；未运行 xsim 或官方判定，正式 manifest 服务上的模型效果与检查器构造质量仍未验证。

## 工作流与恢复路径

主路径为 `analyze → generate（保存首稿）→ build_checker → review_checker → check → decide → repair → recheck → select → finish`。短分析每题一次，失败直接保守生成；完整首稿立即原子保存。首稿未形成且服务已返回有效响应时，最多一次 `rescue`：rescue 只用于补交首稿，取消检查器构造和正常修复，最终只做结构检查；rescue 提示携带首次调用的交付失败事实，缺失时明确记录而不伪造失败块。

恢复分三个通道，均无返回边；格式纠正与语义修订共用同一次检查器恢复机会（互斥），复核契约重试独立触发，但在预算上与语义修订互斥（重试已用后不再修订）：

1. **本地标点恢复**：构造回复是正常结束（`finish_reason=stop`）的完整 JSON 语法错误时，可进入 `correct_checker_format → review_checker → check`。恢复由本地代码执行，`model_calls=0`，最多 8 处标点编辑：只删除容器结束前的尾逗号、补齐文件末尾缺失的闭括号，或删除完整根对象后的多余闭括号。不移动已有内部层级，不补缺失键、值、冒号或内部隔断；无法识别字符串、截断、空正文、重复键、非有限数和 schema/语义错误都不触发。恢复后仍执行严格解析、接口/来源绑定、预检与独立复核；若复核拒绝，状态为 `rejected_after_format_correction`，不再发起语义修订。
2. **复核契约一次受控重试**：首次 `review` 返回 `invalid` 且冻结的检查器可重试（`retryable=true`）且尚未用过重试时，宿主用同一检查器、同一任务和上次契约违规列表（只含规则 ID、字段路径和宿主期望值，不含候选信息）发起一次 `review_retry`。重试只用于修正复核回复的契约字段/声明；`rereview` 永不重试。重试后若仍被正式拒绝，状态为 `rejected_after_review_retry` 并视为检查器恢复名额已用，不再进入语义修订。重试请求被预算拒绝时同样按已用处理，不退回第一次结果继续修订。
3. **语义修订**：只有通过 v2 复核契约、绑定原检查器与任务哈希的正式 `reject` 才允许 `revise_checker → rereview_checker → check`。修订输入只增加原检查器和绑定拒绝意见，不增加候选、实测或求解知识；修订后的检查器必须重新通过严格预检并重新复核，未获批准前不使用。格式纠正与语义修订共用同一次恢复机会。

第二次拒绝、未知、无效或请求不可用都继续结构检查，不自动重问。HTTP 结束未确认时不追加请求，已有候选继续保留。服务返回过深 JSON 或不能编码为 UTF-8 的字符串时，客户端保留原始响应并返回可处理的模型错误；已知 usage 不丢失，未知 usage 不记为零。

候选模块声明无法被接口解析器读取时，接口结果仍是 `error/unknown`，但允许编译器提供进一步诊断。只有明确的编译代码错误才能进入已有的一次修复；公开接口解析失败和确定的接口不匹配仍按原规则阻断编译。编译、综合成功不能把未解析接口变为通过：这类候选不执行功能采样，无法验证接口的子稿不晋升。最终结果单独给出 `interface_verified`，接口解析异常时 `structural_passed` 为 false。

## 公开输入、路由与 Skill

短分析请求提供带编号的公开原文目录，模型只选择 `requirement_ids`，宿主还原原文并严格绑定；未知/重复编号、混合编号和引用字段均拒绝。历史逐字引用输入仍可严格重放，但新请求不要求模型重新抄写原文。分析、构造及复核提示都以带编号的完整原文段落提供公开题面/接口，来源绑定及任务哈希继续使用未压缩的公开字段。

生成提示明确传入顶层名及公开接口的来源、可信程度、完整性和警告，缺失信息保持未定。首稿计划投影只含 `classification`（`kind`、`clocks`、`risks`）与 `ambiguities`，不发送 `rationale`、`route`、`model_cost` 或重复的 requirements；分类只是宿主路由元数据，不是已选实现。`repair.j2` 是新旧结构共享模板：`adaptive_verify` 传上述新投影，其它工作流传入的旧式计划仍按原设计计划段整体渲染。

检查路线只依据公开分析与宿主接口/表达能力限制，顺序为：接口未解析 → `inout` → 公开端口宽度超出 1..256 → 多时钟 → 以下三项能力门禁 → 无可依据检查范围 → 模型成本。三项新增门禁按顺序为：

- **无时钟 level-sensitive 存储**：分析认为有状态（`kind` 为 sequential/fsm/protocol 或含 `state_update` 风险）、`clocks` 为空、接口没有 1 位时钟名输入、题面没有明显时钟沿措辞，且题面出现 latch / level-sensitive / transparent / 锁存 / 电平敏感时，降为 `structural`，原因 `level_sensitive_storage_requires_clock`。不能仅凭“无时钟”降级，否则会误伤只有 next-state 组合逻辑的一热 FSM 题。
- **同端口双边沿**：题面明确出现双边沿（如 dual-edge、both the rising and falling edges、posedge and negedge）时降为 `structural`，原因 `dual_edge_clock_not_supported`。
- **异步复位 × properties**：题面有明确肯定异步复位要求且原路线为 `properties` 时，`model_cost=small` 改为 `model`，否则降为 `structural`，原因均为 `async_reset_needs_off_edge_observation`。properties 评估只保留时钟沿步，无法观测离边沿异步复位。

命中能力门禁或既有接口限制而走 `structural` 时，`uncovered` 追加 `behavior_not_checked`；此时不构造检查器，仍执行接口、lint、综合等结构检查，明确代码错误仍可触发一次修复，但不做功能行为检查。路由记录写入 `route.json` 的 `skill_candidates`、`reason`、`uncovered`；`skill_ids` 仅作为进程内只读别名。

Skill 候选来自 `route_skill_ids`：fsm 对应 FSM 方法，sequential/protocol 对应当前配置的时序方法，combinational 对应组合完整性方法，arithmetic 或 width/signed 风险追加宽度方法，最多两个。若 `analysis.clocks` 为空且（kind 为 sequential/protocol 或命中无时钟 latch 门禁），移除时序方法；候选在生成前仍要经过自动准入：只有默认冻结版本可自动准入，其它状态记录拒绝原因并继续无知识生成，实际发送看知识装配的 `skill_selected`/`sent`，不能把 `skill_candidates` 当成已发送。生成的 `sequential_skill` 在构图阶段用 catalog/资产校验自动准入，配置为未经批准的 v3 候选会在任何模型请求前报错停止，不再静默失效。checker 不消费 Skill、诊断卡、候选或实际输出。

本分支直接使用 `./run.sh <input> <output>` 即运行 `adaptive_verify`；需要对照旧流程时显式设置 `AGENT_CONFIG=config/single_generate.yaml`。HIP 服务使用 `config/adaptive_hip.yaml`；900 秒开发冒烟使用 `config/adaptive_dev_900.yaml`（8010 llama.cpp，非正式模型声明）。新预设默认连接真实服务，服务、模型和思考声明须在实验副本中核对。分支默认 `adaptive_verify.yaml` 的总时限为 9600 秒、收尾 120 秒，没有独立研究模式；默认预设 `adaptive_verify.yaml` 的阶段额度按 900 秒入口校准，外部更短时限仍按 `AGENT_DEADLINE_S` 生效。`params` 使用工作流的 `AdaptiveParameters` 严格校验，可调整阶段限额；阶段额度必须连同后继预留一起放入剩余工作时间。

## 检查器构造、归一化与预检证据

`adaptive_check` 的构造只接收公开 TaskSpec、原文引用目录和 DSL schema，不读取候选、实际输出、Skill 或求解分析。构造可返回 `status/checker` 外层对象或同路线的完整裸检查器对象，两种形式都执行完整 schema 与预检并记录 `response_form`；半个外层对象、未知字段和不合法状态仍拒绝。客户端严格解析 JSON，拒绝截断、重复键、未知字段和越界表达式；不可编码 Unicode 字符串与非有限数值同样按无效回复处理。

构造阶段只有两种审计过的机械归一化：

- **请求 route 回显**：仅当检查器对象根出现 `route`，且其值是字符串并与请求 route 逐字符相等时删除；值不等或非字符串直接判无效，嵌套 route 仍由严格 schema 拒绝。
- **冗余寄存器 clock**：仅当 `schema_version=1`、顶层 `clock` 是合法单值且无 `clocks`、`state` 非空且每个寄存器都是带 `clock` 的对象、所有寄存器 clock 都逐字符等于 legacy clock 端口时，删除各 `state.<name>.clock`；任一条件不满足保持原样，交由严格校验拒绝。

归一化只作用于上述来源形式，记录在 `checker-draft` 的 `preflight.normalization`：方法、`model_calls=0`、原始/归一化响应 SHA-256、`response_form`、被删除路径与原值（冗余 clock 另记 legacy clock）。`checker_hash` 对归一化后 payload 计算。复核输入摘要会移除 `response_form`、`format_correction`、`normalization` 等机械元数据，避免重复；冻结证据本身不裁剪。

构造预检新增两类只记录、不自动拒绝的形状摘要：行为路线 `expectation_shape` 给出全局与逐 requirement/逐输出的采样数、可比较位、期望 1 的数量、是否零变化或单侧，以及引文是否提到 1/复位；性质路线 `trigger_census` 用“输入确定、输出未知”的静态计算给出每个性质的预测触发数、不可确定数与空触发标记。这些摘要进入复核证据与日志，但不参与构造拒绝，也不代表实际执行或语义正确。

两条检查路线的公开端口宽度均须在 1..256 位，超限提前走结构检查，不裁剪端口或省略输出。紧凑静态 sequence/exhaustive 在宿主展开后重新检查。行为模型最多 8 个寄存器、128 个表达式节点；控制状态编码是寄存器的值，不另设编码数限制，数组须按实际展开成本计数。端口 signed 等题目语义仍需依据原题复核。

明确的异步复位要求会触发离边采样预检。题面和引用使用相同的局部语句判断，排除 `no asynchronous reset`、`asynchronous reset isn't required`、`不使用异步复位`等否定描述；一条复位的否定描述不会取消另一条肯定要求。肯定要求仍须有对应模型、肯定引用，以及先在非复位状态经过时钟、再在无有效时钟沿时采样复位断言的事件。此预检只识别明确常见句式，不替代语义复核。性质解释器本身仍只对时钟沿求值，无边沿即时异步复位不在其覆盖内；本题型的路线处理见上文路由门禁。

## 复核契约 v2

复核请求包含完整公开题面、route、checker_hash、检查器 payload、关键预检摘要、`review_contract_version=2`、`expected_table_sha256` 和 `review_evidence`。复核输入会移除预检中的重复逐事件输入/掩码/签名表和机械元数据，只保留汇总与证据；完整预检仍保存在 `checker-draft` 产物中，不裁剪冻结证据。`review_evidence` 只由检查器自身计算，独立于候选 RTL 与实测输出，边界字段明确为 `checker_only=true`、`candidate_rtl=false`、`dut_observations=false`：

- 行为路线：有效的采样期望表（最多 1024 行/32 KiB，超出按 case 摘要截断并保留完整表哈希）、覆盖摘要、`expectation_shape`、必须覆盖的表达式声明（全部 concat 节点与前 16 个 slice 节点）、phase/init/degenerate 声明集合与证据哈希。
- 性质路线：可确定的触发预测表（最多 512 行/16 KiB，超出截断并记录省略数）、覆盖摘要、`trigger_census`、按上限截断的必需触发声明（最多 64 条）与证据哈希。

复核响应必须是一个严格 JSON，字段集合精确为：`review_contract_version`、`checker_hash`、`expected_table_sha256`、`decision`、`reason`、`checked_requirements`、`requirement_reviews`、`claims`、`state_phase_claims`、`init_claims`、`degenerate_outputs`、`counterexamples`。宿主规则 R-00…R-12：

- **R-00/R-01**：单一、有界、可严格解析的 JSON；字段齐全且 `review_contract_version` 为整数 2。
- **R-02/R-03**：`decision` 只能是 accept/reject/unknown，`reason` 非空；必须回显冻结检查器哈希与宿主期望表哈希。
- **R-04/R-05**：`checked_requirements` 唯一且存在；accept 必须覆盖全部声明要求且每项 verdict 为 supported（出现 contradicted 或 insufficient 即不能 accept）。每项 review 的 verdict 为 supported/contradicted/insufficient 且不得重复，supported 必须带 witness；reject 时至少一项 contradicted 或 insufficient。
- **R-06**：witness 必须定位到真实 case/step，行为路线数值逐位等于宿主预测；性质路线校验可定位位置与可确定触发值。
- **R-07/R-07b**：typed claim（concat_arity、slice、ref、op、width、const、trigger）的 JSON Pointer 必须存在且值相等，claim 不得重复；行为路线必须覆盖全部 concat 节点和前 16 个 slice 节点。
- **R-08**：`state_phase_claims` 精确等于宿主集合（被输出引用的 state 记 NEW，`state.next` 引用的 state 记 OLD）；性质路线必须为空。
- **R-09**：`init_claims` 覆盖每个 state 寄存器，来源只能是允许集合（显式 initial / 异步复位赋值 / 无依据）。
- **R-10**：`degenerate_outputs` 精确等于宿主计算的全部采样期望相同的输出集合；性质路线必须为空。
- **R-11/R-12**：`counterexamples` 非空时 decision 必须为 reject；性质路线必需触发声明必须全部出现在 claims 且值相等。

`approve_review` 返回只读 `FrozenChecker`，除 status 外提供 `retryable`、`violations`、`review_record`。`retryable` 只在“违反复核契约、且 decision 不是 reject/unknown”时为真，因此错误拒绝不能通过重试进入修订；正式 `rejected` 只可能在全部规则通过时产生。旧 v1 复核响应缺少 v2 字段，一律 invalid，属于显式兼容边界。

复核只能给出 approved/rejected/unknown：approved 只允许主流程考虑修复，还必须有真实采样、实际比较和有效反例；同一模型的构造与复核不构成独立正确性证明。检查器修订前，宿主重新从 draft 计算 v2 证据并重跑契约校验，要求原拒绝是同一检查器、同一任务的合法正式拒绝；修订不得删除/重排旧 case 或屏蔽旧采样，仅可在末尾追加有界 case，并保留全部原 requirement ID/引用、采样端口/时钟和性质绑定。语义变更重新复核新哈希；未获批准前不使用。

## 归因与修复契约 v2

编译与功能修复共用一次名额；只有明确代码错误或获准检查器的有效反例才修。归因与完整 RTL 在同一请求中返回：请求的 `public_task` 含题面、原始 interface、顶层名、`expected_interface`（解析来源、端口方向/宽度、完整性与警告）和“缺失保持未定、原题优先”说明；证据包含已记录的反例、`failed_mismatches`（行为路线最多 32 条：model 为 case/step/signal/bit/expected/actual，properties 为 property/case/trigger_step/expected_holds/observed_holds）、结构诊断码和检查器 requirement ID。

响应 envelope 为：可选 fenced json 头 + 必须先于正文出现的 JSON + `rtl_error` 时紧随唯一完整 Verilog 代码块；拒绝重复键、额外正文、多个对象/代码块和截断。归因字段为 `attribution_contract_version`（必须为 2）、`decision`、`reason`、`candidate_conclusion`、`failure_binding`、`additional_recorded_mismatches`、`checker_defect`、`rtl_defect`、`requirement_id`、`public_quote`。A-00…A-08 校验：

- **A-00/A-01**：envelope 与长度上限；version=2 且必需字段齐全。
- **A-02**：decision 只能是 `rtl_error` / `checker_suspect` / `spec_unclear`，原因非空，`candidate_conclusion` 只能是 `unverified`（此阶段不能宣称候选正确）。
- **A-03**：行为证据必须回显已记录反例的全部绑定字段；properties 路线使用 `expected_holds`/`observed_holds`。
- **A-04**：`failure_binding.public_expectation` 是从公开题面重推的值，必须与 decision 一致：`rtl_error` 等于检查器期望值且不等于实测值，`checker_suspect` 等于实测值且不等于期望值，`spec_unclear` 可为 null。
- **A-05**：`requirement_id` 必须存在；`public_quote` 必须是公开题面或显式接口的逐字子串（空白规范化后比较）。
- **A-06**：`checker_suspect` 必须给出 `checker_defect` 对象，path 是检查器 payload 内存在的 JSON Pointer，claim 非空。
- **A-07/A-08**：`rtl_error` 必须给出 `rtl_defect`（非空 locations，可选 diagnostics）；结构类证据只能归因 `rtl_error`，所引诊断码必须来自请求证据；`additional_recorded_mismatches` 每项都必须命中已记录的 failed_mismatches，且长度有界。

只有 `rtl_error` 且返回完整、与父稿不同的 RTL 才产生子候选；`checker_suspect` 与 `spec_unclear` 撤销本次修复权限并直接结束，不改写候选。归因结论不修改已批准的检查器，修复后的子稿使用同一冻结检查器与计划重新采样与比较；`candidate_conclusion` 始终是 `unverified`，approved 不是真值，`checker_suspect` 也不证明候选正确。

## 采样与解释

`agent/domain/rtl/observation.py` 接收只含公开端口、静态输入和时钟事件的 SamplingPlan。每个 case 使用独立 DUT，`pre` 在输入驱动稳定后、有效沿前采样，`post` 在有效沿及非阻塞赋值稳定后采样。两相位都保存实际输入和输出，包括未知位掩码、候选哈希、采样计划哈希和独立 execution_id。缺行、重复、错宽度、错相位或驱动值不符都不能记为完成。`TraceRun.complete` 仅表示得到完整轨迹，不代表功能通过；Vivado 退出 0 也须检查实际采样及完成标记。

`observation.validate_trace()` 是两条解释路线共用的结构化记录校验入口，核对身份、每个 case 的顺序、时钟计数、采样标记、端口位宽和实际驱动值；不同 case 可以交错输出。`adaptive_execute.evaluate_model()` 将同一中立轨迹的 post 输出交给既有行为比较器；`compare_trace_rows()` 也供旧日志解析器使用，比较计数、掩码和未知值规则只有一份实现。期望值只从独立模型、输入和模型状态计算，不能读取 DUT 输出。`properties.evaluate_properties()` 使用公开端口、有限历史与触发快照计算局部性质；两条路线都使用同一采样器。

最多 8 个 case，总共 256 个事件；时序 case 最多 32 个事件，组合 case 最多 256 个。只支持组合或单时钟，输入必须每事件完整显式驱动，不根据 DUT 输出动态生成激励。公开接口必须能确定端口方向和宽度；接口解析保留已有端口列表，另支持明确的 Inputs/Outputs 章节及 Design Signature 顶层声明，矛盾或半截清单不能补猜为完整接口。

## 局部性质与异步复位

每条性质包含公开原文依据、触发条件、采样相位、响应窗口、断言和可选的有依据 abort。past 和窗口最多 16 个有效边沿，表达式使用定宽 AST，不支持任意 Python、内部信号、跨时钟历史或动态队列；每次触发独立计数，同一响应可能满足多个窗口，因此不证明事务一对一匹配。报告分别保存 satisfied、violated、unknown、incomplete、aborted、untriggered；未知触发不是 false、缺历史不是零、未结束窗口和零触发都不能通过。局部性质通过只证明声明的检查通过，不证明题目所有功能正确。

## 修复准入与选稿

`adaptive_selection` 统一判断修复准入和晋升：已归因的接口/编译/综合错误，或获准检查器的真实反例才能触发。模型结果按冻结模型重新计算期望并逐 bit 核对；性质按每个触发义务核对。子稿须绑定真实父稿、不同代码哈希、同一检查器与采样计划、独立执行身份，并通过必要结构检查及综合。

功能修复至少消除一个旧失败，保留全部旧通过项，不新增失败/unknown/未完成窗口；失败义务消失或被 abort 不算改善。结构修复必须消除旧代码阻断，已有功能证据同样不能退步。公开接口未验证及残余功能失败分别报告。采样器编译/展开时明确归因于候选代码的错误也属于结构修复触发，不能因尚无功能轨迹而漏掉。采样结果与其解释结果共享同一个真实 execution_id，这不代表执行了两次工具；父子候选仍必须独立重新采样。

`adaptive_assessment` 保存结构及共用的身份、绑定和结构错误校验；`CandidateAssessment`/`BehaviorAssessment` 的 `public_dict()` 保持原有日志字段并生成独立快照。带类型的对象本身不代表证据已获准，选稿仍校验完整快照；收尾只汇总当前结果，子稿晋升要求返回码、执行身份、父子关系及证据不退步，不共用一个“通过”判断。

## 答案提交与工具循环

`SubmissionGateway` 是唯一写 `solution.v` 的入口，使用 `CandidateStore.publish()` 原子替换。默认策略 `submission_policy=last_written`：首稿、修复稿和模型 `submit_answer` 登记的候选都会立即发布，最后一次写入生效；`selected_id` 仍由 `promotion_decision` 记录，收尾事件用 `overrode_selected` 标明是否覆盖了证据选稿。切换为 `selected` 只改该参数。`adaptive_finish` 与 `agent/main.py` 的收尾都会调用 `finalize()`，覆盖正常结束、截止、取消和异常路径。

`tool_steps` 默认 0，作者阶段仍为单次调用。设为大于 0 时，首稿/救援最多经过指定步数的模型-工具循环，白名单只有 `submit_answer` 与 `finish_task`；每一步都独立申请 completion 许可，因此会计入 `max_calls` 与输出 token 额度。工具创建的候选若还没有 `selected_id`，节点会按首稿兜底建立选择；否则 `selected` 策略会在收尾时找不到证据候选。实验配置为 `config/adaptive_tools.yaml`（`tool_steps: 2`），900 秒开发配置为 `config/adaptive_dev_900.yaml`。目标服务必须支持工具调用；llama.cpp 开发服务已验证返回 `tool_calls`，但未在正式 manifest 服务上验证，未验证前不进入正式默认配置。

模型 profile 按角色固定映射：分析者 `small`，作者、构造、复核、归因 `large`。配置在 `services.profiles`，未启用或未知 profile 回落主模型；只切换模型名、可选 base URL 和超时，思考设置仍取 manifest。每次模型调用在事件和 `request_outcomes` 中记录 `profile` 与实际 `model`。小模型候选为 `Nellyw888/VeriReason-Qwen2.5-1.5b-RTLCoder-Verilog-GRPO-reasoning-tb`；HF 模型卡未声明许可证，flat plan 输出格式尚未实测，仅 `guided_verify` 的抽象特征 planner 启用；`adaptive_verify` 的完整题面分析保持 `small.enabled: false`，否则 VeriReason 倾向直接输出 Verilog。服务在 8011，flat plan 已验证；许可证与 manifest 声明仍待补齐。

上下文装配在 `adaptive_analyze` 保存 `context-bundle.json`；生成前记录一次 `prompt/assembly`，包含保留/丢弃的知识条目、消息哈希和 token 估算。装配失败仍按知识层原有规则失败关闭，不改变原题文本。

## 预算、日志与诊断

以下为默认预设 `config/adaptive_verify.yaml` 的实际阶段参数；`AdaptiveParameters`
的宽预算默认值只在未显式覆盖时生效。

| 阶段 | 单次秒数 | 输出 token 上限 |
| --- | ---: | ---: |
| profile | 30 | 1024 |
| draft | 240 | 4096 |
| construction | 150 | 4096 |
| review | 90 | 2048 |
| review_retry | 90 | 2048 |
| revision | 90 | 4096 |
| rereview | 90 | 2048 |
| repair | 150 | 4096 |

最多 7 次 completion、65536 输出 tokens（含思考）；单次请求还受剩余上下文约束。首次工具组 120 秒，修稿工具组 120 秒，默认配置收尾预留 120 秒。默认预设的阶段额度按 900 秒入口校准：profile 的准入条件是 `30 + (240 + 120) = 390` 秒，首稿是 `240 + 120 = 360` 秒；两者在 900 秒扣除收尾预留后仍可通过。后续构造、复核、修订和修复仍按各自后继预留申请，预算不足时记录 `not_sent`，不保证八阶段全部发送。

completion 额度按路径计：首次复核直接批准的正常路径最多 5 次（含一次可能的 RTL 修复）；发生一次复核契约重试的路径最多 6 次；语义修订路径（复核→修订→重新复核→修复）最多 7 次。复核重试与检查器语义修订互斥：重试已用后，正式拒绝不再进入修订。`format_correction` 是本地计算，记录 `model_calls=0`，不消耗 completion 额度。后继预留由 `_rtl_followup` 和当前复核/修订限额动态计算；额度充足不代表应继续生成，阶段仍只执行一次。

`adaptive/` 保存分析/路由、请求额度与阶段结果、构造及复核、逐候选 assessment、修复证据、选稿理由和最终结果。关键产物：`checker-draft`/`checker-initial-review` 保留初版，`checker-revised-draft`/`checker-revised-review` 保留修订版，`checker-revision` 记录父哈希、修订绑定与请求状态；`review-contract` 按阶段记录复核的 attempts/status/violations/model_calls（发生重试时另有 retry_used/first_status/retry_status）；`rescue-context` 记录 rescue 是否带交付失败事实及原因；`repair-evidence`/`repair-decision` 保存修复输入证据与归因结论；`checker-format-correction` 记录原响应哈希、调用编号、本地编辑位置与新旧字符、结果哈希和零模型调用。`frozen-checker` 是最近一次实际完成的复核，重新复核未得到响应时仍可能是原拒绝结果，不能把文件存在当作批准；最新阶段状态看 `result.checker_status`。

`result` 分别给出交付、结构、声明检查、覆盖范围与未覆盖项，记录 `interface_verified`、`coverage_scope`、`semantic_completeness_proven`（始终为 false）、`review_contract`、`review_retry_used`、检查器修订/格式纠正和选稿结果。流程完成、局部性质通过及官方正确率是不同结论。

修复提示保留反例与有限历史，完整 reset 到失败轨迹保存在采样产物，压缩提示时明确 omitted 事件，不补造观测值。修复请求只在提示视图中合并重复诊断、去掉已逐字覆盖的 excerpt 行和不可访问日志路径，保留错误、行号、工具版本及候选绑定。

Vivado 摘要及结构化诊断先保留 ERROR、CRITICAL WARNING、FATAL（含无编号行），用剩余名额补 WARNING；输出仍按来源顺序，跨命令合并时全局按严重度优先。诊断上限、重复数量、消息裁剪和省略数量明确记录；`complete` 仅表示声明范围内诊断完整，不表示整个日志或 RTL 通过。warning 不会自动被归为代码失败，错误归因仍使用严格规则。

## 验证边界

`adaptive_check`、`adaptive_repair`、`adaptive_selection` 是纯契约层：它们只校验和记录宿主能机械判定的证据，不保证模型能写出合法契约、正确归因或在额度内完成修复。检查器构造与复核的输入边界、正式拒绝绑定和 v2 校验在离线重放中验证；辨别力验收使用合成实际轨迹，验证比较器能捕获指定 case/step/signal/位，并不是 RTL 仿真结果。真实 Vivado 仿真验收测试默认跳过，当前版本未执行。

离线重放与组件测试只说明“若模型给出契约形状，宿主能按规则判断”；真实模型下 v2 复核/归因首次通过率、重试次数与 token 增量未验证。旧 review 响应在新契约下 invalid 是显式兼容边界；旧批次的通过率、`ready`/`approved` 数量与官方成绩不因规则变化而改写。

本版本已包含远端 Qwen3.8-27B llama.cpp 与 Vivado 2026.1 的单题结构冒烟，但未做功能仿真或官方判定；宽预算实验仍不能当作符合 900 秒赛事预算的成绩。旧三条工作流的配置保持原样；本分支默认入口已切到 `adaptive_verify`，`main` 在封存前不变。
