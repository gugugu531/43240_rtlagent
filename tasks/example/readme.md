# example题集

自动生成，不要手改；在仓库根目录运行 `python3 43240-agent/dev/tools/datasets.py docs`。

来源：[https://github.com/gugugu531/AMD_SocChina_2026](https://github.com/gugugu531/AMD_SocChina_2026)；固定提交：`7f1014925d5b83e737db02fb08045014a1ec4f54`。

本次登记3题，导入3题，未导入0题。导入不代表通过质量筛选；
逐题验证和排除原因见[候选清单](../../43240-agent/dev/datasets/catalog.json)。

## 导入方法与脚本

从本仓库固定提交恢复3道赛事示例，保留题面、参考答案及测试台，统一目录题号并保存original_task_id别名。

本目录的[import.py](import.py)调用[统一转换器](../../43240-agent/dev/tools/datasets.py)，仅处理本来源。

使用 `git archive` 从上述提交读取原始题目；无需额外下载。克隆时须保留该提交的Git历史。

以下命令从仓库根目录执行；`--out`是来源目录的父目录。已有题目不会被覆盖，复现时使用空目录。

```bash
python3 tasks/example/import.py --out 43240-agent/dev/runs/reimport-example --manifest 43240-agent/dev/runs/reimport-example/conversion.json
```

## 如何选题

只维护TXT清单，每行一个题号，支持空行与`#`注释；不创建选题副本目录。
本来源全量清单为[imported.txt](imported.txt)。跨来源清单可混写题号，实验配置的题目根目录设为`tasks/`。

## 已导入题目

| 题号 | 原始题号（如有） |
| --- | --- |
| [example_ex01_popcount8](example_ex01_popcount8/prompt.txt) | ex01_popcount8 |
| [example_ex02_detect_1101](example_ex02_detect_1101/prompt.txt) | ex02_detect_1101 |
| [example_ex03_lfsr8](example_ex03_lfsr8/prompt.txt) | ex03_lfsr8 |

## 未导入题目

本次登记范围内没有未导入题目。
