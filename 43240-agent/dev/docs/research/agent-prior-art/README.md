# Agent 论文与开源工程调研

本目录面向当前 FPGA 赛题 Agent，整理可复现的 RTL/EDA、Coding Agent 和通用 Agent 工作。
目标不是罗列所有论文，而是回答三个问题：哪些值得先读、哪些代码值得复现、哪些想法能用现有
Workflow 做受控实验。

## 快速结论

最值得先读的不是最复杂的多 Agent 系统，而是下面六条相互补充的路线：

1. [AutoChip](papers.md#1-autochip)：编译和仿真反馈怎样进入下一轮，以及工具反馈何时真的有效。
2. [RTLFixer](papers.md#2-rtlfixer)：把编译错误分类，再检索针对性的人类修复建议，而不是塞整段日志。
3. [VerilogCoder](papers.md#3-verilogcoder)：用规划图和 AST 波形追踪定位功能错误；其完整条件依赖测试台，
   不能直接照搬论文成绩。
4. [Agentless](papers.md#11-agentless)：固定“定位—修复—验证”往往比自由 Agent 更便宜、更容易解释；
   这与当前保留简单默认流程的方向一致。
5. [SWE-agent](papers.md#10-swe-agent)：工具接口本身会显著影响 Agent 行为，结构化、短而明确的工具输出
   比继续堆提示词更值得先做。
6. [LLMLingua、RouteLLM 与 LLMCompiler](papers.md#14-效率方法)：分别对应上下文压缩、按难度路由、
   独立工具并行，直接关系到比赛墙钟时间和 token 预算。

论文、代码与指标分开记录：

- [论文清单](papers.md)：发布时间、OpenAlex 引用量、代码入口、核心结论和适用边界。
- [开源工程清单](projects.md)：GitHub Star、许可证、活跃度、复现优先级和建议阅读位置。
- [落地路线](adoption-plan.md)：映射到当前 `single_generate`、`repair_loop`、Node、Policy 和实验入口。
- 一周教程与下载的论文、第三方工程只保存在本地，不纳入本次 PR。
- [AMD Ross 本地研究入口](ross-ai-study.md)：2026-10-13 下载用户 fork，记录固定版本、阅读路线与比赛边界；未安装插件或接入实验。

## 筛选口径

核心清单使用以下条件：

- 论文全文公开，且存在公开代码、数据、模型或可执行评测仓库；只有摘要或宣传页的不进入核心清单。
- RTL/EDA 工作优先考虑和“规格生成 RTL、工具反馈修复、功能验证、PPA、时间预算”直接相关的项目。
- 通用工作只保留能迁移到当前工程的技术：工具接口、错误定位、反思、搜索、路由、上下文压缩、
  并行执行和可复现实验。
- 引用量与 Star 都是动态信号，不把它们等同于正确性；新论文允许引用少，但必须单列为前沿项目。
- 论文声称的提升只代表其模型、数据、测试台和预算，不能直接外推到 Qwen、本赛题或 Vivado。

## 指标说明

指标快照日期为 **2026-10-06（Asia/Shanghai）**：

- 引用量来自 [OpenAlex](https://openalex.org/)，优先选择标题完全一致的正式发表记录；预印本与会议版
  可能被拆分，因此数字只在同一来源内比较。
- GitHub Star、创建时间、最近 push、归档状态与许可证来自
  [GitHub REST API](https://docs.github.com/en/rest/repos/repos#get-a-repository)。
- GitHub 返回 `NOASSERTION` 或没有检测到许可证时写作“需人工核对”；这意味着可以阅读，不意味着可以
  直接复制代码进入提交方案。
- ReAct 在本次 OpenAlex 查询中没有可靠的标题完全匹配记录，因此不编造引用数字；论文和代码仍保留，
  因为 RTLFixer 等后续工作明确沿用了它的“推理—行动—观察”循环。
- 最近 push 只能说明仓库活动时间，不能证明项目维护质量或论文可复现性。

## 本轮材料边界

- 教程、PDF、材料清单和只读第三方工程不随本目录上传；本目录仅保留调研摘要和来源链接。
- RTLRepoCoder 仅保存公开论文；截至 2026-10-09 未找到作者公开代码，因此第 3 天以可复现的 RepoCoder
  和 RTL-Repo 补充方法与数据结构学习，不把替代仓库冒充官方实现。
- AutoCodeRover 保存 ISSTA 正式论文但不保留工程副本：当前仓库约 1.1 GiB，且采用 Source-Available
  许可证，不把“公开源码”误写成“可自由复用的开源工程”。
- 没有下载模型权重、完整数据集或 AutoChip 大型仓库。
- 没有启动 GPU、Vivado 或第三方 API 复现实验。
- 没有把第三方 benchmark 的参考答案、测试台或生成代码放进正式 Agent。
- 没有按论文摘要直接修改求解策略；具体实验顺序见[落地路线](adoption-plan.md)。

## 建议阅读顺序

如果只有半天：AutoChip → RTLFixer → Agentless → 当前[落地路线](adoption-plan.md)。

如果有两天：再读 VerilogCoder、MAGE、SWE-agent、Reflexion、LLMLingua，并查看
VerilogEval v2、RTLLM 和 TuRTLe 的评测脚本。ChatEDA 主要学习 EDA 工具接口和任务编排，
不要把它当作 RTL 功能修复方案。
