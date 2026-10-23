"""Generate once, then optionally repair from the failed check's diagnostics."""
from agent.core.budget import BudgetExhausted
from agent.core.components import Node, Workflow
from agent.core.extraction import ExtractInput, ExtractionOutput
from agent.core.model import ModelCallError, ModelReply
from agent.core.state import CheckResult
from agent.nodes.check import CheckInput
from agent.nodes.generate import GenerateInput


class RepairLoop(Workflow):
    component_name = 'repair_loop'
    assembly_roles = ['workflow']
    assembly_defaults = {'params': {'max_rounds': 2},
     'dependencies': {'generate': {'component': 'rtl_generate', 'id': 'generate'},
                      'extract': {'component': 'rtl_extract', 'id': 'extract'},
                      'interface': {'component': 'interface_check', 'id': 'interface'},
                      'lint': {'component': 'vivado_lint', 'id': 'lint'},
                      'synth': {'component': 'vivado_synth', 'id': 'synth'}}}
    dependencies = {'generate': 'node', 'extract': 'node', 'interface': 'node',
                    'lint': 'node', 'synth': 'node'}
    dependency_types = {'generate': (GenerateInput, ModelReply),
                        'extract': (ExtractInput, ExtractionOutput),
                        'interface': (CheckInput, CheckResult),
                        'lint': (CheckInput, CheckResult),
                        'synth': (CheckInput, CheckResult)}

    def __init__(self, generate: Node[GenerateInput, ModelReply],
                 extract: Node[ExtractInput, ExtractionOutput],
                 interface: Node[CheckInput, CheckResult],
                 lint: Node[CheckInput, CheckResult],
                 synth: Node[CheckInput, CheckResult], *, max_rounds: int = 2) -> None:
        if isinstance(max_rounds, bool) or not isinstance(max_rounds, int) or max_rounds <= 0:
            raise ValueError('max_rounds must be a positive integer')
        self.generate, self.extract = generate, extract
        self.interface, self.lint, self.synth = interface, lint, synth
        self.max_rounds = max_rounds

    def run(self, ctx):
        repair_target, feedback = None, ''
        for round in range(1, self.max_rounds + 1):
            try:
                reply = ctx.execute(self.generate,
                    GenerateInput(ctx.task, feedback, repair_target, round))
                result = ctx.execute(self.extract, ExtractInput(reply, round,
                    repair_target.id if repair_target else None,
                    'repair' if repair_target else 'generate'))
                if result.candidate is None:
                    # A failed extraction supplies diagnostics, without inventing
                    # code or discarding the previously selected answer.
                    feedback = '[extraction] ' + '; '.join(result.extraction.diagnostics)
                    source_id = reply.call_id
                    failure_kind = 'extraction'
                else:
                    candidate = result.candidate
                    repair_target = candidate
                    # Keep the first complete code as a fallback. A later failed
                    # repair must not overwrite the answer already selected.
                    if ctx.state.selected_candidate_id is None:
                        ctx.select_candidate(candidate.id, reason='complete_fallback')
                    ctx.emit('repair_target', candidate_id=candidate.id)
                    failed = None
                    for stage, node in (('interface', self.interface),
                                        ('lint', self.lint), ('synth', self.synth)):
                        check = ctx.execute(node, CheckInput(candidate))
                        # An advisory interface observation may continue. An
                        # environment failure or a blocking mismatch may not.
                        if (stage == 'interface' and not check.blocking and
                                check.status in ('passed', 'failed', 'skipped') and
                                check.classify() not in ('environment', 'timeout')):
                            continue
                        if check.blocking or check.status != 'passed':
                            failed = check
                            break
                    if failed is None:
                        ctx.select_candidate(candidate.id, reason='synth_passed')
                        return ctx.finish(reason='synth_passed')
                    failure_kind = failed.classify()
                    source_id = failed.id
                    feedback = f'[{failed.kind}] {failed.summary[:16000]}'
                # Only an extraction failure or an attributed RTL defect can
                # request another generation. No request or tool retries occur.
                repair = failure_kind in ('code', 'extraction') and round < self.max_rounds
                ctx.emit('failure_decision', action='repair' if repair else 'stop',
                         reason=failure_kind, diagnostic_ids=(source_id,), round=round)
                if not repair:
                    reason = ('verification_unavailable' if failure_kind == 'environment' else
                              'round_limit' if failure_kind in ('code', 'extraction') else failure_kind)
                    return ctx.finish(reason=reason, status='stopped')
            except BudgetExhausted:
                return ctx.finish(reason='deadline', status='stopped')
            except ModelCallError as exc:
                return ctx.finish(reason=f'model_{exc.kind}', status='stopped')
        return ctx.finish(reason='round_limit', status='stopped')
