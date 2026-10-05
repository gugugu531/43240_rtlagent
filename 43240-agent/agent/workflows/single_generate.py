"""Default: one model generation and extraction, similar to the baseline."""
from ..core.budget import BudgetExhausted
from ..core.components import Component
from ..core.model import ModelCallError
from ..core.registry import WORKFLOW_REGISTRY, build_node
from ..nodes.generate import GenerateInput
from ..nodes.extract import ExtractInput


@WORKFLOW_REGISTRY.register('single_generate')
class SingleGenerate(Component):
    def __init__(self, max_tokens: int = 8192, temperature: float = 0.0,
                 timeout_s: float = 300.0):
        self.max_tokens, self.temperature, self.timeout_s = max_tokens, temperature, timeout_s
        self.generate = build_node('rtl_generate', max_tokens=max_tokens,
                                   temperature=temperature, timeout_s=timeout_s)
        self.extract = build_node('rtl_extract')

    def run(self, ctx):
        try:
            reply = ctx.execute(self.generate, GenerateInput(ctx.task))
        except BudgetExhausted:
            return ctx.finish(reason='deadline', status='stopped')
        except ModelCallError as exc:
            return ctx.finish(reason=f'model_{exc.kind}', status='stopped')
        result = ctx.execute(self.extract, ExtractInput(reply))
        if result.candidate is None:
            return ctx.finish(reason=f'extraction_{result.extraction.status}', status='stopped')
        ctx.select_candidate(result.candidate.id, reason='single_generation')
        return ctx.finish(reason='completed')
