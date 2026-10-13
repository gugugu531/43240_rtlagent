# RTL 小知识库：首批 15 张卡片

日期：2026-10-13。状态：开发原型，未接入 Agent、未参与当前 11 题实验。

这是 RAG（检索增强生成）的资料与检索准备部分：本地检索相关卡片，再把有限片段交给生成模型。
目前只实现了资料、检索和上下文打包，没有新增模型调用，也没有证明解题效果提升。
不需要 GPU、embedding 模型、Docker、向量数据库或在线知识库。

## 从哪里读

- [cards.json](cards.json)：15 张可检索卡片，以及 14 条来源记录。
- [NOTICE.md](NOTICE.md)：Ross 参考资料版权与许可。
- [实现与验收说明](../../docs/design/knowledge-cards.md)：字段、检索规则、适用边界与后续实验。

每张卡片包括适用条件、建议、验证方式、禁止盲用的边界、来源编号和资料核对状态。
全部标记为 `source_reviewed_draft / tool_validation=not_run`：核对资料不等于独立运行 HDL 验证。
`verify` 是未来应该执行的检查方法，不是已经执行的证明。

## 卡片目录

| 类型 | ID | 用途 |
| --- | --- | --- |
| 错误修复 | procedural-variable | 过程赋值目标声明 |
| 错误修复 | module-port-contract | 模块名与端口契约 |
| 错误修复 | syntax-local-context | 语法错误附近及前一语句 |
| 错误修复 | arithmetic-width | 算术位宽和截断 |
| 错误修复 | signedness | 有符号/无符号语义 |
| 错误修复 | shift-range | 移位量和有效范围 |
| 错误修复 | combinational-coverage | 组合赋值覆盖与锁存 |
| 错误修复 | driven-output-bits | 未驱动信号和输出位 |
| 错误修复 | reset-coverage | 复位覆盖与语句分组 |
| 设计检查 | reset-semantics | 同步/异步、极性、复位值 |
| 设计检查 | sequential-assignment | 状态更新与赋值语义 |
| 设计检查 | control-priority | 多控制同时有效 |
| 设计检查 | rotate-versus-shift | 旋转和普通移位的区别 |
| 设计检查 | counter-boundaries | 计数端点、终值事件 |
| 设计检查 | fsm-output-timing | 状态转移与输出时机 |

## 使用方法

以下命令均在 `43240-agent/` 下执行，只读本地文件，不调用模型或 Vivado。

```bash
# 检查资料结构和本地来源指纹
python3 dev/tools/knowledge_lookup.py validate --verify-sources

# 错误码检索：必须说明工具和适用版本
python3 dev/tools/knowledge_lookup.py search \
  --tool xvlog --version 2026.1 --code 'VRFC 10-1280'

# synth_design -lint 的规则，与 xvlog 错误不混用
python3 dev/tools/knowledge_lookup.py search \
  --tool vivado-lint --version 2026.1 --code ASSIGN-2

# 设计主题检索：不要求工具错误已经发生
python3 dev/tools/knowledge_lookup.py search --query '旋转和循环移位'

# 未知错误返回空，不偷偷用关键词当成确切修复
python3 dev/tools/knowledge_lookup.py search \
  --tool xvlog --version 2026.1 --query '[VRFC 10-9999] 过程赋值'
```

输出 JSON 包含命中原因、卡片和来源、内容哈希，以及可供以后使用的 `context.text`。
每次最多 2 张；默认 2400 个 Unicode 字符，超预算则整张省略，不截断卡片。
这不是 tokenizer 的 token 预算；未来接入模型时还需按实际 tokenizer 与总上下文预算处理。

11 个本地来源有文件 SHA256，可离线复核；2 条 AMD 在线文档只保留链接和查询日期，
另外 1 条为团队原创通用推导，不能把这三条描述成已下载并校验的文档副本。
运行检索无需 Ross 原仓库；只有 `validate --verify-sources` 才需要它来复核来源指纹。

## 我们没有照搬哪些建议

Ross 的指南面向通用工程，不能作为对比赛固定接口的无条件修改指令：

- 算术宽度不足不自动扩大端口，也不自动加饱和逻辑。
- 输出未驱动不允许删除题面要求的输出端口。
- 移位量超范围不自动裁剪成另一个数值。
- `$signed` 不能盲目套在本来表示无符号正数的对象上。
- 组合块每次执行时的无条件默认赋值，可以覆盖赋值路径；声明时的一次性初始化不能代替它。
  不能照搬 Ross INFER-1 中对这两种情况过度笼统的说法。
- 复位范围取决于规格，不任意给全部数据寄存器增加复位。

没有收录题号对应答案、官方 testbench、参考实现、隐藏判定日志或特定题目的完整代码。
卡片不得高于题面与实际工具证据；命中一张卡片不等于已诊断根因。

## 后续顺序

1. 用独立小例子做 HDL 验证，再提升卡片验证状态；当前加载器刻意只接受原型草稿状态，避免混淆。
2. 当前 11 题参数对照完成后，在新的独立 workflow 变体中接入检索，不修改本轮结果。
3. 分别比较结构化反馈与结构化反馈加短指南，记录修好、修坏、时延和 tokens。
4. 设计检查卡另做实验，不把修复检索和额外审查同时混入一次消融。
