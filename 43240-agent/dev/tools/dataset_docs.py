"""从来源清单生成每个题集的说明、清单及薄导入入口。"""
from pathlib import Path

METHODS = {
    'chipbench': '保留公开题面、参考RTL和激励；补全公开子模块与宏，隔离参考模块名称，统一最终统计行。',
    'rtllm': '保留原始规格、激励和断言；测试数据嵌入测试台，统一模块名称与成功/失败出口，并处理SystemVerilog保留字。一次完整测试台判定计为一个样本。',
    'archxbench': '平方根、脉动阵列矩阵乘法和AES使用本地独立参考实现。平方根保留上游测试；另两题采用本地测试台与独立数学/上游Python模型。其余题缺少完整RTL参考答案或需要外部判定，暂未导入。改编版不能等同上游官方成绩。',
    'cvdp': '仅处理官方带答案公开样例中的RTL模块生成题，将LFSR的Cocotb测试改写为SystemVerilog，覆盖全部255个非零种子。其他公开样例要求补丁、测试台或文字解释；不代表完整CVDP。',
    'verilogeval': '从本仓库固定提交恢复主办方适配的156道VerilogEval题，保留题面、参考答案及测试台，统一目录题号并保存original_task_id别名。',
    'example': '从本仓库固定提交恢复3道赛事示例，保留题面、参考答案及测试台，统一目录题号并保存original_task_id别名。',
}


def write_source_docs(root, records, chosen=None):
    from datasets import SOURCES, ORIGINAL_COMMIT
    root = Path(root)
    for dataset in chosen or METHODS:
        rows = sorted((r for r in records if r['dataset']==dataset), key=lambda r:r['task_id'])
        imported = [r for r in rows if r['status']=='converted']
        deferred = [r for r in rows if r['status']!='converted']
        folder = root/dataset
        folder.mkdir(parents=True, exist_ok=True)
        url, revision = SOURCES.get(dataset, ('https://github.com/gugugu531/AMD_SocChina_2026', ORIGINAL_COMMIT))
        lines = [f'# {dataset}题集', '', '自动生成，不要手改；在仓库根目录运行 `python3 43240-agent/dev/tools/datasets.py docs`。', '',
                 f'来源：[{url}]({url})；固定提交：`{revision}`。', '',
                 f'本次登记{len(rows)}题，导入{len(imported)}题，未导入{len(deferred)}题。导入不代表通过质量筛选；',
                 '逐题验证和排除原因见[候选清单](../../43240-agent/dev/datasets/catalog.json)。', '',
                 '## 导入方法与脚本', '', METHODS[dataset], '',
                 '本目录的[import.py](import.py)调用[统一转换器](../../43240-agent/dev/tools/datasets.py)，仅处理本来源。',
                 '']
        if dataset == 'archxbench':
            lines += ['本地适配见[ArchXBench适配器](../../43240-agent/dev/tools/archxbench_adapter.py)。', '']
        if dataset in SOURCES:
            lines += [f'先将上游仓库放到 `43240-agent/dev/datasets/upstream/{dataset}`，检出上述固定提交。',
                      '许可证及NOTICE见[licenses](../../43240-agent/dev/datasets/licenses)。', '']
        else:
            lines += ['使用 `git archive` 从上述提交读取原始题目；无需额外下载。克隆时须保留该提交的Git历史。', '']
        lines += ['以下命令从仓库根目录执行；`--out`是来源目录的父目录。已有题目不会被覆盖，复现时使用空目录。', '',
                  '```bash', f'python3 tasks/{dataset}/import.py --out 43240-agent/dev/runs/reimport-{dataset} --manifest 43240-agent/dev/runs/reimport-{dataset}/conversion.json',
                  '```', '', '## 如何选题', '',
                  '只维护TXT清单，每行一个题号，支持空行与`#`注释；不创建选题副本目录。',
                  f'本来源全量清单为[imported.txt](imported.txt)。跨来源清单可混写题号，实验配置的题目根目录设为`tasks/`。', '',
                  '## 已导入题目', '', '| 题号 | 原始题号（如有） |', '| --- | --- |']
        lines += [f"| [{r['task_id']}]({r['task_id']}/prompt.txt) | {r.get('original_task_id','—')} |" for r in imported]
        lines += ['', '## 未导入题目', '']
        if deferred:
            lines += ['| 题号 | 原因 |', '| --- | --- |']
            lines += [f"| `{r['task_id']}` | {r['reason'].replace('|','/')} |" for r in deferred]
        else:
            lines += ['本次登记范围内没有未导入题目。']
        (folder/'readme.md').write_text('\n'.join(lines)+'\n')
        (folder/'imported.txt').write_text('# 自动生成：python3 43240-agent/dev/tools/datasets.py docs\n'+'\n'.join(r['task_id'] for r in imported)+'\n')
        wrapper = ('#!/usr/bin/env python3\n"""本来源的导入入口；由datasets.py docs生成。"""\n'
                   'from pathlib import Path\nimport subprocess\nimport sys\n\n'
                   "repo = next(p for p in Path(__file__).resolve().parents if (p/'43240-agent/dev/tools/datasets.py').is_file())\n"
                   "raise SystemExit(subprocess.call([sys.executable, str(repo/'43240-agent/dev/tools/datasets.py'),\n"
                   f"                                  'convert', '--dataset', {dataset!r}, *sys.argv[1:]]))\n")
        (folder/'import.py').write_text(wrapper)
