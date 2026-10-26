"""Synthetic development examples test policy behavior, not model repair benefit."""
from dataclasses import replace
import unittest
from agent.rtl.candidate import CandidateFactory
from agent.rtl.result import CheckResult, bind_result
from admission import F24, decide, witnesses

CODE = 'module TopModule(input x, input [3:0] a, output [7:0] y);\nassign y = {4{x}, a};\nendmodule'


def fixture(code=CODE, **changes):
    parent = CandidateFactory().create(code, source_stage='synthetic_development', round=1)
    item = dict(code='VRFC 10-4982',tool='xvlog',version='2026.1',severity='error',cascade=False,
                process_status='failed',message="syntax error near ',' [candidate.sv:2]",command_index=0)
    item.update(changes)
    check = bind_result(CheckResult(status='failed', summary=item['message'], failure_kind='code',
                        details={'knowledge_diagnostics':{'complete':True,'items':[item]}}),parent,'lint')
    return parent, {'check':check,'execution_id':'synthetic-fixture'}


class Predicates(unittest.TestCase):
    def check(self, expected, code=CODE, feedback='', **changes):
        parent, evidence = fixture(code, **changes)
        decision = decide(F24,evidence,parent,feedback)
        self.assertEqual(decision['reason'],expected)
        return decision

    def test_positive(self):
        d=self.check('development_eligible_not_proven_useful')
        self.assertTrue(d['admit'])
        self.assertEqual(d['measured_benefit'],'not_established')
        self.assertFalse(d['production_enabled'])

    def test_independent_and_valid_outer_replication(self):
        for expr in ('{4{x}}','{{4{x}}, a}'):
            with self.subTest(expr=expr):
                self.check('source_witness_missing_or_ambiguous',CODE.replace('{4{x}, a}',expr))

    def test_comments_strings_and_macros(self):
        for code in ('// '+CODE.replace('\n',' '), 'module T; string s="assign y = {4{x}, a};"; endmodule',
                     CODE.replace('4{x}','`N{x}')):
            self.assertEqual(witnesses(code),[])

    def test_unknown_version_and_wrong_tool(self):
        self.check('unknown_version_or_nonfailure',version='2027.1')
        self.check('primary_diagnostic_outside_predicate',tool='xelab')

    def test_missing_and_wrong_line(self):
        self.check('diagnostic_source_location_missing',message="syntax error near ','")
        self.check('source_witness_missing_or_ambiguous',message="syntax error near ',' [candidate.sv:1]")

    def test_duplicate_examples_and_paraphrase(self):
        for text in ('Use {{4{x}}, a}.', 'Enclose the replication in an outer concatenation.'):
            self.check('knowledge_already_present',feedback=text)
        self.check('novelty_not_established',feedback='Check whether another pair of braces is needed.')

    def test_unrelated_correct_source_is_not_supplied_advice(self):
        code=CODE.replace('endmodule','assign unrelated = {{4{x}}, a};\nendmodule')
        self.check('development_eligible_not_proven_useful',code)

    def test_ambiguous_same_line(self):
        self.check('source_witness_missing_or_ambiguous',CODE.replace('assign y = {4{x}, a};',
                        'assign y = {4{x}, a}; assign z = {4{x}, a};'))

    def test_stale_hash_and_incomplete(self):
        parent,e=fixture()
        self.assertFalse(decide(F24,e,replace(parent,code_hash='0'*64))['admit'])
        e['check'].details['knowledge_diagnostics']['complete']=False
        self.assertEqual(decide(F24,e,parent)['reason'],'incomplete_diagnostics')

    def test_secondary_diagnostic_cannot_authorize(self):
        parent,e=fixture()
        first=dict(e['check'].details['knowledge_diagnostics']['items'][0],code='VRFC 10-1280')
        e['check'].details['knowledge_diagnostics']['items'].insert(0,first)
        self.assertEqual(decide(F24,e,parent)['reason'],'primary_diagnostic_outside_predicate')

    def test_all_32_cards_have_explicit_fail_closed_disposition(self):
        from agent.knowledge.runtime import bundle
        data,_=bundle(); parent,e=fixture()
        for card in data['cards']:
            with self.subTest(card=card['card_id']):
                d=decide(card['card_id'],e,parent)
                self.assertFalse(d['admit']);self.assertNotEqual(d['reason'],'unknown_card')

    def test_missing_execution_checker_binding_and_full_duplicate(self):
        from agent.knowledge.runtime import bundle
        parent,e=fixture();data,_=bundle()
        self.assertEqual(decide(F24,e,parent,supplied_messages=[{'content':data['f24']['projection_text']}])['reason'],
                         'knowledge_already_present')
        e['execution_id']=''
        self.assertFalse(decide(F24,e,parent)['admit'])
        parent,e=fixture();e['check'].details['checker_hash']='0'*64
        self.assertFalse(decide(F24,e,parent)['admit'])


if __name__=='__main__':
    unittest.main()
