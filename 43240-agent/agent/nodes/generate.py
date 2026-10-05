"""Single generation action; retry decisions belong to workflows."""
from dataclasses import dataclass
from ..candidate import Candidate
from ..core.components import Component
from ..core.model import ModelRequest, ModelReply
from ..core.registry import NODE_REGISTRY
from ..core.task import TaskSpec
from ..prompting import assemble_messages


@dataclass(frozen=True)
class GenerateInput:
    task: TaskSpec
    feedback: str = ''
    parent: Candidate | None = None
    round: int = 1


@NODE_REGISTRY.register('rtl_generate')
@dataclass(frozen=True)
class GenerateNode(Component):
    max_tokens: int = 8192
    temperature: float = 0.0
    timeout_s: float = 300.0
    prompt_style: str = 'direct'
    use_skills: bool = False

    def __post_init__(self):
        ModelRequest([], max_tokens=self.max_tokens, temperature=self.temperature, timeout_s=self.timeout_s)
        if self.prompt_style not in ('direct', 'repair'):
            raise ValueError('prompt_style must be direct or repair')

    def run(self, ctx, input: GenerateInput) -> ModelReply:
        messages, resources = assemble_messages(
            input.task, style=self.prompt_style, feedback=input.feedback,
            parent_code=input.parent.code if input.parent else '', use_skills=self.use_skills)
        ctx.emit('prompt_resources', round=input.round, **resources)
        return ctx.llm.chat(ModelRequest(messages, max_tokens=self.max_tokens,
                                        temperature=self.temperature,
                                        timeout_s=ctx.budget.timeout_s(self.timeout_s),
                                        purpose='repair' if input.parent else 'generate'))
