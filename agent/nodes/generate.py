"""Single generation action; retry decisions belong to workflows."""
from dataclasses import dataclass
import math
from agent.core.candidate import Candidate
from agent.core.components import Node
from agent.core.model import ModelRequest, ModelReply
from agent.core.task import TaskSpec
from agent.prompts.context import ContextAssembler, ContextPiece


@dataclass(frozen=True)
class GenerateInput:
    task: TaskSpec
    feedback: str = ''
    parent: Candidate | None = None
    round: int = 1
    optional_pieces: tuple[ContextPiece, ...] = ()
    seed: int | None = None


@dataclass(frozen=True)
class GenerateNode(Node[GenerateInput, ModelReply]):
    component_name = 'rtl_generate'
    input_type = GenerateInput
    output_type = ModelReply
    assembly_roles = ['generate']
    assembly_defaults = {'params': {'max_tokens': 4096, 'temperature': 0.2,
                                    'timeout_s': 180.0, 'prompt_style': 'repair',
                                    'minimum_s': 0.0, 'top_p': None},
                         'dependencies': {}}
    max_tokens: int = 8192
    temperature: float = 0.0
    timeout_s: float = 300.0
    prompt_style: str = 'direct'
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
        kwargs = dict(style=self.prompt_style, feedback=input.feedback,
                      parent_code=input.parent.code if input.parent else '',
                      counter=ctx.llm.counter, template_options=ctx.llm.template_options)
        cap, context_limit = self.max_tokens, ctx.llm.context_limit
        if ctx.llm.tokens.policy.strict:
            # Reserve output against required messages first. Optional context
            # is considered only after the remaining allowance is known.
            required = ContextAssembler().assemble(input.task, **kwargs)
            cap = ctx.llm.tokens.allowance(required.count, cap)
            total = ctx.llm.tokens.policy.total_limit
            if total is not None:
                remaining = total - ctx.llm.tokens.snapshot()['charged_total']
                context_limit = min(context_limit, remaining) if context_limit is not None else remaining
        assembly = ContextAssembler().assemble(input.task, **kwargs,
            optional_pieces=input.optional_pieces,
            context_limit=context_limit, output_reserve=cap, strict=ctx.llm.strict_context)
        ctx.emit('prompt_resources', round=input.round, **assembly.resources)
        ctx.emit('context_assembly', round=input.round, **assembly.summary_dict())
        return ctx.llm.chat(ModelRequest(assembly.messages, max_tokens=cap,
                                        temperature=self.temperature,
                                        top_p=self.top_p,
                                        timeout_s=ctx.budget.timeout_s(self.timeout_s, self.minimum_s),
                                        seed=input.seed,
                                        purpose='repair' if input.parent else 'generate'))
