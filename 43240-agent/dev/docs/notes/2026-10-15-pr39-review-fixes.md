# PR #39 审查问题修复验证

日期：2026-10-15。类型：验证记录。状态：修复通过本地验证；不包含题集性能结论。

## 来源与改动

来源为用户对 [PR #39](https://github.com/gugugu531/AMD_SocChina_2026/pull/39) 的代码审查及后续修复要求。
修复分支为 `codex/fix-pr39-replay`，基于 PR 提交 `eee9845e6adcac555da4dfa6118e53677b70efd4`。

- 首稿请求的输出上限可能被 token 策略降低。重放现在用空账本还原首次调用的实际额度，
  不再要求实际请求上限等于配置上限；导入成本仍保留在运行账本，实际采样上限变化仍拒绝重放。
- 真实 Vivado 测试沿用正式工具配置解析，不再强制要求 `VIVADO_BIN`，支持从 `PATH` 查找工具。
- 同步更新方案 README 与当前接口说明，不改变检查点格式或其他工作流的行为。

## 验证结果

运行编号：`pr39-review-fixes-20261015`。
原始记录保存在本地 `43240-agent/dev/runs/pr39-review-fixes-20261015/`，不纳入 Git 或参赛包。

| 检查 | 结果 | 原始记录 |
| --- | --- | --- |
| 全量回归 | 327 项：318 通过、9 项可选真实工具测试跳过、0 失败 | `full.log` |
| 不设置 `VIVADO_BIN` 的真实 Vivado 专项 | 4 项全部通过，通过 `PATH` 查找工具 | `vivado-path.log` |
| 提交包检查 | `errors=[]` | `submission.json` |

新增回归覆盖三个实验工作流在输出 token 限额和总 token 限额下的重放、成本不重复扣除，
以及实际输出上限变化时继续拒绝重放。全量还覆盖三个入口在不含 dev 的提交包中运行。
真实工具专项属于全量默认跳过的项目，不相加作为独立测试数量。

使用已具备仓库依赖的本机环境 `/tmp/rtl-research-venv/bin/python`，在 `43240-agent/` 下运行：

```bash
python3 -m unittest discover -s dev/tests -p 'test_*.py' -v
env -u VIVADO_BIN RUN_VIVADO_TESTS=1 python3 -m unittest discover -s dev/tests -p 'test_experimental_vivado.py' -v
python3 dev/tools/submission.py
```

测试只使用固定假模型、本机 HTTP 服务和人工构造电路，没有调用商业模型或启动云端实例。
受保护文件与两个 baseline 未改动，差异格式检查通过。
