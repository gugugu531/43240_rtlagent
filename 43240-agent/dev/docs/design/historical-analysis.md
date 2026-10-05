# 历史实验分析工具

位置为 dev/tools/analysis/。这些工具继续读取既有模型选型实验的原始格式，不代表支持第四阶段
新实验格式，不把旧记录转换成新结果。本阶段仅迁移路径，没有新增历史重放或实验比较功能。

| 工具 | 用途 |
| --- | --- |
| analyze.py | 从历史 trace、判定和样本统计分析失败原因 |
| metrics.py | 历史运行资源统计，以及模型服务速度、显存、KV Cache（键值缓存）探测 |
| compare.py | 原有格式的逐题比较 |
| overview.py | 历史模型筛选与联合实验总表 |
| categorize.py | 从题面关键词生成题型清单 |

任务子集、排除清单及 categories.tsv 集中在 dev/configs/。新的 Agent/baseline 实验统一使用
[run.py](configuration-and-experiments.md)。旧 run_eval.py 已移除；参考答案链路验证改用官方
selftest/run_selftest.sh --reference，并将输出放 dev/runs/。

以下命令在 43240-agent/ 中运行：

```bash
python3 dev/tools/analysis/analyze.py dev/runs/<历史运行编号>
python3 dev/tools/analysis/metrics.py probe http://127.0.0.1:18000/v1 --model Qwen3-8B
python3 dev/tools/analysis/overview.py --out dev/docs/notes/2026-09-25-candidate-tables.md
python3 dev/tools/analysis/overview.py --inject dev/docs/notes/0002-model-choice.md
```

生成表格仍需从原始产物取得数据，人工假设和结论留在生成块外。单路速度探测与并发运行吞吐
分开解释。历史实验中的服务、预算和题目范围以各次原始记录为准，不能因为路径迁移视为重新验证。
