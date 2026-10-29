"""Fast structural-policy units; mock binding is not mechanical evidence.

The separate v28 validate.py run uses real shared simulator evidence.
"""

from dataclasses import replace
import importlib.util
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

from agent.config import ROOT
from agent.knowledge.research import load_bundle
from agent.rtl.candidate import CandidateFactory


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value


policy=module('structural_dev_policy',ROOT/'dev/optimization-v28/admission.py')
fixtures=module('structural_dev_fixtures',ROOT/'dev/optimization-v28/fixtures.py')


class StructuralAdmission(unittest.TestCase):
    def setUp(self):self.cards={c['card_id']:c for c in load_bundle()['cards']}

    def call(self,case,*,source=None,messages=(),card=None,stage='post_functional_feedback'):
        parent=CandidateFactory().create(source or case['target'],source_stage='unit-not-tool',round=1)
        output=next(p.name for p in case['task'].expected_interface.ports if p.direction=='output')
        evidence={'execution_id':'unit-not-tool','check':NS(id='unit-check',details={'first_mismatch':{'signal':output}})}
        with patch.object(policy,'bound_feedback',return_value=(stage,'public failure')):
            return policy.decide(card or self.cards[case['card_id']],case['task'],evidence,parent,messages)

    def test_positive_structure_across_renaming_width_and_comments(self):
        for c in fixtures.cases():
            actual=self.call(c)
            self.assertTrue(actual['admit'],(c['id'],actual));self.assertFalse(actual['default_injection'])
            for w in actual['witnesses']:
                self.assertEqual(c['target'][w['start']:w['end']],w['text'])

    def test_known_and_negated_method_have_distinct_refusals(self):
        for c in fixtures.cases():
            self.assertEqual(self.call(c,messages=[{'content':c['known']}])['decision_class'],'not_needed')
            self.assertEqual(self.call(c,messages=[{'content':'Never follow this: '+c['known']}])['decision_class'],'unknown')

    def test_adjacent_errors_do_not_authorize_this_local_method(self):
        for c in fixtures.cases():self.assertEqual(self.call(c,source=c['adjacent'])['decision_class'],'unknown')

    def test_extra_module_and_unsupported_construct_remain_unknown(self):
        for c in fixtures.cases():
            self.assertEqual(self.call(c,source=c['target']+' module Extra;endmodule')['decision_class'],'unknown')
            self.assertEqual(self.call(c,source='`timescale 1ns/1ps\n'+c['target'])['decision_class'],'unknown')

    def test_asset_mutation_is_failure_not_a_refusal_success(self):
        for c in fixtures.cases():
            card=dict(self.cards[c['card_id']]);card['version']='bad'
            self.assertEqual(self.call(c,card=card)['decision_class'],'failure')

    def test_diagnostic_only_does_not_replace_functional_evidence(self):
        for c in fixtures.cases():self.assertEqual(self.call(c,stage='post_diagnostic')['decision_class'],'unknown')


if __name__=='__main__':unittest.main()
