"""Single generation action; retry decisions belong to workflows."""
from dataclasses import dataclass
import math
from agent.core.candidate import Candidate
from agent.core.components import Node, Tool
from agent.core.model import ModelRequest, ModelReply
from agent.core.skill import SkillQuery, SkillSelection
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
    dependencies = {'skill_tool': 'tool'}
    dependency_types = {'skill_tool': (SkillQuery, SkillSelection)}
    assembly_roles = ['generate', 'alternative']
    assembly_defaults = {'params': {'max_tokens': 4096, 'temperature': 0.2,
                                    'timeout_s': 180.0, 'prompt_style': 'repair',
                                    'use_skills': True, 'minimum_s': 0.0, 'top_p': None},
                         'dependencies': {'skill_tool': {'component': 'skill_lookup',
                                                         'id': 'skill_tool',
                                                         'when': {'use_skills': True}}}}
    max_tokens: int = 8192
    temperature: float = 0.0
    timeout_s: float = 300.0
    prompt_style: str = 'direct'
    use_skills: bool = False
    minimum_s: float = 0.0
    top_p: float | None = None
    skill_tool: Tool[SkillQuery, SkillSelection] | None = None

    def __post_init__(self):
        ModelRequest([], max_tokens=self.max_tokens, temperature=self.temperature,
                     timeout_s=self.timeout_s, top_p=self.top_p)
        if not math.isfinite(self.minimum_s) or self.minimum_s < 0:
            raise ValueError('minimum_s must be finite and nonnegative')
        if self.prompt_style not in ('direct', 'repair'):
            raise ValueError('prompt_style must be direct or repair')
        if self.use_skills and not isinstance(self.skill_tool, Tool):
            raise ValueError('skill_tool is required when use_skills is true')

    def run(self, ctx, input: GenerateInput) -> ModelReply:
        selected_skills = (ctx.call(self.skill_tool, SkillQuery(input.task.prompt, input.feedback))
                           if self.use_skills and input.feedback else None)
        kwargs = dict(style=self.prompt_style, feedback=input.feedback,
                      parent_code=input.parent.code if input.parent else '',
                      selected_skills=selected_skills,
                      counter=ctx.llm.counter, template_options=ctx.llm.template_options)
        cap, context_limit = self.max_tokens, ctx.llm.context_limit
        if ctx.llm.tokens.policy.strict:
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
