"""Fast boundary checks; real mechanical evidence is in v32/runs, not mocks."""
import importlib.util
from pathlib import Path
import re
import sys
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'dev/optimization-v32'))
from common import cases,cards_data,sha256
from policy import decide
from query_projection import project


class BatchScreenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.rows=cases();cls.cards={c['card_id']:c for c in cards_data()['cards']}

    def invoke(self,case,variant='target',messages=(),card=None,code=None,task=None):
        source=code or case[variant];parent=NS(id='current',code=source,code_hash=sha256(source))
        signal=next(n for n,p in case['suite']['ports'].items() if p['direction']=='output')
        check=NS(id='execution',details={'first_mismatch':{'signal':signal,'actual':0,'expected':1}})
        evidence={'check':check,'execution_id':'actual-identity-is-tested-in-mechanical-preflight'}
        with patch('policy.feedback.bound_feedback',return_value=('post_functional_feedback','public mismatch')):
            return decide(card or self.cards[case['card_id']],task or case['task'],evidence,parent,messages)

    def test_twenty_distinct_cards_and_supported_targets(self):
        self.assertEqual(len({c['card_id'] for c in self.rows}),20)
        for case in self.rows:
            with self.subTest(card=case['card_id']):self.assertEqual(self.invoke(case)['decision_class'],'eligible')

    def test_neighbors_are_not_authorized_by_topic(self):
        for case in self.rows:
            with self.subTest(card=case['card_id']):self.assertIn(self.invoke(case,'adjacent')['decision_class'],('unknown','not_needed'))

    def test_known_negated_and_mutated_assets(self):
        for case in self.rows:
            with self.subTest(card=case['card_id']):
                self.assertEqual(self.invoke(case,messages=[{'content':case['known']}])['decision_class'],'not_needed')
                self.assertEqual(self.invoke(case,messages=[{'content':'Do not follow this: '+case['known']}])['decision_class'],'unknown')
                self.assertEqual(self.invoke(case,card=self.cards[case['card_id']]|{'version':'bad'})['decision_class'],'failure')

    def test_witnesses_survive_renaming_and_comments(self):
        for case in self.rows:
            source=case['target']
            for name in list(case['suite']['ports'])+[case['task'].top,'low']:
                source=re.sub(r'\b'+re.escape(name)+r'\b','renamed_'+name,source)
            from dataclasses import replace
            interface=case['task'].interface
            for name in list(case['suite']['ports'])+[case['task'].top]:interface=re.sub(r'\b'+re.escape(name)+r'\b','renamed_'+name,interface)
            # Expected output is bound independently to the renamed port.
            renamed=dict(case);renamed['suite']=dict(case['suite'],ports={'renamed_'+n:v for n,v in case['suite']['ports'].items()})
            task=replace(case['task'],interface=interface,top='renamed_'+case['task'].top)
            with self.subTest(card=case['card_id']):self.assertEqual(self.invoke(renamed,code='/* comment */'+source,task=task)['decision_class'],'eligible')

    def test_compact_projection_preserves_all_public_restrictions(self):
        case=self.rows[0];from dataclasses import replace
        task=replace(case['task'],prompt=case['task'].prompt+' Never change the interface; do not add a pipeline.')
        parent=NS(code=case['target'],code_hash=sha256(case['target']))
        evidence={'check':NS(id='current',details={'first_mismatch':{'signal':'y','actual':1,'expected':255}}),'execution_id':'current'}
        with patch('query_projection.bound_feedback',return_value=('post_functional_feedback','verbose simulator trace '*1000)):
            query,receipt=project(task,evidence,parent)
            self.assertIn(task.prompt,query);self.assertIn(task.interface,query);self.assertLess(len(query),1800)
            self.assertEqual(receipt['candidate_hash'],parent.code_hash)
            with self.assertRaisesRegex(ValueError,'exceeds_budget'):project(replace(task,prompt='x'*2000+' do not change widths'),evidence,parent)

if __name__=='__main__':unittest.main()
