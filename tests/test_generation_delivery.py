"""Public interface and observed delivery failures must reach generation."""
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from burr.core import State

from agent.orchestration.nodes.adaptive import (
    _generation_messages, _delivery_failure, _candidate, _review_checker,
    finish, initialize, repair, rescue, review_checker, revise_checker,
)
from agent.context.prompts import TemplateRenderer
from agent.domain.rtl.candidate import CandidateStore
from agent.domain.rtl.extract import extract_result
from agent.domain.rtl.task import TaskSpec


class DeliveryTests(unittest.TestCase):
    def context(self, prompt):
        self.artifacts = {}
        record = SimpleNamespace(
            write_json=lambda name, value: self.artifacts.update({name: value}),
            write_text=lambda *args: None,
            emit=lambda *args, **kwargs: None,
        )
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return SimpleNamespace(task=TaskSpec.from_text('public', prompt),
            prompts=TemplateRenderer(), store={'adaptive': {'analysis': None}},
            candidates=CandidateStore(record, temporary.name), record=record)

    def test_public_ports_and_top_reach_actual_template(self):
        ctx = self.context('Implement a module named TopModule.\n- input x\n- input y\n- output z')
        text = _generation_messages(ctx)[1]['content']
        self.assertIn('Required top module name: `TopModule`', text)
        self.assertIn('"name": "x"', text)
        self.assertIn('"source": "prompt_list"', text)
        self.assertIn('"complete": true', text)

    def test_buggy_embedded_code_is_not_an_authoritative_interface(self):
        ctx = self.context('Fix the bug:\n```verilog\nmodule wrong(input x, output [9:0] z); endmodule\n```')
        text = _generation_messages(ctx)[1]['content']
        self.assertIn('"complete": false', text)
        self.assertIn('"ports": []', text)
        self.assertNotIn('"source": "generated_code"', text)

    def test_rejected_top_records_failure_and_changes_rescue_request(self):
        ctx = self.context('Implement a module named TopModule.\n- input x\n- output z')
        reply = SimpleNamespace(call_id='m1', content='module top(input x, output z); assign z=x; endmodule', finish_reason='stop')
        first = _generation_messages(ctx)
        self.assertIsNone(_candidate(ctx, reply))
        failure = ctx.store['adaptive']['draft_failure']
        self.assertEqual(failure['extraction']['status'], 'target_missing')
        self.assertEqual(failure['extraction']['module_names'], ['top'])
        rescue = _generation_messages(ctx, failure=failure)
        self.assertNotEqual(first, rescue)
        self.assertIn('target_missing', rescue[1]['content'])
        self.assertEqual(self.artifacts['adaptive/draft-failure.json'], failure)

    def test_missing_body_is_not_inferred_to_be_length_truncation(self):
        for finish, kind in [('stop', 'no_final_content'), ('length', 'length_truncated')]:
            reply = SimpleNamespace(call_id='m2', content='', finish_reason=finish)
            failure = _delivery_failure(reply, extract_result('', 'TopModule'), 'TopModule')
            self.assertEqual(failure['kind'], kind)
            self.assertFalse(failure['final_content_present'])

    def test_complete_candidate_is_still_delivered(self):
        ctx = self.context('Implement a module named TopModule.\n- input x\n- output z')
        reply = SimpleNamespace(call_id='m3', content='module TopModule(input x, output z); assign z=x; endmodule', finish_reason='stop')
        candidate = _candidate(ctx, reply)
        self.assertEqual(ctx.candidates.selected_id, candidate.id)
        self.assertNotIn('draft_failure', ctx.store['adaptive'])

    def test_format_recovery_node_makes_no_model_request(self):
        from agent.orchestration.nodes.adaptive import correct_checker_format
        from agent.domain.rtl.adaptive_check import parse_checker
        ctx = self.context('Implement a module named TopModule.\n- input x\n- output z')
        text = '{"status":"unsupported","reason":"No grounded behavioral check"'
        data = ctx.store['adaptive']
        data.update(checker_revision_used=False,
                    checker_draft=parse_checker(text, ctx.task, 'model', finish_reason='stop'),
                    checker_syntax_reply=SimpleNamespace(content=text, finish_reason='stop', call_id='m4'))
        with patch('agent.orchestration.nodes.adaptive._request', side_effect=AssertionError('model call')):
            state = correct_checker_format(ctx, State())
        self.assertEqual(state['checker_status'], 'unsupported')
        self.assertEqual(data['checker_format_correction']['model_calls'], 0)
        self.assertTrue(data['checker_revision_used'])
        with self.assertRaises(ValueError):
            correct_checker_format(ctx, State())

    # -- plan projection: routing metadata only ------------------------------
    def test_plan_projection_omits_rationale_requirements_and_cost(self):
        ctx = self.context('Implement a module named TopModule.\n- input x\n- output z')
        ctx.store['adaptive']['analysis'] = SimpleNamespace(
            kind='sequential', clocks=['clk'], risks=['state_update'],
            ambiguities=['reset polarity unclear'],
            requirements=['PRIVATE REQUIREMENT TEXT'], route='model',
            model_cost='small', rationale='private model rationale')
        text = _generation_messages(ctx)[1]['content']
        self.assertIn('reset polarity unclear', text)
        self.assertIn('"clocks": ["clk"]', text)
        self.assertIn('"kind": "sequential"', text)
        self.assertNotIn('rationale', text)
        self.assertNotIn('model_cost', text)
        self.assertNotIn('PRIVATE REQUIREMENT TEXT', text)

    # -- rescue: a missing failure record must not raise ---------------------
    def test_rescue_without_failure_record_sends_plain_request(self):
        from agent.domain.rtl.adaptive_analysis import RouteDecision
        from agent.orchestration.workflows.adaptive_verify import AdaptiveParameters
        ctx = self.context('Implement a module named TopModule.\n- input x\n- output z')
        data = ctx.store['adaptive']
        data['settings'] = AdaptiveParameters().model_dump(mode='json')
        data['routing'] = RouteDecision('model', 'analysis_route', (), ())
        data['draft_reply'] = SimpleNamespace(call_id='m9')
        sent = {}

        def fake_request(ctx_arg, stage, messages, **kwargs):
            sent['stage'], sent['messages'] = stage, messages
            return SimpleNamespace(call_id='m10', content='', finish_reason='stop')

        with patch('agent.orchestration.nodes.adaptive._request', side_effect=fake_request):
            state = rescue(ctx, State())
        self.assertEqual(sent['stage'], 'rescue')
        self.assertFalse(any('Previous delivery failure' in item['content']
                             for item in sent['messages']))
        self.assertEqual(self.artifacts['adaptive/rescue-context.json']['reason'],
                         'draft_failure_missing')
        self.assertFalse(self.artifacts['adaptive/rescue-context.json']['failure_present'])
        self.assertEqual(state['stop_reason'], 'no_complete_candidate')

    # -- repair node: evidence indexes reach the request and the v2 parser ---
    def test_repair_node_delivers_diagnostic_codes_to_request_and_parser(self):
        import json
        from agent.domain.rtl.adaptive_analysis import RouteDecision
        from agent.orchestration.workflows.adaptive_verify import AdaptiveParameters
        ctx = self.context('Implement a module named TopModule.\n- input x\n- input y\n- output z')
        data = ctx.store['adaptive']
        parent = ctx.candidates.create(
            'module TopModule(input x, input y, output z); assign z = x; endmodule',
            source_stage='draft', round=1)
        check = SimpleNamespace(
            status='failed', failure_kind='code',
            details={'execution_id': 'lint-exec',
                     'repair_diagnostics': {'items': [
                         {'code': 'VRFC 10-9336', 'severity': 'error',
                          'message': 'syntax error near endmodule'}]}})
        data.update(
            settings=AdaptiveParameters().model_dump(mode='json'),
            repair_used=False, rescue_used=False, checker=None,
            routing=RouteDecision('structural', 'first_draft_rescue', (), ()),
            opportunity={'kind': 'structure', 'check': 'lint',
                         'failure': {'details': check.details}},
            assessments={parent.id: SimpleNamespace(structure={'lint': check})},
            observations={})
        fence = '`' * 3
        value = {'attribution_contract_version': 2, 'decision': 'rtl_error',
                 'reason': 'The port declaration is malformed.',
                 'candidate_conclusion': 'unverified',
                 'checker_defect': None,
                 'rtl_defect': {'locations': ['module header'],
                                'diagnostics': [{'code': 'VRFC 10-9336'}]}}
        content = (fence + 'json\n' + json.dumps(value) + '\n' + fence
                   + '\n\n' + fence + 'verilog\nmodule TopModule(input x, input y, output z);'
                   ' assign z = x & y; endmodule\n' + fence + '\n')
        sent = {}

        def fake_request(ctx_arg, stage, messages, **kwargs):
            sent['stage'], sent['messages'] = stage, messages
            return SimpleNamespace(call_id='m20', content=content, finish_reason='stop')

        with patch('agent.orchestration.nodes.adaptive._request', side_effect=fake_request):
            state = repair(ctx, State({'target_id': parent.id}))
        self.assertEqual(sent['stage'], 'repair')
        user = json.loads(sent['messages'][1]['content'])
        self.assertEqual(user['public_task']['expected_interface'],
                         ctx.task.expected_interface.public_dict())
        self.assertEqual(user['evidence']['diagnostic_codes'], ['VRFC 10-9336'])
        self.assertEqual(self.artifacts['adaptive/repair-evidence.json']['diagnostic_codes'],
                         ['VRFC 10-9336'])
        self.assertEqual(state['action'], 'recheck')
        self.assertTrue(data['repair_used'])
        self.assertNotEqual(state['target_id'], parent.id)
        self.assertIsNotNone(ctx.candidates.get(state['target_id']))

    # -- review contract retry and exhausted-revision semantics --------------
    def review_context(self):
        from agent.orchestration.workflows.adaptive_verify import AdaptiveParameters
        self.artifacts = {}
        record = SimpleNamespace(
            write_json=lambda name, value: self.artifacts.update({name: value}),
            write_text=lambda *args: None,
            emit=lambda *args, **kwargs: None,
        )
        data = {
            'settings': AdaptiveParameters().model_dump(mode='json'),
            'attempted': set(), 'request_outcomes': {},
            'checker_revision_used': False, 'review_retry_used': False,
            'review_contract': {}, 'checker': None, 'checker_draft': object(),
            'ledger': SimpleNamespace(snapshot=lambda: {}),
        }
        ctx = SimpleNamespace(
            task=TaskSpec.from_text('public', 'Implement a module named TopModule.'),
            store={'adaptive': data}, record=record, prompts=TemplateRenderer())
        return ctx, data

    @staticmethod
    def review_reply(call_id):
        return SimpleNamespace(call_id=call_id, content='review', finish_reason='stop')

    @staticmethod
    def frozen_review(status, retryable, violations=()):
        return SimpleNamespace(status=status, retryable=retryable,
                               violations=list(violations),
                               public_dict=lambda: {'status': status})

    def test_review_contract_invalid_retries_once_then_approves(self):
        ctx, data = self.review_context()
        first = self.frozen_review('invalid', True, ['R-01 missing fields'])
        second = self.frozen_review('approved', False)
        with patch('agent.orchestration.nodes.adaptive._request',
                   side_effect=[self.review_reply('m1'), self.review_reply('m2')]) as request, \
             patch('agent.orchestration.nodes.adaptive.review_request',
                   return_value=[{'role': 'user', 'content': 'review'}]) as review_req, \
             patch('agent.orchestration.nodes.adaptive.approve_review',
                   side_effect=[first, second]):
            frozen = _review_checker(ctx, object(), 'review')
        self.assertEqual(frozen.status, 'approved')
        self.assertEqual([call.args[1] for call in request.call_args_list],
                         ['review', 'review_retry'])
        self.assertEqual(review_req.call_args_list[1].kwargs['violations'],
                         ['R-01 missing fields'])
        self.assertTrue(data['review_retry_used'])
        contract = self.artifacts['adaptive/review-contract.json']['review']
        self.assertEqual(contract['attempts'], 2)
        self.assertEqual(contract['model_calls'], 2)
        self.assertTrue(contract['retry_used'])
        self.assertEqual(contract['status'], 'approved')
        self.assertEqual(contract['first_violations'], ['R-01 missing fields'])

    def valid_review_text(self, task, draft):
        import json
        from agent.domain.rtl.adaptive_check import review_request
        user = json.loads(review_request(task, draft)[1]['content'])
        value = {
            'review_contract_version': 2,
            'checker_hash': user['checker_hash'],
            'expected_table_sha256': user['expected_table_sha256'],
            'decision': 'accept',
            'reason': 'Both input values are compared against the public identity requirement.',
            'checked_requirements': ['identity'],
            'requirement_reviews': [{
                'requirement_id': 'identity', 'verdict': 'supported',
                'witness': {'case_id': 'both', 'steps': [
                    {'step': 0, 'outputs': {'y': 0}},
                    {'step': 1, 'outputs': {'y': 1}}]}}],
            'claims': [], 'state_phase_claims': [], 'init_claims': [],
            'degenerate_outputs': [], 'counterexamples': [],
        }
        return json.dumps(value)

    def test_review_retry_uses_the_real_v2_contract_validator(self):
        import json
        from agent.domain.rtl.adaptive_check import parse_checker
        ctx, data = self.review_context()
        legacy = json.dumps({'checker_hash': 'ignored', 'decision': 'accept',
                             'reason': 'legacy response', 'checked_requirements': ['identity']})
        task = TaskSpec.from_text(
            'synthetic', 'The output y equals the one-bit input a.',
            'module TopModule(input a, output y); endmodule')
        checker = {
            'schema_version': 1, 'mode': 'behavior',
            'ports': {'a': {'direction': 'input', 'width': 1},
                      'y': {'direction': 'output', 'width': 1}},
            'clock': None, 'state': {}, 'outputs': {'y': {'ref': 'a'}},
            'requirements': [{'id': 'identity', 'quote': task.prompt}],
            'cases': [{'id': 'both', 'requirements': ['identity'], 'exhaustive': True}],
        }
        draft = parse_checker(json.dumps({'status': 'ready', 'checker': checker}),
                              task, 'model', finish_reason='stop')
        self.assertEqual(draft.status, 'ready', draft.reason)
        valid = self.valid_review_text(task, draft)
        ctx.task = task
        sent = []

        def fake_request(ctx_arg, stage, messages, **kwargs):
            sent.append((stage, json.loads(messages[1]['content'])))
            return SimpleNamespace(call_id=f'm-{len(sent)}',
                                   content=legacy if len(sent) == 1 else valid,
                                   finish_reason='stop')

        with patch('agent.orchestration.nodes.adaptive._request', side_effect=fake_request):
            frozen = _review_checker(ctx, draft, 'review')
        self.assertEqual(frozen.status, 'approved')
        self.assertEqual([stage for stage, _ in sent], ['review', 'review_retry'])
        self.assertNotIn('contract_violations', sent[0][1])
        self.assertTrue(sent[1][1]['contract_violations'])
        contract = self.artifacts['adaptive/review-contract.json']['review']
        self.assertEqual(contract['first_status'], 'invalid')
        self.assertTrue(contract['first_violations'])
        self.assertEqual(contract['status'], 'approved')

    def test_reject_after_review_retry_never_reenters_revision(self):
        ctx, data = self.review_context()
        first = self.frozen_review('invalid', True, ['R-02 reason'])
        second = self.frozen_review('rejected', False)
        with patch('agent.orchestration.nodes.adaptive._request',
                   side_effect=[self.review_reply('m1'), self.review_reply('m2')]), \
             patch('agent.orchestration.nodes.adaptive.review_request',
                   return_value=[{'role': 'user', 'content': 'review'}]), \
             patch('agent.orchestration.nodes.adaptive.approve_review', side_effect=[first, second]):
            state = review_checker(ctx, State())
        # A distinct status keeps the graph on the default (finish) edge.
        self.assertEqual(state['checker_status'], 'rejected_after_review_retry')
        self.assertTrue(data['checker_revision_used'])
        with self.assertRaises(ValueError):
            revise_checker(ctx, State())

    def test_non_retryable_review_contract_is_not_retried(self):
        ctx, data = self.review_context()
        invalid = self.frozen_review('invalid', False, ['R-02 reason'])
        with patch('agent.orchestration.nodes.adaptive._request',
                   side_effect=[self.review_reply('m1')]) as request, \
             patch('agent.orchestration.nodes.adaptive.review_request',
                   return_value=[{'role': 'user', 'content': 'review'}]), \
             patch('agent.orchestration.nodes.adaptive.approve_review', side_effect=[invalid]):
            state = review_checker(ctx, State())
        self.assertEqual(state['checker_status'], 'invalid')
        self.assertEqual(len(request.call_args_list), 1)
        self.assertFalse(data['review_retry_used'])
        contract = self.artifacts['adaptive/review-contract.json']['review']
        self.assertEqual(contract['attempts'], 1)
        self.assertFalse(contract['retryable'])

    def test_rereview_never_retries_the_contract(self):
        ctx, data = self.review_context()
        invalid = self.frozen_review('invalid', True, ['R-02 reason'])
        with patch('agent.orchestration.nodes.adaptive._request',
                   side_effect=[self.review_reply('m1')]) as request, \
             patch('agent.orchestration.nodes.adaptive.review_request',
                   return_value=[{'role': 'user', 'content': 'review'}]), \
             patch('agent.orchestration.nodes.adaptive.approve_review', side_effect=[invalid]):
            frozen = _review_checker(ctx, object(), 'rereview')
        self.assertEqual(frozen.status, 'invalid')
        self.assertEqual(len(request.call_args_list), 1)
        self.assertFalse(data['review_retry_used'])

    def test_denied_review_retry_records_not_sent(self):
        ctx, data = self.review_context()
        invalid = self.frozen_review('invalid', True, ['R-01 missing fields'])
        with patch('agent.orchestration.nodes.adaptive._request',
                   side_effect=[self.review_reply('m1'), None]), \
             patch('agent.orchestration.nodes.adaptive.review_request',
                   return_value=[{'role': 'user', 'content': 'review'}]), \
             patch('agent.orchestration.nodes.adaptive.approve_review', side_effect=[invalid]):
            state = review_checker(ctx, State())
        self.assertEqual(state['checker_status'], 'invalid')
        self.assertTrue(data['review_retry_used'])
        contract = self.artifacts['adaptive/review-contract.json']['review']
        self.assertEqual(contract['retry_status'], 'not_sent')
        self.assertEqual(contract['model_calls'], 1)

    def test_initialize_and_finish_record_review_contract(self):
        from agent.orchestration.workflows.adaptive_verify import AdaptiveParameters
        self.artifacts = {}
        record = SimpleNamespace(
            write_json=lambda name, value: self.artifacts.update({name: value}),
            write_text=lambda *args: None,
            emit=lambda *args, **kwargs: None,
        )
        settings = AdaptiveParameters().model_dump(mode='json')
        ctx = SimpleNamespace(
            task=TaskSpec.from_text('public', 'Implement a module named TopModule.'),
            store={}, record=record,
            candidates=SimpleNamespace(selected_id=None),
            budget=SimpleNamespace(remaining=lambda: 600.0))
        initialize(ctx, State({'settings': settings}))
        data = ctx.store['adaptive']
        self.assertFalse(data['review_retry_used'])
        self.assertEqual(data['review_contract'], {})
        data.update(assessments={},
                    routing=SimpleNamespace(public_dict=lambda: {'route': 'structural'}),
                    ledger=SimpleNamespace(snapshot=lambda: {}),
                    request_outcomes={},
                    review_contract={'review': {'attempts': 2, 'status': 'approved',
                                                'violations': [], 'model_calls': 2}},
                    review_retry_used=True)
        finish(ctx, State({'stop_reason': 'assessment_complete',
                            'checker_status': 'approved'}))
        result = self.artifacts['adaptive/result.json']
        self.assertTrue(result['review_retry_used'])
        self.assertEqual(result['review_contract']['review']['attempts'], 2)

    # -- workflow parameters and Skill admission at graph construction -------
    def test_adaptive_parameters_review_retry_and_skill_gate(self):
        from burr.core import ApplicationBuilder
        from agent.orchestration.workflows.adaptive_verify import AdaptiveParameters, build
        parameters = AdaptiveParameters()
        self.assertEqual((parameters.review_retry.timeout_s,
                          parameters.review_retry.max_tokens), (1200.0, 32768))
        # normal 5, one retry 6, revision path 7 completions.
        self.assertEqual(parameters.max_calls, 7)
        build(ApplicationBuilder(), parameters)
        with self.assertRaises(ValueError):
            build(ApplicationBuilder(),
                  AdaptiveParameters(sequential_skill='rtl-sequential-state-update-v3'))


if __name__ == '__main__':
    unittest.main()
