"""Explicitly imported output-budget experiment; default workflows stay unchanged."""
from dataclasses import replace

from agent.core.registry import NODE_REGISTRY, WORKFLOW_REGISTRY, build_node
from agent.nodes.baseline import BaselineGenerateNode
from agent.workflows.single_generate import SingleGenerate


class _ModelOverride:
    def __init__(self, ctx, max_tokens, timeout_s):
        self.ctx, self.max_tokens, self.timeout_s = ctx, max_tokens, timeout_s

    def baseline_model(self, **kwargs):
        return self.ctx.llm.baseline_model(**kwargs)

    def chat(self, request):
        return self.ctx.llm.chat(replace(
            request, max_tokens=self.max_tokens,
            timeout_s=self.ctx.budget.timeout_s(self.timeout_s)))


class _ContextOverride:
    def __init__(self, ctx, max_tokens, timeout_s):
        self._ctx = ctx
        self.llm = _ModelOverride(ctx, max_tokens, timeout_s)

    def __getattr__(self, name):
        return getattr(self._ctx, name)


@NODE_REGISTRY.register('long_output_generate')
class LongOutputGenerate(BaselineGenerateNode):
    def __init__(self, max_tokens=32768, timeout_s=900):
        self.max_tokens, self.timeout_s = max_tokens, timeout_s

    def run(self, ctx, input):
        ctx.emit('experiment_override', max_tokens=self.max_tokens,
                 timeout_s=self.timeout_s, source='agent.workflows.single_generate_long_output')
        return super().run(_ContextOverride(ctx, self.max_tokens, self.timeout_s), input)


@WORKFLOW_REGISTRY.register('single_generate_long_output')
class SingleGenerateLongOutput(SingleGenerate):
    def __init__(self):
        super().__init__()
        self.generate = build_node('long_output_generate')
