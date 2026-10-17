"""E1 arms share the existing solver loop and explicit solver-only replay."""

from agent.core.components import Node
from agent.core.extraction import ExtractInput, ExtractionOutput
from agent.core.model import ModelReply
from agent.core.replay_contract import InitialReplayContract
from agent.nodes.check import CheckInput
from agent.nodes.feedback import FeedbackInput, StructuredFeedback
from agent.nodes.generate import GenerateInput
from agent.workflows.replay import load_initial, save_initial
from agent.workflows.evidence_repair import EvidenceRepair
from agent.workflows.repair_loop import AttemptState, LoopStart
from agent.core.state import CheckResult


class EvidenceAblation(EvidenceRepair):
    component_name = 'evidence_ablation'
    assembly_roles = ['workflow']
    assembly_defaults = {'params': {'max_rounds': 2,
                'max_request_retries': 1,
                'max_model_calls': 3,
                'minimum_action_s': 0.05,
                'repair_output_drivers': False},
     'dependencies': {'generate': {'component': 'rtl_generate',
                                   'id': 'generate',
                                   'params': {'max_tokens': 8192,
                                              'temperature': 0.0,
                                              'timeout_s': 300.0,
                                              'use_skills': False,
                                              'top_p': 1.0}},
                      'extract': {'component': 'rtl_extract', 'id': 'extract'},
                      'interface': {'component': 'interface_check', 'id': 'interface'},
                      'lint': {'component': 'vivado_lint', 'id': 'lint'},
                      'synth': {'component': 'vivado_synth', 'id': 'synth'},
                      'feedback_builder': {'component': 'structured_feedback', 'id': 'feedback'},
                      'guidance': {'component': 'repair_guidance', 'id': 'guidance'}}}
    arm = 'A1'

    dependencies = {**EvidenceRepair.dependencies, 'guidance': 'node'}
    dependency_types = {**EvidenceRepair.dependency_types, 'guidance': (CheckResult, tuple)}

    def initial_replay_contract(self) -> InitialReplayContract:
        return InitialReplayContract('scheme_a', self.extract,
                                     (self.interface, self.lint, self.synth))

    def __init__(self, generate: Node[GenerateInput, ModelReply],
                 extract: Node[ExtractInput, ExtractionOutput],
                 interface: Node[CheckInput, CheckResult],
                 lint: Node[CheckInput, CheckResult],
                 synth: Node[CheckInput, CheckResult],
                 feedback_builder: Node[FeedbackInput, StructuredFeedback],
                 guidance: Node[CheckResult, tuple] | None = None, *,
                 max_rounds: int = 2, max_request_retries: int = 1,
                 max_model_calls: int | None = None, minimum_action_s: float = 0.05,
                 repair_output_drivers: bool = False) -> None:
        super().__init__(generate, extract, interface, lint, synth, feedback_builder,
                         max_rounds=max_rounds, max_request_retries=max_request_retries,
                         max_model_calls=max_model_calls, minimum_action_s=minimum_action_s,
                         repair_output_drivers=repair_output_drivers)
        self.guidance = guidance
        self._identity = None
        self._initial_checkpoint = None
        self._initial_state = None

    def run(self, ctx):
        # Configuration carries only a checkpoint path; its solver-only payload
        # is validated independently, never taken from a judge-bearing run folder.
        configured = getattr(ctx, 'configuration', {}).get('effective', {}).get('runtime', {}).get('initial_state')
        self._initial_state = configured
        if not self._initial_state:
            self._identity = ctx.checks.identify()
        return super().run(ctx)

    def restore(self, ctx):
        if not self._initial_state:
            return None
        data, reply, result, checks = load_initial(self._initial_state, ctx)
        self._initial_checkpoint = data
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
        if round == 1 and self.arm == 'A0' and not self._initial_state:
            save_initial(ctx.output_dir / 'initial.json', ctx, reply, result, checks, choice.reason, self._identity)

    def repair_pieces(self, ctx, checks):
        if self.guidance is None or not checks:
            return ()
        return ctx.execute(self.guidance, checks[-1])


class EvidenceInitial(EvidenceAblation):
    component_name = 'evidence_a0'
    assembly_roles = ['workflow']
    assembly_defaults = {'params': {'max_rounds': 1,
                'max_request_retries': 1,
                'max_model_calls': 3,
                'minimum_action_s': 0.05,
                'repair_output_drivers': False},
     'dependencies': {'generate': {'component': 'rtl_generate',
                                   'id': 'generate',
                                   'params': {'max_tokens': 8192,
                                              'temperature': 0.0,
                                              'timeout_s': 300.0,
                                              'use_skills': False,
                                              'top_p': 1.0}},
                      'extract': {'component': 'rtl_extract', 'id': 'extract'},
                      'interface': {'component': 'interface_check', 'id': 'interface'},
                      'lint': {'component': 'vivado_lint', 'id': 'lint'},
                      'synth': {'component': 'vivado_synth', 'id': 'synth'},
                      'feedback_builder': {'component': 'structured_feedback', 'id': 'feedback'}}}
    arm = 'A0'


class EvidenceStructured(EvidenceAblation):
    component_name = 'evidence_a1'
    assembly_roles = ['workflow']
    assembly_defaults = {'params': {'max_rounds': 2,
                'max_request_retries': 1,
                'max_model_calls': 3,
                'minimum_action_s': 0.05,
                'repair_output_drivers': False},
     'dependencies': {'generate': {'component': 'rtl_generate',
                                   'id': 'generate',
                                   'params': {'max_tokens': 8192,
                                              'temperature': 0.0,
                                              'timeout_s': 300.0,
                                              'use_skills': False,
                                              'top_p': 1.0}},
                      'extract': {'component': 'rtl_extract', 'id': 'extract'},
                      'interface': {'component': 'interface_check', 'id': 'interface'},
                      'lint': {'component': 'vivado_lint', 'id': 'lint'},
                      'synth': {'component': 'vivado_synth', 'id': 'synth'},
                      'feedback_builder': {'component': 'structured_feedback', 'id': 'feedback'}}}
    arm = 'A1'


class EvidenceGuided(EvidenceAblation):
    component_name = 'evidence_a2'
    assembly_roles = ['workflow']
    assembly_defaults = {'params': {'max_rounds': 2,
                'max_request_retries': 1,
                'max_model_calls': 3,
                'minimum_action_s': 0.05,
                'repair_output_drivers': False},
     'dependencies': {'generate': {'component': 'rtl_generate',
                                   'id': 'generate',
                                   'params': {'max_tokens': 8192,
                                              'temperature': 0.0,
                                              'timeout_s': 300.0,
                                              'use_skills': False,
                                              'top_p': 1.0}},
                      'extract': {'component': 'rtl_extract', 'id': 'extract'},
                      'interface': {'component': 'interface_check', 'id': 'interface'},
                      'lint': {'component': 'vivado_lint', 'id': 'lint'},
                      'synth': {'component': 'vivado_synth', 'id': 'synth'},
                      'feedback_builder': {'component': 'structured_feedback', 'id': 'feedback'},
                      'guidance': {'component': 'repair_guidance', 'id': 'guidance'}}}
    arm = 'A2'
