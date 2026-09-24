# AGENTS.md

给协作者和 AI 编程助手的简短指引。详细规范见 `43240-agent/dev/CONVENTIONS.md`。

## 仓库分工

- **主办方原始文件，只读，不要修改：** 根目录的 `README.md`、`SCORING.md`、
  `REPORT_TEMPLATE.md`、`.gitignore`，以及 `docs/`、`selftest/`、`example/`
- **`43240-agent/`：** 队伍 43240 的参赛方案，也是提交目录，主要开发都在这里。整体结构见
  `43240-agent/README.md`
- **`43240-agent/dev/`：** 团队开发文档与测试脚本，不随方案提交。新的笔记、决策、实验
  记录、分析都放这里

## 必须遵守

- 不修改 `43240-agent/baseline.py` 和 `43240-agent/run_baseline.sh`
- 参考答案只能放在 `43240-agent/dev/`，不能进入 `agent/`、`skill/` 或其他提交文件
- 提交目录中的文件名只用英文小写字母、数字、下划线或连字符
- 不提交 API key、令牌、`remote.env`、`selftest/env.sh`
- 不直接向 `main` 提交或推送：改动在单独的分支上完成，通过 PR 合并（见规范第 4.3 节）
- 提交信息只写一行 `<类型>(<范围>): <说明>`，不写正文，不加 `Co-Authored-By`
- 改了方案的代码结构或行为，在同一个 commit 中更新 `43240-agent/README.md`

## 写文档

- 正文用中文，优先使用日常说法，不自己创造说法或缩写
- 专有名词和通用缩写保持原样
- 含义不明显的缩写或术语，第一次出现时加括号解释

## 常用命令

```bash
# 用假模型检查流程能否跑通（不需要 GPU 和 Vivado）
cd 43240-agent && LLM_BACKEND=mock ./run.sh ../tasks/ex03_lfsr8 /tmp/out

# 本地判定（需要 Vivado）
selftest/run_selftest.sh --agent 43240-agent --tasks <题目目录>

# 并行跑分并分析失败原因（在 43240-agent/ 下运行），见 43240-agent/dev/eval/README.md
python3 dev/eval/run_eval.py --tag ref --modes reference          # 检查判定链路
python3 dev/eval/run_eval.py --tag xxx --taskset quick --modes baseline

# 用云端 GPU 实例跑分（启动、销毁、看门狗），见 43240-agent/dev/remote/README.md
43240-agent/dev/remote/cloud.py status
```

云端实例一直计费：用完立刻 `cloud.py down`；长时间运行前阻止本机休眠；Cookie 约 4 小时失效。
