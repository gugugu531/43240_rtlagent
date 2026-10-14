"""按题号查找平铺或按来源分组的题库，不复制选中的题目。"""
from pathlib import Path
import json


def task_directories(root):
    root = Path(root).resolve()
    prompts = [*root.glob('*/prompt.txt'), *root.glob('*/*/prompt.txt')]
    return sorted({p.parent for p in prompts if p.is_file()})


def task_index(root):
    """保留原有题号别名；同名题不静默选择，交由调用方报告歧义。"""
    root = Path(root).resolve()
    directories = task_directories(root)
    index = {}
    for directory in directories:
        if not directory.resolve().is_relative_to(root):
            raise ValueError('task directory escapes tasks.root')
        aliases = {directory.name}
        metadata = directory/'task.json'
        if metadata.is_file():
            data = json.loads(metadata.read_text())
            if not isinstance(data, dict):
                raise ValueError('task metadata must be an object')
            alias = data.get('original_task_id')
            if isinstance(alias, str):
                aliases.add(alias)
        for name in aliases:
            index.setdefault(name, []).append(directory.resolve())
    return directories, index
