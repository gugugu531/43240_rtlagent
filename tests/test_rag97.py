"""Regression tests for real research admission, release integrity and assembly."""

import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

from agent.config import ROOT
from agent.domain.knowledge.context import prepare
from agent.domain.knowledge.pregen import decide, extract_spec, PREDICATES, retrieve_spec
from agent.domain.knowledge.research import load_bundle, load_scope, scope_guard, validate_bundle, render, validate_vector_index, LOCK_PATH
from agent.domain.knowledge.release import fingerprint
from agent.observability.recorder import Recorder
from agent.domain.rtl.task import TaskSpec


class Rag97(unittest.TestCase):
    def setUp(self):
        self.data = load_bundle()
        self.cards = {r['card_id']: r for r in self.data['cards']}
        self.queries = json.loads((ROOT / 'dev/optimization-v25/retrieval-queries.json').read_text())['queries']

    def test_scope_is_a_partition_and_every_frozen_card_is_denied(self):
        scope = load_scope()
        self.assertEqual(len([r for r in scope['cards'] if r['status'] == 'allowed_research']), 97)
        frozen = [r for r in scope['cards'] if r['status'] == 'frozen']
        self.assertEqual(len(frozen), 39)
        for row in frozen:
            cid = row['candidate_id']
            self.assertFalse(scope_guard(cid))
            self.assertNotIn(cid, self.cards)
            d = decide({'card_id': cid}, 'Implement a related design.')
            self.assertFalse(d['admit']); self.assertEqual(d['reason'], 'card_frozen')
        self.assertFalse(scope_guard('v9-unknown-new-card'))

    def test_real_admission_from_text_not_case_labels(self):
        for query in self.queries:
            with self.subTest(query=query['query_id']):
                actual = decide(self.cards[query['family']], query['prompt'], query['interface'])
                self.assertEqual(actual['decision_class'], query['expected_target_decision'], actual)

    def test_mutating_evidence_changes_decision(self):
        card = self.cards['v9-lang-conditional-x-merge']
        positive = 'Implement a mux selector with X/Z behavior and bit merging.'
        self.assertTrue(decide(card, positive)['admit'])
        self.assertFalse(decide(card, positive.replace('X/Z', 'strictly two-state'))['admit'])
        self.assertEqual(decide(card, positive + ' Never use a conditional expression.')['decision_class'], 'unknown')
        self.assertEqual(decide(card, positive, supplied_messages=[{'content': 'Use the conditional operator.'}])['decision_class'], 'not_needed')

    def test_asset_mutation_is_failure(self):
        card = copy.deepcopy(self.cards['v9-lang-conditional-x-merge'])
        card['narrow_fact'] += ' changed'
        self.assertEqual(decide(card, 'Implement a mux selector with X/Z behavior.')['decision_class'], 'failure')

    def test_published_identity_sets_not_just_counts(self):
        lock = json.loads((ROOT / LOCK_PATH).read_text())
        scope = load_scope()
        for field in ('cards', 'rules', 'documents'):
            broken = copy.deepcopy(self.data)
            broken[field][0] = copy.deepcopy(broken[field][1])
            with self.subTest(field=field), self.assertRaises(ValueError): validate_bundle(broken, lock, scope)
        broken = copy.deepcopy(self.data); broken['cards'][0]['narrow_fact'] += ' changed'
        with self.assertRaises(ValueError): validate_bundle(broken, lock, scope)

    def test_extracted_facts_bind_original_offsets(self):
        prompt = 'Add unsigned four-bit inputs including carry at the rising clock edge.'
        interface = 'module TopModule(input [3:0] a, output [4:0] sum); endmodule'
        e = extract_spec(prompt, interface)
        for fact in e['facts']:
            self.assertEqual({'prompt': prompt, 'interface': interface}[fact['source']][fact['start']:fact['end']], fact['text'])
        self.assertNotIn('execution_id', e)

    def context(self, prompt):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        record = Recorder(tmp.name); self.addCleanup(record.close)
        return NS(store={}, record=record, task=TaskSpec.from_text('local-test', prompt),
            llm=NS(tokenize=lambda m: len(json.dumps(m))//4),
            config=NS(services=NS(model=NS(max_model_len=65536))))

    def test_real_assembly_on_shadow_off_and_budget(self):
        prompt = 'Implement a four-bit mux selector with X/Z behavior: equal bits remain known and differing bits become unknown.'
        ctx = self.context(prompt)
        messages = [{'role': 'user', 'content': prompt}]
        options = dict(skill_ids=[], skill_phases=['generate'], rag=False, max_tokens=1024,
                       max_extra_tokens=2048, retrieval_options={'strategy': 'bm25', 'pre_generation': True})
        for mode in ('off', 'shadow'):
            actual, trace = prepare(ctx, messages, None, None, rag_mode=mode, **options)
            self.assertEqual(actual, messages); self.assertFalse(trace['sent'])
        actual, trace = prepare(ctx, messages, None, None, rag_mode='on', **options)
        self.assertEqual(trace['sent'], ['v9-lang-conditional-x-merge'])
        self.assertIn('safe_example:', actual[-1]['content'])
        self.assertEqual(trace['retrieval']['actually_sent'], trace['sent'])
        actual, trace = prepare(ctx, messages, None, None, rag_mode='on', **(options | {'max_extra_tokens': 0}))
        self.assertEqual(actual, messages); self.assertFalse(trace['sent'])

    def test_dense_missing_real_vectors_returns_failure_without_fabrication(self):
        with patch('agent.domain.knowledge.pregen.read_vector_index', side_effect=OSError('unavailable')):
            cards, trace = retrieve_spec('Implement a mux selector with X/Z behavior.', '', {'strategy': 'dense', 'pre_generation': True})
        self.assertFalse(cards); self.assertEqual(trace['empty_kind'], 'failure')

    def test_frozen_card_cannot_bypass_assembly_with_forged_retriever(self):
        ctx = self.context('Implement a module.')
        frozen = next(r['candidate_id'] for r in load_scope()['cards'] if r['status'] == 'frozen')
        fake = {'card_id': frozen, 'version': 'forged', 'projection_text': 'unsafe'}
        messages = [{'role': 'user', 'content': ctx.task.prompt}]
        with patch('agent.domain.knowledge.pregen.retrieve_spec', return_value=([fake], {'admitted': [frozen]})):
            actual, trace = prepare(ctx, messages, None, None, skill_ids=[], skill_phases=['generate'], rag=False,
                rag_mode='on', max_tokens=1024, max_extra_tokens=2048,
                retrieval_options={'strategy': 'bm25', 'pre_generation': True})
        self.assertEqual(actual, messages); self.assertFalse(trace['sent'])

    def test_real_first_generate_node_sends_the_packed_first_request(self):
        from contextlib import nullcontext
        from agent.kit import State
        from agent.orchestration.nodes.generate import generate
        from agent.context.prompts import TemplateRenderer
        from agent.domain.rtl.candidate import CandidateFactory
        prompt = 'Implement a four-bit mux selector with X/Z behavior: equal bits remain known and differing bits become unknown.'
        actual_requests = []
        for mode in ('off', 'shadow', 'on'):
            ctx = self.context(prompt)
            ctx.prompts = TemplateRenderer()
            ctx.llm.generation = {}
            ctx.llm.request_window = lambda seconds: nullcontext()
            def capture(messages, **kwargs):
                actual_requests.append((mode, copy.deepcopy(messages)))
                self.assertEqual(kwargs['purpose'], 'generate')
                return NS(call_id='first-call', content='module TopModule;endmodule', finish_reason='stop')
            ctx.llm.chat = capture
            generate(ctx, State({'target_id': None, 'round': 0, 'feedback': ''}), rag_mode=mode,
                retrieval={'strategy': 'bm25', 'pre_generation': True}, max_tokens=1024)
        self.assertEqual(actual_requests[0][1], actual_requests[1][1])
        self.assertNotEqual(actual_requests[0][1], actual_requests[2][1])
        self.assertIn('[Knowledge Card v9-lang-conditional-x-merge@', actual_requests[2][1][-1]['content'])

    def test_dense_protocol_with_bound_test_vectors_and_service_error(self):
        # Synthetic vectors validate transport/ranking only, never dense quality.
        index = {'release_id': self.data['release_id'], 'model': self.data['model'],
                 'documents_sha256': fingerprint(self.data['documents']), 'vectors': []}
        target = 'v9-lang-conditional-x-merge'
        for d in self.data['documents']:
            vec = [0.0]*self.data['model']['dimensions']; vec[0 if d['card_id']==target else 1] = 1.0
            index['vectors'].append({'card_id': d['card_id'], 'text_sha256': d['text_sha256'], 'vector': vec})
        q=[1.0]+[0.0]*(self.data['model']['dimensions']-1)
        with patch('agent.domain.knowledge.pregen.read_vector_index', return_value=index), patch('agent.domain.knowledge.runtime.embed', return_value=q):
            # Supply the merge contract so this test isolates transport/ranking.
            cards, trace=retrieve_spec('Implement a four-bit mux selector with X/Z bit merging.', '', {'strategy':'dense','pre_generation':True})
            self.assertEqual([c['card_id'] for c in cards], [target])
        with patch('agent.domain.knowledge.pregen.read_vector_index', return_value=index), patch('agent.domain.knowledge.runtime.embed', side_effect=OSError('endpoint unavailable')):
            cards, trace=retrieve_spec('Implement a mux selector with X/Z behavior.', '', {'strategy':'dense','pre_generation':True})
            self.assertFalse(cards);self.assertEqual(trace['empty_kind'],'failure')
        broken=copy.deepcopy(index);broken['vectors'][0]['text_sha256']='0'*64
        with self.assertRaises(ValueError):validate_vector_index(broken,self.data)

    def test_variable_release_size_and_duplicates_with_rehashed_outer_package(self):
        from agent.domain.knowledge.release import bind_release, validate_release
        from agent.domain.knowledge.assets import sha256
        data=json.loads((ROOT/'knowledge/runtime-v1.json').read_text())
        legacy=(ROOT/'knowledge/cards.json').read_bytes()
        for field in ('cards','rules','documents'):
            row=copy.deepcopy(data[field][0]);row['card_id']='additional-test-card';data[field].append(row)
        data=bind_release(data,legacy)
        raw=json.dumps(data).encode()
        lock={k:data[k] for k in ('release_id','policy_sha256','index_sha256','legacy_cards_sha256')}
        lock.update(release_sha256=sha256(raw),card_count=33)
        validate_release(data,lock,raw,legacy)
        data['rules'][-1]=copy.deepcopy(data['rules'][0])
        data=bind_release(data,legacy);raw=json.dumps(data).encode()
        lock.update(release_sha256=sha256(raw),policy_sha256=data['policy_sha256'],index_sha256=data['index_sha256'])
        with self.assertRaises(ValueError):validate_release(data,lock,raw,legacy)


if __name__ == '__main__': unittest.main()
