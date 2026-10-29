# 97张研究卡：剩余工作逐卡清单

2026-10-29，日本时间。当前研究目录`rag-catalog-v3-rc4.2`；本页是第49批结束前的逐卡工作快照，不晋级资产。第49批完成结果、97卡本地修订和后续实验包已经转入[当前审计与实验交接](2026-10-29-rag-v49-audit-v51-package.md)；下表中“在途”文字仅保留历史快照含义。

97张已在统一129项目录中，与旧32张共享资产登记。这里的“入池”指获得指定阶段的受限注入权限；资产入库与模型请求中的实际发送是两个进度。

## 分类口径

下面是工作优先级，而非新的运行状态。真正可以优先进入受限路由验证的是2张；41张可优先补准入工程，但其中一部分只有历史保留配对，仍需核对当前渲染并验证独立题面合同。不能把全部41张称为“已证明只差三步”。

| 分类 | 数量 | 当前主要缺口 |
| --- | ---: | --- |
| 已有受限权限 | 5 | 已有指定范围的准入与真实首次路由证据；继续保持各自范围和默认策略。 |
| 最接近下一轮受限验证 | 2 | 当前正文首稿固定配对通过且有单样本效率信号；已有谓词，重点补独立合同、拒绝边界和真实首次路由。 |
| 已有谓词，先处理需求或成本 | 8 | 题面谓词已实现，已有开发拒绝测试；缺当前范围真实路由效果确认，且尚无一致收益，先收紧需求条件。 |
| 主要补准入与路由工程 | 41 | 已有机械/历史或修订配对基础，未发现需立即重写正文的未解决退步；按实际证据阶段补谓词、拒绝测试、独立合同及真实请求路由。 |
| 还需内容、合同或覆盖复核 | 15 | 除了准入与路由，还有已知长尾、旧退步或验证范围缺口；逐项处理后再考虑受限注入。 |
| 还需工具报告闭环 | 26 | 已有机械/工具事实证据，但缺唯一有效的生成修复评分及资源报告准入链路；不能用普通功能仿真代替映射验证。 |

15张已有运行时题面谓词：5张已有受限权限，另外10张仍是shadow。已有部分拒绝测试不等于每张都完成全部拒绝矩阵；真值必须来自实际题面、源码或工具证据。

## 最接近的两张

- `v9-public-block-carry-chain`：当前版本固定首稿配对两侧通过，2994→2177 token（−27.3%）。已有谓词；第49批前补了独立块/无跨块进位/高块carry-in固定为零的拒绝边界。下一步是独立上下文、冲突及已有事实拒绝、实际首次路由。
- `v9-public-batch-final-sample`：当前版本固定首稿配对两侧通过，4453→3004 token（−32.5%）。已有谓词；第49批前补了排除末样本和发布旧累加值的拒绝边界。下一步绑定批次长度、完成沿、valid和复位合同，再做真实首次路由。

这两张有单样本效率信号，尚没有稳定正确率收益证明。完成上述检查后再决定受限权限。

## 全量逐卡安排

### 已有受限权限：5张

已有指定范围的准入与真实首次路由证据；继续保持各自范围和默认策略。

| 卡片ID | 知识 | 证据/待办 |
| --- | --- | --- |
| `v8-packer-temporal-order` | Arrival order is a separate packing contract | 已有指定范围真实路由；packer仅pre_generation。继续保持合同与版本绑定。 |
| `v9-lang-conditional-x-merge` | Conditional unknown merges bits | 已有指定范围真实路由；packer仅pre_generation。继续保持合同与版本绑定。 |
| `v9-lang-indexed-select-constant-width` | Indexed selection separates base and width | 已有指定范围真实路由；packer仅pre_generation。继续保持合同与版本绑定。 |
| `v9-lang-nba-rhs-sampling` | Nonblocking assignment samples at execution | 已有指定范围真实路由；packer仅pre_generation。继续保持合同与版本绑定。 |
| `v9-public-sticky-event-memory` | A captured event remains pending | 已有指定范围真实路由；packer仅pre_generation。继续保持合同与版本绑定。 |

### 最接近下一轮受限验证：2张

当前正文首稿固定配对通过且有单样本效率信号；已有谓词，重点补独立合同、拒绝边界和真实首次路由。

| 卡片ID | 知识 | 证据/待办 |
| --- | --- | --- |
| `v9-public-batch-final-sample` | A completed batch includes its final accepted sample | 已有机械与配对基础。已有题面谓词；补需求/拒绝覆盖和真实路由。 |
| `v9-public-block-carry-chain` | Carry across arithmetic blocks | 历史配对保留；需回接实际渲染身份。已有题面谓词；补需求/拒绝覆盖和真实路由。 |

### 已有谓词，先处理需求或成本：8张

题面谓词已实现，已有开发拒绝测试；缺当前范围真实路由效果确认，且尚无一致收益，先收紧需求条件。

| 卡片ID | 知识 | 证据/待办 |
| --- | --- | --- |
| `v9-lang-arithmetic-right-sign` | Arithmetic shift depends on sign | 已有机械与配对基础。已有题面谓词；补需求/拒绝覆盖和真实路由。收益不一致或成本增加，先收紧注入需求。 第49批b49-09在途，尚未计成绩。 |
| `v9-lang-boolean-versus-bitwise` | Boolean reduction differs from bitwise masking | 历史配对保留；需回接实际渲染身份。已有题面谓词；补需求/拒绝覆盖和真实路由。收益不一致或成本增加，先收紧注入需求。 |
| `v9-lang-comparison-result-sign` | Comparison result is unsigned | 历史配对保留；需回接实际渲染身份。已有题面谓词；补需求/拒绝覆盖和真实路由。收益不一致或成本增加，先收紧注入需求。 |
| `v9-lang-context-before-operation` | Context propagates before evaluation | 已有机械与配对基础。已有题面谓词；补需求/拒绝覆盖和真实路由。收益不一致或成本增加，先收紧注入需求。 第49批b49-11在途，尚未计成绩。 |
| `v9-lang-unsigned-negative-check` | Unsigned negativity check is constant | 历史配对保留；需回接实际渲染身份。已有题面谓词；补需求/拒绝覆盖和真实路由。收益不一致或成本增加，先收紧注入需求。 |
| `v9-public-bounded-modulus` | Storage width does not define the requested modulus | 已有机械与配对基础。已有题面谓词；补需求/拒绝覆盖和真实路由。收益不一致或成本增加，先收紧注入需求。 |
| `v9-public-sampled-edge-history` | An edge requires previous and current samples | 已有机械与配对基础。已有题面谓词；补需求/拒绝覆盖和真实路由。收益不一致或成本增加，先收紧注入需求。 |
| `v9-public-saturation-not-wrap` | Saturating boundaries hold rather than wrap | 已有机械与配对基础。已有题面谓词；补需求/拒绝覆盖和真实路由。收益不一致或成本增加，先收紧注入需求。 |

### 主要补准入与路由工程：41张

已有机械/历史或修订配对基础，未发现需立即重写正文的未解决退步；按实际证据阶段补谓词、拒绝测试、独立合同及真实请求路由。

| 卡片ID | 知识 | 证据/待办 |
| --- | --- | --- |
| `v8-bcd-decimal-carry` | Decimal carry must use the full digit sum | 历史配对保留；需回接实际渲染身份。补阶段适配谓词、拒绝测试和真实路由。首次生成阶段尚未发布；若题面证据不足，保留反馈路径。 |
| `v8-pipeline-valid-alignment` | Valid tracks the same accepted transaction as result | 已有机械与配对基础。补阶段适配谓词、拒绝测试和真实路由。首次生成阶段尚未发布；若题面证据不足，保留反馈路径。 第49批b49-04在途，尚未计成绩。 |
| `v8-ram-port-write-mode` | RAM read-during-write is mode-dependent | 已有机械与配对基础。补阶段适配谓词、拒绝测试和真实路由。首次生成阶段尚未发布；若题面证据不足，保留反馈路径。 第49批b49-05在途，尚未计成绩。 |
| `v8-serializer-snapshot` | Serial bits belong to one accepted word | 已有机械与配对基础。补阶段适配谓词、拒绝测试和真实路由。首次生成阶段尚未发布；若题面证据不足，保留反馈路径。 第49批b49-07在途，尚未计成绩。 |
| `v8-stack-boundary-guards` | Illegal stack operations do not move occupancy | 已有机械与配对基础。补阶段适配谓词、拒绝测试和真实路由。首次生成阶段尚未发布；若题面证据不足，保留反馈路径。 第49批b49-08在途，尚未计成绩。 |
| `v9-lang-comb-read-before-write` | Combinational source order matters | 历史配对保留；需回接实际渲染身份。补阶段适配谓词、拒绝测试和真实路由。首次生成阶段尚未发布；若题面证据不足，保留反馈路径。 |
| `v9-lang-concat-signedness` | Concatenation drops signedness | 历史配对保留；需回接实际渲染身份。补阶段适配谓词、拒绝测试和真实路由。首次生成阶段尚未发布；若题面证据不足，保留反馈路径。 |
| `v9-lang-const-not-parameter` | Const is not an elaboration parameter | 已有机械与配对基础。补阶段适配谓词、拒绝测试和真实路由。首次生成阶段尚未发布；若题面证据不足，保留反馈路径。 第49批b49-10在途，尚未计成绩。 |
| `v9-lang-division-rounding` | Signed division truncates | 已有机械与配对基础。补阶段适配谓词、拒绝测试和真实路由。首次生成阶段尚未发布；若题面证据不足，保留反馈路径。 |
| `v9-lang-empty-star-events` | Empty implicit event set | 已有机械与配对基础。补阶段适配谓词、拒绝测试和真实路由。首次生成阶段尚未发布；若题面证据不足，保留反馈路径。 |
| `v9-lang-lhs-not-sign-coercion` | Destination sign is insufficient | 历史配对保留；需回接实际渲染身份。补阶段适配谓词、拒绝测试和真实路由。首次生成阶段尚未发布；若题面证据不足，保留反馈路径。 |
| `v9-lang-overlapping-case-order` | Overlapping case order matters | 已有机械与配对基础。补阶段适配谓词、拒绝测试和真实路由。首次生成阶段尚未发布；若题面证据不足，保留反馈路径。 第49批b49-12在途，尚未计成绩。 |
| `v9-lang-remainder-sign` | Remainder follows dividend | 历史配对保留；需回接实际渲染身份。补阶段适配谓词、拒绝测试和真实路由。首次生成阶段尚未发布；若题面证据不足，保留反馈路径。 |
| `v9-lang-same-process-nba-order` | Same-process overlapping NBA priority | 已有机械与配对基础。补阶段适配谓词、拒绝测试和真实路由。首次生成阶段尚未发布；若题面证据不足，保留反馈路径。 |
| `v9-lang-sign-conversion-width` | Sign conversion preserves width | 历史配对保留；需回接实际渲染身份。补阶段适配谓词、拒绝测试和真实路由。首次生成阶段尚未发布；若题面证据不足，保留反馈路径。 |
| `v9-lang-size-cast-sign` | Size cast preserves sign | 已有机械与配对基础。补阶段适配谓词、拒绝测试和真实路由。首次生成阶段尚未发布；若题面证据不足，保留反馈路径。 |
| `v9-public-am-pm-phase` | AM/PM transition is not the hour wrap transition | 已有机械与配对基础。补阶段适配谓词、拒绝测试和真实路由。首次生成阶段尚未发布；若题面证据不足，保留反馈路径。 第49批b49-13在途，尚未计成绩。 |
| `v9-public-carry-lookahead-composition` | Compose carry generate and propagate over ordered groups | 已有机械与配对基础。补阶段适配谓词、拒绝测试和真实路由。首次生成阶段尚未发布；若题面证据不足，保留反馈路径。 第49批b49-14在途，尚未计成绩。 |
| `v9-public-cellular-snapshot-update` | All cells use one previous generation | 已有机械与配对基础。补阶段适配谓词、拒绝测试和真实路由。首次生成阶段尚未发布；若题面证据不足，保留反馈路径。 第49批b49-15在途，尚未计成绩。 |
| `v9-public-convolution-memory-depth` | Constraint length includes the current input | 已有机械与配对基础。补阶段适配谓词、拒绝测试和真实路由。首次生成阶段尚未发布；若题面证据不足，保留反馈路径。 第49批b49-16在途，尚未计成绩。 |
| `v9-public-division-equality-boundary` | Restoring division includes equality in subtraction | 历史配对保留；需回接实际渲染身份。补阶段适配谓词、拒绝测试和真实路由。首次生成阶段尚未发布；若题面证据不足，保留反馈路径。 |
| `v9-public-division-remainder-invariant` | Unsigned quotient and remainder satisfy one identity | 已有机械与配对基础。补阶段适配谓词、拒绝测试和真实路由。首次生成阶段尚未发布；若题面证据不足，保留反馈路径。 第49批b49-17在途，尚未计成绩。 |
| `v9-public-fractional-period-duty` | Fractional ratio does not uniquely determine duty cycle | 已有机械与配对基础。补阶段适配谓词、拒绝测试和真实路由。首次生成阶段尚未发布；若题面证据不足，保留反馈路径。 |
| `v9-public-framing-search-phase` | Start markers are interpreted only while searching | 已有机械与配对基础。补阶段适配谓词、拒绝测试和真实路由。首次生成阶段尚未发布；若题面证据不足，保留反馈路径。 第49批b49-18在途，尚未计成绩。 |
| `v9-public-hdlc-run-classification` | Stuffed data and framing runs have distinct meanings | 已有机械与配对基础。补阶段适配谓词、拒绝测试和真实路由。首次生成阶段尚未发布；若题面证据不足，保留反馈路径。 |
| `v9-public-instruction-bank-isolation` | A selected write preserves unrelated banks | 已有机械与配对基础。补阶段适配谓词、拒绝测试和真实路由。首次生成阶段尚未发布；若题面证据不足，保留反馈路径。 第49批b49-19在途，尚未计成绩。 |
| `v9-public-iterative-product-restart` | A new multiply does not inherit the previous sum | 已有机械与配对基础。补阶段适配谓词、拒绝测试和真实路由。首次生成阶段尚未发布；若题面证据不足，保留反馈路径。 |
| `v9-public-johnson-orbit` | A Johnson sequence is not a binary count | 已有机械与配对基础。补阶段适配谓词、拒绝测试和真实路由。首次生成阶段尚未发布；若题面证据不足，保留反馈路径。 |
| `v9-public-mixed-radix-time-rollover` | Cascaded time fields use their own moduli | 已有机械与配对基础。补阶段适配谓词、拒绝测试和真实路由。首次生成阶段尚未发布；若题面证据不足，保留反馈路径。 |
| `v9-public-odd-divider-duty-limit` | Odd periods cannot have equal integer half-periods | 已有机械与配对基础。补阶段适配谓词、拒绝测试和真实路由。首次生成阶段尚未发布；若题面证据不足，保留反馈路径。 |
| `v9-public-pause-preserves-subtick` | Pause preserves fractional progress when specified | 已有机械与配对基础。补阶段适配谓词、拒绝测试和真实路由。首次生成阶段尚未发布；若题面证据不足，保留反馈路径。 第49批b49-20在途，尚未计成绩。 |
| `v9-public-progression-first-term` | The initial term is not an incremented term | 已有机械与配对基础。补阶段适配谓词、拒绝测试和真实路由。首次生成阶段尚未发布；若题面证据不足，保留反馈路径。 |
| `v9-public-ring-onehot-invariant` | Rotation preserves the number of asserted state bits | 已有机械与配对基础。补阶段适配谓词、拒绝测试和真实路由。首次生成阶段尚未发布；若题面证据不足，保留反馈路径。 |
| `v9-public-sequence-prefix-fallback` | Mismatch fallback may preserve a useful suffix | 已有机械与配对基础。补阶段适配谓词、拒绝测试和真实路由。首次生成阶段尚未发布；若题面证据不足，保留反馈路径。 |
| `v9-public-serial-error-rearm` | A bad stop symbol requires an explicit recovery phase | 已有机械与配对基础。补阶段适配谓词、拒绝测试和真实路由。首次生成阶段尚未发布；若题面证据不足，保留反馈路径。 |
| `v9-public-signed-subtract-overflow` | Subtraction overflow depends on operand signs | 历史配对保留；需回接实际渲染身份。补阶段适配谓词、拒绝测试和真实路由。首次生成阶段尚未发布；若题面证据不足，保留反馈路径。 |
| `v9-public-speculation-rollback-priority` | Recovery discards younger speculative history | 已有机械与配对基础。补阶段适配谓词、拒绝测试和真实路由。首次生成阶段尚未发布；若题面证据不足，保留反馈路径。 |
| `v9-public-toggle-divider-period` | A toggle interval is half an output period | 已有机械与配对基础。补阶段适配谓词、拒绝测试和真实路由。首次生成阶段尚未发布；若题面证据不足，保留反馈路径。 |
| `v9-public-unsigned-borrow-not-sign` | Unsigned borrow is not the truncated result sign | 历史配对保留；需回接实际渲染身份。补阶段适配谓词、拒绝测试和真实路由。首次生成阶段尚未发布；若题面证据不足，保留反馈路径。 |
| `v9-public-weighted-partial-products` | Partial products preserve bit-position weights | 已有机械与配对基础。补阶段适配谓词、拒绝测试和真实路由。首次生成阶段尚未发布；若题面证据不足，保留反馈路径。 |
| `v9-tool-synthesis-excluded-functional-code` | Synthesis exclusion pragmas can hide functional behavior | 已有机械与配对基础。补阶段适配谓词、拒绝测试和真实路由。首次生成阶段尚未发布；若题面证据不足，保留反馈路径。 |

### 还需内容、合同或覆盖复核：15张

除了准入与路由，还有已知长尾、旧退步或验证范围缺口；逐项处理后再考虑受限注入。

| 卡片ID | 知识 | 证据/待办 |
| --- | --- | --- |
| `v8-lfsr-feedback-seed` | Feedback polarity determines absorbing seed states | 旧配对两侧通过，但卡片成本增加281.7%，分析曾质疑正确递推；先审查反馈极性/seed边界和重复事实。 第49批b49-01在途，尚未计成绩。 |
| `v8-packer-valid-count` | Pack accepted items rather than adjacent clock cycles | 旧配对两侧通过，成本增加48.6%；先区分接受事件与周期计数的信息增量，并检查气泡、复位和完成沿。 第49批b49-02在途，尚未计成绩。 |
| `v8-pipeline-operand-cohort` | Partial arithmetic must use one transaction's operands | 旧配对代码相同，成本增加27.9%；需绑定实际事务、流水级及同批操作数，单独的流水主题不足以准入。 第49批b49-03在途，尚未计成绩。 |
| `v8-result-backpressure-retention` | Unconsumed result is not a completed transfer | 旧配对两侧通过，成本增加26.7%；需绑定ready/valid、接受沿和保持合同，检查背压与新结果同时出现的边界。 第49批b49-06在途，尚未计成绩。 |
| `v9-lang-based-literal-sign` | Based literal sign marker | 历史样例有边界常数改错风险；v32虽两侧通过，卡片成本仍增加38.0%；需复核数值边界与signed位模式。 |
| `v9-lang-mixed-sign-arithmetic` | Unsigned arithmetic operand changes interpretation | 最新正文两组均通过，旧语法/零扩展退步已修订；但最新两组成本分别增加11.6%和22.6%，落实方式仍不稳定。 |
| `v9-lang-slice-signedness` | Selection drops signedness | 保留历史配对成本增加66.1%；需绑定实际切片、signed来源和目标表达式，并回接开发结构谓词。 |
| `v9-public-fp-exponent-bias` | Multiplication removes one exponent bias | 现有窄夹具通过，不覆盖完整浮点；先限定格式、正规/非正规数和特殊值适用域，再设计需求谓词。 |
| `v9-public-fp-normal-hidden-bit` | Implicit significand bit depends on operand class | 现有窄夹具通过；需明确正规数前提、指数为零和特殊值，不能把隐含1应用到所有编码。 |
| `v9-public-fp-round-renormalize` | Rounding can require a second normalization | 现有窄夹具通过；需限定舍入模式并覆盖舍入进位、指数溢出与特殊值边界。 |
| `v9-public-fp-sticky-rounding` | Discarded low bits participate in rounding | 现有窄夹具通过；需限定舍入合同、guard/round/sticky位置及tie场景，不能泛化成完整浮点正确性。 |
| `v9-public-grid-row-column-wrap` | Toroidal neighborhoods wrap each coordinate separately | 修订后配对通过，早期存在未交付；需独立网格合同与索引位宽边界确认，限制为可证明的局部邻居修改。 |
| `v9-public-gshare-training-context` | Training indexes the original prediction context | 曾有一次救援，但已审计记录指出模型样例只有一个公开断言；先补预测/训练跨周期、别名及更新时刻覆盖。 |
| `v9-public-serial-sampling-vs-latch` | A latch event follows the last sampling edge | 修订后救援通过，历史存在未交付和长尾；需继续绑定最后采样沿、后一沿latch、气泡、连续帧及复位。 |
| `v9-public-triangle-endpoint-dwell` | Endpoint dwell is separate from count direction | 修订后两侧通过，历史存在相位反推和未交付；需独立端点驻留/复位相位合同，不能仅靠主题路由。 |

### 还需工具报告闭环：26张

已有机械/工具事实证据，但缺唯一有效的生成修复评分及资源报告准入链路；不能用普通功能仿真代替映射验证。

| 卡片ID | 知识 | 证据/待办 |
| --- | --- | --- |
| `v9-lang-case-equality-synthesis` | Case equality is not an X detector in hardware | 机械/工具事实已留存；补工具版本、器件、约束、资源报告绑定与有效评分。 |
| `v9-lang-delay-not-hardware` | Procedural delay is not a hardware timer | 机械/工具事实已留存；补工具版本、器件、约束、资源报告绑定与有效评分。 |
| `v9-tool-bram-byte-column-shape` | Byte-enable inference depends on write-column shape | 机械/工具事实已留存；补工具版本、器件、约束、资源报告绑定与有效评分。 |
| `v9-tool-direct-enable-selection` | DIRECT_ENABLE can override data-path enable mapping | 机械/工具事实已留存；补工具版本、器件、约束、资源报告绑定与有效评分。 |
| `v9-tool-direct-reset-selection` | DIRECT_RESET can choose which reset uses the dedicated pin | 机械/工具事实已留存；补工具版本、器件、约束、资源报告绑定与有效评分。 |
| `v9-tool-dsp-adder-mapping-default` | An adder is not automatically mapped like a multiplier | 机械/工具事实已留存；补工具版本、器件、约束、资源报告绑定与有效评分。 |
| `v9-tool-dsp-attribute-scope-priority` | A signal-level DSP directive can override a broader directive | 机械/工具事实已留存；补工具版本、器件、约束、资源报告绑定与有效评分。 |
| `v9-tool-dsp-pipeline-utilization` | DSP pipeline stages require explicit latency agreement | 机械/工具事实已留存；补工具版本、器件、约束、资源报告绑定与有效评分。 |
| `v9-tool-dsp-register-control-compatibility` | DSP48 register controls restrict direct absorption | 机械/工具事实已留存；补工具版本、器件、约束、资源报告绑定与有效评分。 |
| `v9-tool-dsp-signed-capacity` | Unsigned operands can consume DSP sign capacity | 机械/工具事实已留存；补工具版本、器件、约束、资源报告绑定与有效评分。 |
| `v9-tool-dsp-symmetric-preadder` | Symmetric filters can use a DSP pre-adder | 机械/工具事实已留存；补工具版本、器件、约束、资源报告绑定与有效评分。 |
| `v9-tool-extract-reset-sync-only` | EXTRACT_RESET does not control asynchronous-reset mapping | 机械/工具事实已留存；补工具版本、器件、约束、资源报告绑定与有效评分。 |
| `v9-tool-fsm-safe-default-target` | A safe-state default target must exist in the RTL | 机械/工具事实已留存；补工具版本、器件、约束、资源报告绑定与有效评分。 |
| `v9-tool-fsm-safe-fault-model` | Safe-state modes cover particular encoding fault models | 机械/工具事实已留存；补工具版本、器件、约束、资源报告绑定与有效评分。 |
| `v9-tool-ram-address-feedback` | Address-register feedback can block RAM packing | 机械/工具事实已留存；补工具版本、器件、约束、资源报告绑定与有效评分。 |
| `v9-tool-ram-array-runtime-reset` | Whole-array runtime reset is not a block-RAM output reset | 机械/工具事实已留存；补工具版本、器件、约束、资源报告绑定与有效评分。 |
| `v9-tool-ram-initialization-not-runtime-reset` | Configuration contents and runtime clearing are different operations | 机械/工具事实已留存；补工具版本、器件、约束、资源报告绑定与有效评分。 |
| `v9-tool-ram-output-async-reset` | Asynchronous output reset can prevent BRAM register absorption | 机械/工具事实已留存；补工具版本、器件、约束、资源报告绑定与有效评分。 |
| `v9-tool-ram-output-fanout` | Additional fanout blocks the documented BRAM output packing | 机械/工具事实已留存；补工具版本、器件、约束、资源报告绑定与有效评分。 |
| `v9-tool-register-reset-ce-priority` | Reset-first coding matches dedicated register control priority | 机械/工具事实已留存；补工具版本、器件、约束、资源报告绑定与有效评分。 |
| `v9-tool-sdp-collision-bypass` | Registered-address SDP collision can need explicit bypass | 机械/工具事实已留存；补工具版本、器件、约束、资源报告绑定与有效评分。 |
| `v9-tool-srl-dynamic-tap` | Dynamic SRL addressing selects an existing stored tap | 机械/工具事实已留存；补工具版本、器件、约束、资源报告绑定与有效评分。 |
| `v9-tool-srl-extraction-precedence` | SRL extraction disabling outranks style and global threshold | 机械/工具事实已留存；补工具版本、器件、约束、资源报告绑定与有效评分。 |
| `v9-tool-srl-output-register` | A final slice register can improve SRL output timing | 机械/工具事实已留存；补工具版本、器件、约束、资源报告绑定与有效评分。 |
| `v9-tool-srl-reset-emulation` | SRL reset behavior may require surrounding logic | 机械/工具事实已留存；补工具版本、器件、约束、资源报告绑定与有效评分。 |
| `v9-tool-srl-style-static-only` | SRL_STYLE boundary-register choices are for static SRLs | 机械/工具事实已留存；补工具版本、器件、约束、资源报告绑定与有效评分。 |

## 接下来的执行次序

1. 先完成第49批的真实日志审计，并把当前版本退步、未交付和长尾回填台账。该批复用历史夹具并换seed，不增加独立上下文计数。
2. 优先为分块进位、批次末样本补真实题面路由。随后从41张工程候选中选择能从公开题面完整确定合同的低风险卡，一批补约10个谓词及拒绝矩阵。
3. 同一进程NBA覆盖、组合读写次序、const/parameter等方法需要源码或诊断定位时，优先开发反馈准入；只有题面明示必要结构时才加首次生成权限。
4. 8张已有谓词但收益不一致的卡先留shadow，15张复核组按具体风险补覆盖；26张工具卡单独建立综合/映射评分流程。
5. 已有事实、不适用、缺合同和资产异常先用真实装配测试证明请求行为；模型调用集中用于实际发送内容发生变化的情况。

原始证据：`dev/optimization-v36/card-ledger.json`、`dev/optimization-v38/campaign-audit-*.json`、`dev/optimization-v43/summary.json`、`dev/optimization-v46/summary.json`。当前快照含全部来源哈希与逐卡字段：`dev/optimization-v50/card-readiness-inventory.json`。历史v36有一份记录脱敏损坏的已知限制；本整理不重新认证该原始thinking。

## 第49批远端进度快照

2026-10-29 12:29:45，日本时间，只读检查：

| 主机 | 已完成配对 | 当前卡 | 已完成尝试交付/通过 | 当前服务 |
| --- | ---: | --- | --- | --- |
| 33376 | 6/10 | b49-07，serializer快照 | 12/12交付、12/12通过 | 模型正在处理 |
| 33589 | 5/10 | b49-16，卷积存储深度 | 10/10交付、10/10通过 | 模型正在处理 |

合计11/20配对结束、22次尝试结束，两臂各11/11交付和通过。当前两张卡均已通过远端三变体机械预检；33376已发起当前第1臂，33589已发起当前第2臂。上述为运行记录读取，尚未完成全批真实请求、thinking、用量及评分哈希审计，不计为正式晋级。队列未发现已完成卡的环境/生成/评分失败，无重启或重试。

从启动至本次检查约11.6分钟，按已完成卡的速度估算剩余约10–20分钟；若后续出现800秒级长调用则会延长。完整快照为`dev/optimization-v50/progress-33376.json`和`progress-33589.json`。
