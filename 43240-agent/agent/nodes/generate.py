"""Single generation action; retry decisions belong to workflows."""
from dataclasses import dataclass
import math
from agent.core.candidate import Candidate
from agent.core.components import Component
from agent.core.model import ModelRequest, ModelReply
from agent.core.registry import NODE_REGISTRY
from agent.core.task import TaskSpec
from agent.prompts.builder import assemble_messages


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
    minimum_s: float = 0.0
    top_p: float | None = None

    def __post_init__(self):
        ModelRequest([], max_tokens=self.max_tokens, temperature=self.temperature,
                     timeout_s=self.timeout_s, top_p=self.top_p)
        if not math.isfinite(self.minimum_s) or self.minimum_s < 0:
            raise ValueError('minimum_s must be finite and nonnegative')
        if self.prompt_style not in ('direct', 'repair'):
            raise ValueError('prompt_style must be direct or repair')

    def run(self, ctx, input: GenerateInput) -> ModelReply:
        messages, resources = assemble_messages(
            input.task, style=self.prompt_style, feedback=input.feedback,
            parent_code=input.parent.code if input.parent else '', use_skills=self.use_skills)
        ctx.emit('prompt_resources', round=input.round, **resources)
        return ctx.llm.chat(ModelRequest(messages, max_tokens=self.max_tokens,
                                        temperature=self.temperature,
                                        top_p=self.top_p,
                                        timeout_s=ctx.budget.timeout_s(self.timeout_s, self.minimum_s),
                                        purpose='repair' if input.parent else 'generate'))
