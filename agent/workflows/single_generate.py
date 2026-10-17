"""Official RTL baseline semantics with Agent recording and supervision."""
from agent.core.budget import BudgetExhausted
from agent.core.components import Node, Workflow
from agent.core.model import ModelCallError, ModelReply
from agent.core.extraction import ExtractInput, ExtractionOutput
from agent.nodes.generate import GenerateInput


class SingleGenerate(Workflow):
    component_name = 'single_generate'
    assembly_roles = ['workflow']
    assembly_defaults = {'params': {},
     'dependencies': {'generate': {'component': 'baseline_generate', 'id': 'generate'},
                      'extract': {'component': 'baseline_extract', 'id': 'extract'}}}
    dependencies = {'generate': 'node', 'extract': 'node'}
    dependency_types = {'generate': (GenerateInput, ModelReply),
                        'extract': (ExtractInput, ExtractionOutput)}

    def __init__(self, generate: Node[GenerateInput, ModelReply],
                 extract: Node[ExtractInput, ExtractionOutput]) -> None:
        self.generate, self.extract = generate, extract

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
