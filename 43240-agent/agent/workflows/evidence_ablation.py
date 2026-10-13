"""E1 arms share the existing solver loop and explicit solver-only replay."""
from pathlib import Path

from agent.core.registry import WORKFLOW_REGISTRY, build_node
from agent.core.replay import load_initial, save_initial
from agent.workflows.evidence_repair import EvidenceRepair
from agent.workflows.repair_loop import AttemptState, LoopStart


class EvidenceAblation(EvidenceRepair):
    arm = 'A1'

    def __init__(self, initial_state=None, corpus_path=None):
        super().__init__()
        self.initial_state = initial_state
        if self.arm == 'A0':
            self.max_rounds = 1
        self.guidance = build_node('repair_guidance', corpus_path=corpus_path) if self.arm == 'A2' else None
        self._identity = None

    def run(self, ctx):
        # Configuration carries only a checkpoint path; its solver-only payload
        # is validated independently, never taken from a judge-bearing run folder.
        configured = getattr(ctx, 'configuration', {}).get('effective', {}).get('runtime', {}).get('initial_state')
        if self.initial_state is None:
            self.initial_state = configured
        if not self.initial_state:
            self._identity = ctx.tools.identify()
        return super().run(ctx)

    def restore(self, ctx):
        if not self.initial_state:
            return None
        data, reply, result, checks = load_initial(self.initial_state, ctx, self.extract)
        ctx.apply_selection(self.choose(ctx.state))
        if self.arm == 'A0' or data['stop_reason'] == 'synth_passed':
            return ctx.finish(reason=data['stop_reason'])
        if result.candidate is None:
            classification, source = 'extraction', reply.call_id
        elif checks:
            classification, source = checks[-1].classify(), checks[-1].id
        else:
            return ctx.finish(reason='initial_checks_unavailable', status='stopped')
        calls = data['tokens']['calls']
        choice = self.decide(classification, source, AttemptState(calls, 0, 0), ctx.budget)
        ctx.emit('failure_decision', action=choice.action, reason=choice.reason, diagnostic_ids=(source,),
                 model_calls=calls, request_retries=0, repairs=0)
        if choice.action != 'repair':
            return ctx.finish(reason='verification_unavailable' if classification == 'environment' else choice.reason,
                              status='stopped')
        feedback = (self.build_extraction_feedback(ctx, reply, result.extraction) if result.candidate is None
                    else self.build_check_feedback(ctx, checks))
        return LoopStart(result.candidate, feedback, calls, optional_pieces=self.repair_pieces(ctx, checks))

    def after_round(self, ctx, reply, result, checks, choice, round):
        if round == 1 and self.arm == 'A0' and not self.initial_state:
            save_initial(ctx.output_dir / 'initial.json', ctx, reply, result, checks, choice.reason, self._identity)

    def repair_pieces(self, ctx, checks):
        if self.guidance is None or not checks:
            return ()
        return ctx.execute(self.guidance, checks[-1])


@WORKFLOW_REGISTRY.register('evidence_a0')
class EvidenceInitial(EvidenceAblation):
    arm = 'A0'


@WORKFLOW_REGISTRY.register('evidence_a1')
class EvidenceStructured(EvidenceAblation):
    arm = 'A1'


@WORKFLOW_REGISTRY.register('evidence_a2')
class EvidenceGuided(EvidenceAblation):
    arm = 'A2'
