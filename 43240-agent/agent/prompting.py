"""Prompt assembly is an action detail, not a responsibility of the runner."""
from pathlib import Path
import hashlib
from .core.task import TaskSpec
from .skills import load_skills, select

PROMPT_DIR = Path(__file__).parent / 'prompts'
SKILL_DIR = Path(__file__).parent.parent / 'skill'


def assemble_messages(task: TaskSpec, *, style: str, feedback: str = '',
                      parent_code: str = '', use_skills: bool = False):
    filename = 'single_generate.md' if style == 'direct' else 'system.md'
    system = (PROMPT_DIR / filename).read_text(encoding='utf-8').strip()
    if style == 'direct':
        system = system.replace('{{TOP}}', task.top)
        user = task.prompt + ('\n\nInterface:\n' + task.interface if task.interface else '')
    else:
        user = ('## 题目\n\n' + (task.prompt or '(empty)') +
                '\n\n## 模块接口（模块名与端口不得改动）\n\n```verilog\n' +
                (task.interface or '(empty)') + '\n```\n')
    messages = [{'role': 'system', 'content': system}]
    resources = {'system_file': filename, 'system_sha256': hashlib.sha256(system.encode()).hexdigest()}
    chosen = select(load_skills(str(SKILL_DIR)), task.prompt, feedback) if use_skills and feedback else []
    if chosen:
        rendered = '\n\n'.join(s.render() for s in chosen)
        messages.append({'role': 'system', 'content': '以下技能与当前错误相关，按其中的步骤处理：\n\n' + rendered})
        resources['skills'] = [dict(name=s.name, sha256=hashlib.sha256(s.render().encode()).hexdigest()) for s in chosen]
    if feedback:
        template = (PROMPT_DIR / 'repair.md').read_text(encoding='utf-8').strip()
        user += '\n\n' + template.replace('{{LOG}}', feedback).replace('{{CODE}}', parent_code)
        resources['repair_sha256'] = hashlib.sha256(template.encode()).hexdigest()
    messages.append({'role': 'user', 'content': user})
    return messages, resources
