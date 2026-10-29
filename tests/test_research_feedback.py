"""Real admission logic evaluated against independent rejection expectations."""

import copy
from dataclasses import replace
import importlib.util
from pathlib import Path
from types import SimpleNamespace as NS
import sys
import unittest
from unittest.mock import patch
import httpx

from agent.config import ROOT
from agent.domain.knowledge.assets import sha256
from agent.domain.knowledge.feedback import bound_feedback, decide_feedback, retrieve_feedback
from agent.domain.knowledge.pregen import PREDICATES
from agent.domain.knowledge.research import load_bundle, load_scope
from agent.domain.knowledge.runtime import embed
from agent.domain.knowledge.policy import RetrievalOptions
from agent.domain.rtl.candidate import CandidateFactory
from agent.domain.rtl.result import CheckResult, bind_result


def fixture():
    here=ROOT/'dev/optimization-v26';sys.path.insert(0,str(here))
    spec=importlib.util.spec_from_file_location('feedback_public_fixture',here/'local_checks.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    task,suite,variants=module.public_case()
    parent=CandidateFactory().create(variants['target'],source_stage='synthetic-transport-test',round=1)
    first={'case_id':'carry-edge','step':0}
    check=bind_result(CheckResult(status='failed',summary='Public comparison mismatch',rc=0,
        command=(('xvlog',),('xelab',),('xsim',)),details={'failed_cases':['carry-edge'],'first_mismatch':first,
        'traces':[first|{'inputs':{'a':15,'b':1},'actual':{'sum':0},'expected':{'sum':16}}]}),parent,'functional',suite)
    return task,parent,{'check':check,'suite':suite,'execution_id':'unit-test-not-real-tool',
        'public_task_sha256':sha256(task.prompt+'\n'+task.interface)}


class ResearchFeedback(unittest.TestCase):
    def setUp(self):self.data=load_bundle();self.cards={c['card_id']:c for c in self.data['cards']}

    def test_every_allowed_card_has_both_feedback_phases_and_example(self):
        cards=[c for c in self.data['cards'] if c['card_id'].startswith(('v8-','v9-'))]
        self.assertEqual(len(cards),97)
        for c in cards:
            self.assertTrue(c['safe_example']);self.assertIn('post_diagnostic',c['phases'])
            self.assertIn('post_functional_feedback',c['phases']);self.assertFalse(c['feedback_contract']['default_injection'])

    def test_unimplemented_methods_are_not_silently_promoted(self):
        task,parent,evidence=fixture()
        pending=[c for c in self.data['cards'] if c['card_id'].startswith(('v8-','v9-')) and c['card_id'] not in PREDICATES]
        self.assertEqual(len(pending),97-len(PREDICATES))
        for c in pending:
            actual=decide_feedback(c,task,evidence,parent)
            self.assertFalse(actual['admit']);self.assertEqual(actual['decision_class'],'unknown')

    def test_existing_fact_refusal_uses_actual_supplied_text(self):
        task,parent,evidence=fixture();card=self.cards['v9-lang-remainder-sign']
        self.assertEqual(decide_feedback(card,task,evidence,parent)['decision_class'],'unknown')
        actual=decide_feedback(card,task,evidence,parent,[{'content':card['narrow_fact']}])
        self.assertEqual(actual['decision_class'],'not_needed');self.assertEqual(actual['reason'],'knowledge_already_present')
        contradicted=decide_feedback(card,task,evidence,parent,[{'content':'This claim is incorrect: '+card['narrow_fact']}])
        self.assertEqual(contradicted['decision_class'],'unknown')

    def test_changed_candidate_checker_suite_or_task_invalidates_binding(self):
        task,parent,evidence=fixture()
        self.assertEqual(bound_feedback(evidence,parent,task)[0],'post_functional_feedback')
        bad_cases=[(replace(parent,code_hash='0'*64),evidence,task),
            (parent,evidence|{'check':replace(evidence['check'],details=evidence['check'].details|{'checker_hash':'0'*64})},task),
            (parent,evidence|{'suite':{}},task),(parent,evidence,replace(task,prompt='different task')),
            (parent,evidence|{'check':replace(evidence['check'],command=(('xsim',),))},task),
            (parent,evidence|{'check':replace(evidence['check'],details=evidence['check'].details|{'traces':[]})},task)]
        for p,e,t in bad_cases:
            with self.subTest(evidence=e),self.assertRaises(ValueError):bound_feedback(e,p,t)

    def test_diagnosis_alone_is_not_functional_evidence(self):
        task,parent,evidence=fixture()
        cards,trace=retrieve_feedback(task,{'diagnosis':'rtl'},parent,{'strategy':'bm25','research_feedback':True})
        self.assertFalse(cards);self.assertFalse(trace['retrieved']);self.assertEqual(trace['empty_kind'],'unknown')

    def test_ranking_does_not_authorize_a_pending_card(self):
        task,parent,evidence=fixture()
        with patch('agent.domain.knowledge.feedback.bm25',return_value=[('v9-lang-remainder-sign',100)]):
            cards,trace=retrieve_feedback(task,evidence,parent,{'strategy':'bm25','research_feedback':True})
        self.assertFalse(cards);self.assertEqual(trace['search_pool_count'],97)
        self.assertEqual(trace['empty_kind'],'unknown');self.assertNotIn('correct_empty',trace['reason'])

    def test_dense_failure_is_failure_not_correct_empty(self):
        task,parent,evidence=fixture()
        with patch('agent.domain.knowledge.feedback.read_vector_index',side_effect=OSError('missing')):
            cards,trace=retrieve_feedback(task,evidence,parent,{'strategy':'dense','research_feedback':True})
        self.assertFalse(cards);self.assertEqual(trace['empty_kind'],'failure')

    def test_asset_and_environment_failure_are_not_unknown_or_correct_empty(self):
        task,parent,evidence=fixture()
        with patch('agent.domain.knowledge.feedback.load_bundle',side_effect=ValueError('hash mismatch')):
            cards,trace=retrieve_feedback(task,evidence,parent,{'strategy':'bm25','research_feedback':True})
        self.assertFalse(cards);self.assertEqual(trace['empty_kind'],'failure')
        evidence['check']=replace(evidence['check'],status='unavailable',failure_kind='environment')
        cards,trace=retrieve_feedback(task,evidence,parent,{'strategy':'bm25','research_feedback':True})
        self.assertFalse(cards);self.assertEqual(trace['empty_kind'],'failure')

    def test_mutated_asset_and_frozen_cards_fail_closed(self):
        task,parent,evidence=fixture();card=copy.deepcopy(self.cards['v9-lang-remainder-sign']);card['safe_example']+='changed'
        self.assertEqual(decide_feedback(card,task,evidence,parent)['decision_class'],'failure')
        frozen=[r for r in load_scope()['cards'] if r['status']=='frozen']
        for row in frozen:
            self.assertEqual(decide_feedback({'card_id':row['candidate_id']},task,evidence,parent)['decision_class'],'not_needed')

    def test_model_name_echo_cannot_bypass_advertised_identity(self):
        data=self.data|{'model':self.data['model']|{'runtime_alias':'requested-but-not-loaded'}}
        original=httpx.Client;methods=[]
        def handler(request):
            methods.append(request.method)
            return httpx.Response(200,json={'data':[{'id':self.data['model']['runtime_alias']}]})
        def client(**kwargs):return original(transport=httpx.MockTransport(handler),**kwargs)
        with patch('agent.domain.knowledge.runtime.httpx.Client',side_effect=client),self.assertRaisesRegex(ValueError,'advertised_model_mismatch'):
            embed(data,'public query',RetrievalOptions(strategy='dense',embedding_url='http://127.0.0.1:8765'))
        self.assertEqual(methods,['GET'])


if __name__=='__main__':unittest.main()
