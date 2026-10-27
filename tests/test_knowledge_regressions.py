"""Synthetic regressions for optional retrieval and observed delivery evidence."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

import httpx

from agent.kit import State
from agent.domain.knowledge.context import prepare
from agent.domain.knowledge.outcome import summarize
from agent.domain.knowledge.runtime import bundle
from agent.domain.rtl.candidate import CandidateStore
from agent.domain.rtl.result import CheckResult, bind_result, checker_hash
from agent.domain.rtl.task import TaskSpec
from agent.runtime.budget import Budget
from agent.observability.recorder import Recorder


class KnowledgeRegressions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.record = Recorder(self.root)
        self.addCleanup(self.record.close)
        self.store = CandidateStore(self.record, self.root)
        self.task = TaskSpec.from_text('synthetic', 'Implement module TopModule(); endmodule')
        self.ctx = NS(store={}, record=self.record, candidates=self.store, task=self.task,
                      budget=Budget(900, 20), llm=NS(tokenize=lambda m: len(json.dumps(m)) // 4),
                      config=NS(services=NS(model=NS(max_model_len=65536))))

    def parent(self):
        return self.store.create('module TopModule; assign y = {8{x}, x}; endmodule',
                                 call_id='draft-call')

    def prepare(self, messages, parent, check, mode, **retrieval):
        return prepare(self.ctx, messages, parent, {'check': check, 'execution_id': 'lint-execution'},
                       skill_ids=[], skill_phases=['generate', 'repair'], rag=False,
                       skill_mode='off', rag_mode=mode, max_tokens=1024, max_extra_tokens=2048,
                       retrieval_options=retrieval)

    def embedding_case(self, payload, *, fallback='exact', mode='on', strategy='dense', transport='http'):
        parent = self.parent()
        item = dict(code='VRFC 10-4982', tool='xvlog', version='2026.1', severity='error',
                    process_status='failed', message="syntax error near ','", command_index=0)
        check = bind_result(CheckResult('failed', item['message'], failure_kind='code',
                            details={'knowledge_diagnostics': {'complete': True, 'items': [item]}}),
                            parent, 'lint')
        messages = [{'role': 'user', 'content': 'Repair this syntax error.'}]
        original_client = httpx.Client
        def client(**kwargs):
            return original_client(transport=httpx.MockTransport(
                lambda request: httpx.Response(200, content=json.dumps(payload))), **kwargs)
        with patch('agent.domain.knowledge.runtime.httpx.Client', side_effect=client), patch(
                'agent.domain.knowledge.runtime.subprocess.run', return_value=NS(stdout=json.dumps(payload))):
            packed, report = self.prepare(messages, parent, check, mode, strategy=strategy,
                fallback=fallback, embedding_url='http://127.0.0.1:8765',
                embedding_transport=transport, embedding_ssh_host='synthetic-host')
        return messages, packed, report

    def test_invalid_embedding_schema_obeys_fallback_in_all_modes_and_transports(self):
        alias = bundle()[0]['model']['runtime_alias']
        invalid = [None, [], 'text', 3, True, {}, {'model': alias}]
        invalid += [{'model': alias, 'data': value} for value in
                    (None, {}, [], [None], [[]], [{}], [{'embedding': []}],
                     [{'embedding': [1.0]}], [{'embedding': [0.0] * 1024}])]
        for transport in ('http', 'ssh'):
            for mode in ('on', 'shadow'):
                for strategy in ('dense', 'hybrid'):
                    for fallback in ('exact', 'empty'):
                        for payload in invalid:
                            with self.subTest(transport=transport, mode=mode, strategy=strategy,
                                              fallback=fallback, payload=repr(payload)[:100]):
                                messages, packed, report = self.embedding_case(payload,
                                    transport=transport, mode=mode, strategy=strategy, fallback=fallback)
                                retrieval = report['retrieval']
                                self.assertEqual(retrieval['effective_strategy'], fallback)
                                self.assertIn('embedding_error', retrieval)
                                self.assertIn('embedding_ms', retrieval)
                                if fallback == 'exact':
                                    self.assertTrue(retrieval['admitted'])
                                else:
                                    self.assertEqual(retrieval['reason'], 'retrieval_unavailable')
                                    self.assertFalse(retrieval['admitted'])
                                self.assertEqual(packed == messages, mode == 'shadow' or fallback == 'empty')

    def test_valid_embedding_and_model_mismatch(self):
        data, _ = bundle()
        payload = {'model': data['model']['runtime_alias'],
                   'data': [{'embedding': data['documents'][0]['vector']}]}
        _, packed, report = self.embedding_case(payload)
        self.assertEqual(report['retrieval']['effective_strategy'], 'dense')
        self.assertNotIn('embedding_error', report['retrieval'])
        self.assertTrue(report['sent'])
        self.assertIn('[Knowledge Card', packed[-1]['content'])
        payload['model'] = 'different-model'
        _, _, report = self.embedding_case(payload)
        self.assertEqual(report['retrieval']['effective_strategy'], 'exact')
        self.assertEqual(report['retrieval']['embedding_error'], 'ValueError')

    def adaptive_messages(self, mode, *, banner=False, probe_version='2026.1'):
        from agent.orchestration.nodes.adaptive import initialize
        from agent.domain.rtl.adaptive_assessment import CandidateAssessment
        from agent.domain.rtl.adaptive_repair import repair_request
        from agent.domain.rtl.adaptive_selection import repair_opportunity
        from agent.domain.rtl.vivado import lint
        from agent.orchestration.workflows.adaptive_verify import AdaptiveParameters

        self.ctx.store = {}
        initialize(self.ctx, State({'settings': AdaptiveParameters(
            skill_mode='off', rag_mode=mode).model_dump(mode='json')}))
        # Reuse one identity so equality covers the actual prompt, including IDs.
        parent = self.store.get('c001') if self.store.values() else self.parent()
        log = "ERROR: [VRFC 10-4982] syntax error near ',' [solution.sv:1]"
        if banner:
            log = 'xvlog v2026.1\n' + log
        commands = []
        def run(command, **kwargs):
            commands.append(command)
            if command[-1] == '--version':
                return NS(rc=0 if probe_version else 1,
                          stdout=f'xvlog v{probe_version}' if probe_version else 'probe failed')
            return NS(rc=1, stdout=log)
        self.ctx.processes = NS(run=run)
        with patch('agent.domain.rtl.vivado.executable', side_effect=lambda name: '/synthetic/' + name):
            check = bind_result(lint(self.ctx, parent, timeout_s=30), parent, 'lint')
        check.details['execution_id'] = 'lint-execution'
        assessment = CandidateAssessment(parent.id, parent.code_hash, None, None,
            'assessment-execution', '', '', checker_hash(), structure={'lint': check})
        evidence = repair_opportunity(assessment.public_dict())
        self.assertIsNotNone(evidence)
        original = deepcopy(check.trace_dict())
        messages = repair_request(self.task, parent, evidence)
        packed, report = self.prepare(messages, parent, check, mode)
        self.assertEqual(check.trace_dict(), original)
        return packed, report, check, commands

    def test_adaptive_shadow_probe_does_not_change_actual_repair_messages(self):
        off, _, off_check, off_commands = self.adaptive_messages('off')
        shadow, report, shadow_check, shadow_commands = self.adaptive_messages('shadow')
        self.assertEqual(len(off_commands), 1)
        self.assertEqual(shadow_commands[-1], ('/synthetic/xvlog', '--version'))
        self.assertIsNone(off_check.details['knowledge_commands'][0]['version'])
        self.assertEqual(shadow_check.details['knowledge_commands'][0]['version'], '2026.1')
        self.assertTrue(report['retrieval']['admitted'])
        self.assertFalse(report['sent'])
        self.assertEqual(off, shadow)

    def test_failed_probe_is_not_added_to_solver_messages(self):
        off, _, _, _ = self.adaptive_messages('off')
        shadow, report, check, _ = self.adaptive_messages('shadow', probe_version=None)
        self.assertTrue(check.details['knowledge_version_probes'])
        self.assertFalse(report['retrieval']['admitted'])
        self.assertEqual(off, shadow)

    def test_banner_version_remains_in_prompt_without_extra_probe(self):
        off, _, _, _ = self.adaptive_messages('off', banner=True)
        shadow, _, _, commands = self.adaptive_messages('shadow', banner=True)
        self.assertEqual(len(commands), 1)
        self.assertEqual(off, shadow)
        command = json.loads(off[-1]['content'])['evidence']['failure']['details']['knowledge_commands'][0]
        self.assertEqual((command['version'], command['version_source']), ('2026.1', 'banner'))

    def test_on_can_still_admit_using_probe_evidence(self):
        _, report, check, _ = self.adaptive_messages('on')
        self.assertTrue(report['sent'])
        self.assertEqual(check.details['knowledge_commands'][0]['version_source'], 'version_probe')

    def outcome(self):
        return summarize(self.root / 'trace.jsonl', self.root / 'solution.v')

    def test_baseline_creation_without_completeness_evidence_stays_unknown(self):
        from agent.orchestration.nodes.baseline import extract
        import baseline
        for index, content in enumerate(('', 'Cannot provide RTL.', 'module TopModule;',
                                         'module TopModule; endmodule')):
            with self.subTest(content=content):
                call_id = f'call-{index}'
                self.ctx.store[call_id] = NS(content=content, call_id=call_id, finish_reason='stop')
                state = extract(self.ctx, State({'reply_id': call_id, 'round': index + 1}))
                candidate = self.store.select(state['target_id'], 'baseline')
                self.assertEqual(candidate.code, baseline.extract(content, 'rtl'))
                outcome = self.outcome()
                self.assertTrue(outcome['solution_matches_selection'])
                self.assertIsNone(outcome['latest_complete_candidate_id'])
                self.assertIsNone(outcome['selected_candidate_complete'])
                self.assertIsNone(outcome['selected_latest_complete'])

    def test_unvalidated_later_candidate_does_not_replace_confirmed_complete(self):
        from agent.orchestration.nodes.extract import extract
        self.ctx.store['draft-call'] = NS(content='module TopModule; endmodule',
                                         call_id='draft-call', finish_reason='stop')
        state = extract(self.ctx, State({'reply_id': 'draft-call', 'round': 1}))
        confirmed = self.store.get(state['target_id'])
        unvalidated = self.store.create('module TopModule;', call_id='later-call')
        self.store.select(unvalidated.id, 'baseline')
        outcome = self.outcome()
        self.assertEqual(outcome['latest_complete_candidate_id'], confirmed.id)
        self.assertIsNone(outcome['selected_candidate_complete'])
        self.assertIsNone(outcome['selected_latest_complete'])
        self.store.select(confirmed.id, 'retain_complete')
        self.assertTrue(self.outcome()['selected_latest_complete'])

    def test_adaptive_delivery_joins_by_unique_model_call_and_retains_old_draft(self):
        from agent.orchestration.nodes.adaptive import _candidate
        old = _candidate(self.ctx, NS(content='module TopModule; endmodule',
                                     call_id='draft-call', finish_reason='stop'))
        self.assertTrue(self.outcome()['selected_latest_complete'])
        child = _candidate(self.ctx, NS(content='No complete RTL.', call_id='repair-call',
                                       finish_reason='stop'), parent=old, stage='repair')
        self.assertIsNone(child)
        outcome = self.outcome()
        self.assertEqual(outcome['latest_complete_candidate_id'], old.id)
        self.assertTrue(outcome['selected_candidate_complete'])
        self.assertFalse(outcome['deliveries'][-1]['complete_new_draft'])
        child = _candidate(self.ctx, NS(content='module TopModule; wire x; endmodule',
            call_id='new-repair-call', finish_reason='stop'), parent=old, stage='repair')
        self.assertEqual(self.outcome()['latest_complete_candidate_id'], child.id)
        self.assertFalse(self.outcome()['selected_latest_complete'])
        self.store.select(child.id, 'synthetic_selection')
        self.assertTrue(self.outcome()['selected_latest_complete'])

    def test_explicit_incomplete_delivery_is_false_not_unknown(self):
        candidate = self.store.create('module TopModule;', call_id='draft-call')
        self.store.select(candidate.id, 'baseline')
        self.record.emit('extract', 'result', source_call_id='draft-call',
                         candidate_id=candidate.id, complete_new_draft=False)
        outcome = self.outcome()
        self.assertFalse(outcome['selected_candidate_complete'])
        self.assertFalse(outcome['selected_latest_complete'])
        self.assertIsNone(outcome['latest_complete_candidate_id'])

    def test_delivery_cannot_bind_to_other_call_or_ambiguous_candidate(self):
        first = self.store.create('module TopModule; endmodule', call_id='shared-call')
        self.store.create('module TopModule; endmodule', call_id='shared-call')
        self.store.select(first.id, 'fallback')
        self.record.emit('extract', 'delivery', source_call_id='shared-call', complete_new_draft=True)
        self.record.emit('extract', 'result', source_call_id='other-call',
                         candidate_id=first.id, complete_new_draft=True)
        self.assertIsNone(self.outcome()['latest_complete_candidate_id'])


if __name__ == '__main__':
    unittest.main()
