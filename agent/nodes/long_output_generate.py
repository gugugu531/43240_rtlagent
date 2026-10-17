"""Explicit output-budget experiment while retaining official prompt semantics."""
from dataclasses import replace
from agent.nodes.baseline import BaselineGenerateNode


class _ModelOverride:
    def __init__(self, ctx, max_tokens, timeout_s):
        self.ctx, self.max_tokens, self.timeout_s = ctx, max_tokens, timeout_s

    def baseline_model(self, **kwargs):
        return self.ctx.llm.baseline_model(**kwargs)

    def chat(self, request):
        return self.ctx.llm.chat(replace(request, max_tokens=self.max_tokens,
            timeout_s=self.ctx.budget.timeout_s(self.timeout_s)))


class _ContextOverride:
    def __init__(self, ctx, max_tokens, timeout_s):
        self._ctx, self.max_tokens, self.timeout_s = ctx, max_tokens, timeout_s
        self.llm = _ModelOverride(ctx, max_tokens, timeout_s)

    def __getattr__(self, name):
        return getattr(self._ctx, name)


class LongOutputGenerate(BaselineGenerateNode):
    component_name = 'long_output_generate'
    assembly_roles = ['alternative', 'generate']
    assembly_defaults = {'params': {'max_tokens': 32768, 'timeout_s': 900.0}, 'dependencies': {}}

    def __init__(self, max_tokens: int = 32768, timeout_s: float = 900) -> None:
        self.max_tokens, self.timeout_s = max_tokens, timeout_s

    def run(self, ctx, input):
        ctx.emit('experiment_override', max_tokens=self.max_tokens,
                 timeout_s=self.timeout_s, source='agent.workflows.single_generate_long_output')
        return super().run(_ContextOverride(ctx, self.max_tokens, self.timeout_s), input)
