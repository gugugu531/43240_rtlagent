"""Prompt assembly is an action detail, not a responsibility of the runner."""
from pathlib import Path
import hashlib
from agent.core.skill import SkillSelection
from agent.core.task import TaskSpec
from agent.prompts.skills import render

PROMPT_DIR = Path(__file__).parent
def assemble_messages(task: TaskSpec, *, style: str, feedback: str = '',
                      parent_code: str = '', selected_skills: SkillSelection | None = None):
    filename = 'single_generate.md' if style == 'direct' else 'system.md'
    system = (PROMPT_DIR / filename).read_text(encoding='utf-8').strip()
    if style == 'direct':
        system = system.replace('{{TOP}}', task.top)
        user = task.prompt + ('\n\nInterface:\n' + task.interface if task.interface else '')
    else:
        interface_rule = ('模块名、端口名、方向、位宽和顺序须保持' if feedback
                          else '模块名与端口不得改动')
        user = ('## 题目\n\n' + (task.prompt or '(empty)') +
                f'\n\n## 模块接口（{interface_rule}）\n\n```verilog\n' +
                (task.interface or '(empty)') + '\n```\n')
    messages = [{'role': 'system', 'content': system}]
    resources = {'system_file': filename, 'system_sha256': hashlib.sha256(system.encode()).hexdigest()}
    # Lookup belongs to the injected tool. Rendering here preserves the
    # selected order and the extra system message's position before the user.
    chosen = selected_skills.skills if selected_skills is not None else ()
    if chosen:
        rendered = '\n\n'.join(render(s) for s in chosen)
        messages.append({'role': 'system', 'content': '以下技能与当前错误相关，按其中的步骤处理：\n\n' + rendered})
        resources['skills'] = [dict(name=s.name, sha256=hashlib.sha256(render(s).encode()).hexdigest()) for s in chosen]
    if feedback:
        template = (PROMPT_DIR / 'repair.md').read_text(encoding='utf-8').strip()
        user += '\n\n' + template.replace('{{LOG}}', feedback).replace('{{CODE}}', parent_code)
        resources['repair_sha256'] = hashlib.sha256(template.encode()).hexdigest()
    messages.append({'role': 'user', 'content': user})
    return messages, resources
