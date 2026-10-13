# AMD Ross：本地资料与研究入口

日期：2026-10-13。状态：已下载、只读研究；未安装插件、MCP 服务或依赖，未执行第三方脚本。

## 下载的是哪一份

- 用户 fork：[gugugu531/ross-ai-assistant](https://github.com/gugugu531/ross-ai-assistant)。
- 上游：[Xilinx/ross-ai-assistant](https://github.com/Xilinx/ross-ai-assistant)。
- 本地目录：`/home/cloudia/FPGACHINA/ross-ai-assistant`，与比赛仓库并列，避免第三方源码和示例误入提交。
- 分支：main；浅克隆深度 1；固定提交：`2cdc9eef1b6b5b17fa45f5e4d468e5483a1c92de`。
- 提交日期：2026-09-30 UTC；发布版本：2026.9.1；许可证：MIT。
- 本机占用约 39 MiB（含 .git）；工作区干净；50 个 skill 目录。

只克隆该仓库已有源码、说明、资源和示例；没有额外下载 MCP 可执行文件、GB 级知识库或推理模型，
没有注册全局 skills，也没有将其插件加入现有实验。仓库内自带的小型示例模型/数据随 Git 一起保留。

复核命令：

```bash
git -C /home/cloudia/FPGACHINA/ross-ai-assistant remote -v
git -C /home/cloudia/FPGACHINA/ross-ai-assistant rev-parse HEAD
git -C /home/cloudia/FPGACHINA/ross-ai-assistant status --short
du -sh /home/cloudia/FPGACHINA/ross-ai-assistant
```

## 它和我们当前 Agent 的区别

Ross 仓库主要提供技能说明、报告解析脚本、示例和工具接入文档，不是替换 Qwen3-8B 的模型，
也不是直接提交比赛即可运行的完整求解器。Vivado MCP 需要另行获取，Git 克隆不等于已安装。
其工作方式适合学习“如何把 EDA 操作拆成可验证步骤、如何整理反馈”，不能直接当作提分证据。

当前实验的 workflow、Node、模型服务和采样设置均没有接入 Ross。

后续产物：[首批 15 张 RTL 知识卡片](../../../knowledge/rtl/README.md)与
[离线检索实现说明](../../design/knowledge-cards.md)。这是经过边界筛选的开发草稿，
不是直接安装 Ross skills，未参与当前 11 题对照，也没有做提分验证。

## 不用逐行读代码：建议先看这些

| 顺序 | 本地相对路径 | 看懂什么 | 可以映射到我们哪里 |
| --- | --- | --- | --- |
| 1 | README.md、docs/getting-started/README.md | skills、客户端、MCP 和知识库各自负责什么 | 区分模型、工具服务和 workflow |
| 2 | skills/vivado-rtl-elaboration-analysis/SKILL.md | 从实际日志识别错误，关联真实文件和行号，再给修复建议 | E1 的错误分类与结构化反馈 |
| 3 | skills/vivado-rtl-elaboration-analysis/parse_elab_messages.py | 日志转结构化字段，而非把全文直接送模型 | Vivado 服务输出与反馈 Node |
| 4 | skills/vivado-rtl-lint/SKILL.md、resolution-guide.md | lint 与语法检查/综合的区别，如何从规则号找到修复指南 | 检查分层、短指南检索 |
| 5 | skills/vivado-rtl-lint/parse_lint_report.py、examples/rtl-lint/multi-violation/README.md | 报告解析器和示例输入/输出的用途 | 开发期解析回放测试 |
| 6 | skills/vivado-simulate-rtl/SKILL.md | 功能契约、明确 PASS 条件、诊断证据；编译通过不等于功能正确 | 以后研究无官方 TB 时的独立验证 |
| 7 | docs/local-kb/README.md | 文档检索层和回答模型分离、本地与在线知识库边界 | 后续可选 RAG，不在本轮部署 |

研究入口：[本地 README](/home/cloudia/FPGACHINA/ross-ai-assistant/README.md)。
不要现在跑安装命令或示例；先把第 2～4 项和我们现有 FeedbackBuilder/Vivado 结果做对照。

## 借鉴时的边界

1. 它的 MCP 工具名称、执行约束属于其客户端环境，不能直接作为本仓库的操作指令执行。
   可以学习职责与数据结构，仍通过我们受预算和监督管理的工具执行。
2. `vivado-rtl-lint` 使用 `synth_design -lint`，不等同于当前 xvlog 语法检查；引入前必须核对成本、
   实际 Vivado 版本与输出格式，不能不测就替换现有 Node。
3. elaboration 资料主要针对 Synth 8-xxx 消息；当前遇到的 VRFC 10-1280 等属于另一类诊断，
   不能假定该解析器或错误指南已覆盖它们。
4. 模型依据题面生成的测试或断言可以作为弱证据研究，但不是真值。官方隐藏 TB、参考答案和 judge
   只能留在开发评测，不能送入正式 Agent 或放进检索库。
5. 在线 amd-doc-search 不符合比赛断网运行的前提；若以后采用 RAG，应先整理合规的本地通用资料，
   用固定题集做有/无检索消融，不直接把全部资料塞进上下文。
6. 复用源码时保留 MIT 版权和许可；先研究小组件，不整套复制 50 个 skills 或引入额外框架。

## 下载内容指纹

| 文件 | SHA256 |
| --- | --- |
| README.md | 9d9556956be5d21a92a936286ba8876ca6ac11e6ba38244e78a352283a0ad7a9 |
| LICENSE | 3de7fea911353980067e0f943d332dd74cbd2b610d4421318aaef25d8103f11d |
| skills/vivado-rtl-lint/SKILL.md | 8b1cf84a006f008f613f019eb6e2a1681de4194931695ccf52aad1a2106ededb |
| skills/vivado-rtl-elaboration-analysis/SKILL.md | bfab9e52787b2eea6914a2c09047e40d776863521b172ffe6f22ab7046bf2bae |
| skills/vivado-simulate-rtl/SKILL.md | e24c6d396bfa9e0f2a834dc6dfcb67b0efff0a02ae8073752a4c2fc6942651ab |
