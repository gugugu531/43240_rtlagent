"""Official RTL baseline semantics with Agent recording and supervision."""
from agent.core.budget import BudgetExhausted
from agent.core.components import Component
from agent.core.model import ModelCallError
from agent.core.registry import WORKFLOW_REGISTRY, build_node
from agent.nodes.generate import GenerateInput
from agent.nodes.extract import ExtractInput


@WORKFLOW_REGISTRY.register('single_generate')
class SingleGenerate(Component):
    def __init__(self):
        self.generate = build_node('baseline_generate')
        self.extract = build_node('baseline_extract')

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
