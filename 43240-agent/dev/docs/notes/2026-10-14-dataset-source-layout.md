# 题库按来源整理验收

类型：结构调整与离线验证记录。日期：2026-10-14。状态：已完成。
来源：用户要求按来源存储题目，在各目录说明导入范围和方法，使用TXT选题而不维护子集副本。

## 最终结构

258题保存在 `tasks/{verilogeval,example,chipbench,rtllm,archxbench,cvdp}/<题号>/`。
各来源含 `readme.md`、`imported.txt`、`import.py`，说明全部已导入题目、72条未导入记录及原因。
入口为[题库索引](../../../../tasks/index.md)，完整操作见[开发题集说明](../design/datasets.md)。

迁移前逐文件核对60份均衡集副本与原有159题，确认内容相同后移除重复目录；
原始159题的差异仅为统一题号和保存原题号别名。迁移后每道题只保留一份。
`balanced.txt`字节未变，仍选60题；筛选器不再提供复制子集选项。

实验入口支持按来源目录查找题号、跨来源TXT及旧题号别名，排除清单同样识别别名。
`joint-full.yaml`显式使用 `original.txt`，保持原有159题范围，应用原排除清单后为155题。
原始官方自测入口仍要求平铺目录，直接调用须指定单一来源；跨来源测评和参考验证使用开发入口。

## 验证证据

- 从固定上游版本及原题Git提交重新导入，258题全部通过格式检查，内容指纹与迁移前及已有验证缓存一致。
- 逐来源目录、TXT与导入清单一致，所有未导入题号均列入对应说明；258题无遗漏，均衡清单仍为60题。
- 原始主办方文件、两个baseline未改；提交打包检查无错误，题库不进入参赛方案。
- 数据集单元测试11项、实验测试13项、打包与入口测试6项通过；实验测试含跨来源选题、别名、排除、歧义、重复、越界和远端客户端选题。
- 来源导入包装器实际重建3道示例成功；远端包装脚本通过语法检查，未启动GPU实例。
- 假模型单题运行 `20261014-162041-dataset-layout-smoke-c200835a` 完成，旧题号 `ex03_lfsr8`正确定位到新目录。

本次只验证结构、选择行为及内容一致性，没有重跑Vivado或真实模型。先前258题的官方验证结果继续适用，
质量筛选后仍为241题；先前各题是否通过L3的结论未改变。
原始测量和日志保留原路径，历史文档中的 `pool/`、`balanced/` 命令只反映当时结构。

本地审计数据：`dev/runs/dataset-layout-final/audit.json`；重建清单：`dev/runs/dataset-layout-final/conversion.json`。

复核命令（仓库根目录）：

```bash
python3 43240-agent/dev/tools/datasets.py convert --out 43240-agent/dev/runs/dataset-layout-final --manifest 43240-agent/dev/runs/dataset-layout-final/conversion.json
python3 43240-agent/dev/tools/validate_datasets.py --jobs 4
python3 43240-agent/dev/tools/balance_datasets.py --size 60
python3 -m unittest discover -s 43240-agent/dev/tests -p test_datasets.py -v
python3 -m unittest discover -s 43240-agent/dev/tests -p test_experiments.py -v
python3 -m unittest discover -s 43240-agent/dev/tests -p test_submission.py -v
python3 43240-agent/dev/tools/submission.py
```

重建目录非空时应换用新的输出目录。测试中的临时HTTP服务需要允许本机回环监听，不连接外部模型。
