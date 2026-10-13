"""Offline retrieval contract tests, not claims of HDL or task correctness."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from dev.tools.knowledge_lookup import load_corpus, retrieve, build_context, normalize_code, verify_local_sources


class KnowledgeLookupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus=load_corpus()

    def test_fifteen_cards_and_complete_provenance(self):
        self.assertEqual(len(self.corpus['cards']),15)
        for card in self.corpus['cards']:
            self.assertTrue(card['source_ids'])
            self.assertEqual(card['tool_validation'],'not_run')

    def lookup(self,code,tool='xvlog',version='2026.1',**kwargs):
        return retrieve(self.corpus,code=code,tool=tool,version=version,**kwargs)

    def test_exact_error_code(self):
        result=self.lookup('vrfc  10-1280')
        self.assertEqual([h['card_id'] for h in result['hits']],['procedural-variable'])
        self.assertEqual(result['hits'][0]['matched_by'],{'exact_codes':['VRFC 10-1280']})

    def test_no_wrong_tool_or_version(self):
        for tool,version in [('vivado-lint','2026.1'),('xvlog','2025.2')]:
            self.assertEqual(self.lookup('VRFC 10-1280',tool,version)['hits'],[])

    def test_error_lookup_requires_tool_and_version(self):
        for params in ({'tool':'xvlog'},{'version':'2026.1'},{}):
            result=retrieve(self.corpus,code='VRFC 10-1280',**params)
            self.assertEqual(result['reason'],'tool_and_version_required')

    def test_unknown_error_never_falls_back_to_keywords(self):
        result=retrieve(self.corpus,query='[VRFC 10-9999] 过程赋值 output reg',tool='xvlog',version='2026.1')
        self.assertEqual(result['hits'],[])
        self.assertEqual(result['strategy'],'exact_code')

    def test_numeric_suffix_cannot_cross_namespace(self):
        self.assertEqual(self.lookup('Synth 8-1280')['hits'],[])

    def test_lint_rule_requires_lint_scope(self):
        self.assertEqual(self.lookup('ASSIGN-2')['hits'],[])
        result=self.lookup('ASSIGN-2','vivado-lint')
        self.assertEqual(result['hits'][0]['card_id'],'signedness')

    def test_chinese_design_query(self):
        result=retrieve(self.corpus,query='循环移位旋转需要检查什么？')
        self.assertEqual(result['hits'][0]['card_id'],'rotate-versus-shift')

    def test_case_insensitive_english_and_word_boundaries(self):
        self.assertEqual(retrieve(self.corpus,query='FSM Moore output timing')['hits'][0]['card_id'],'fsm-output-timing')
        self.assertEqual(retrieve(self.corpus,query='resetting')['hits'],[])

    def test_unknown_and_empty_queries_return_empty(self):
        for query in ('','如何制作奶茶'):
            self.assertEqual(retrieve(self.corpus,query=query)['hits'],[])

    def test_two_card_cap_and_stable_order(self):
        result=retrieve(self.corpus,query='reset counter FSM rotate')
        self.assertEqual(len(result['hits']),2)
        self.assertEqual(result,retrieve(self.corpus,query='reset counter FSM rotate'))
        with self.assertRaises(ValueError):
            retrieve(self.corpus,query='reset',limit=3)

    def test_budget_does_not_cut_cards(self):
        result=retrieve(self.corpus,query='reset counter')
        full=build_context(result)
        self.assertTrue(full['included'])
        empty=build_context(result,max_chars=1)
        self.assertEqual(empty['text'],'')
        self.assertEqual(len(empty['omitted_for_budget']),len(result['hits']))

    def test_negative_budget_rejected(self):
        with self.assertRaises(ValueError):
            build_context({'hits':[]},-1)

    def test_provenance_and_no_caller_mutation(self):
        before=copy.deepcopy(self.corpus)
        result=self.lookup('VRFC 10-1280')
        self.assertEqual(self.corpus,before)
        self.assertEqual(len(result['corpus_sha256']),64)
        self.assertTrue(result['hits'][0]['sources'])

    def invalid_corpus(self,mutate):
        value=copy.deepcopy(self.corpus)
        mutate(value)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'cards.json'
            path.write_text(json.dumps(value),encoding='utf-8')
            with self.assertRaises(ValueError):load_corpus(path)

    def test_duplicate_ids_rejected(self):
        self.invalid_corpus(lambda c:c['cards'].append(c['cards'][0]))

    def test_unknown_source_rejected(self):
        self.invalid_corpus(lambda c:c['cards'][0]['source_ids'].append('unknown'))

    def test_benchmark_specific_material_rejected(self):
        self.invalid_corpus(lambda c:c['cards'][0]['guidance'].append('Prob999_example'))

    def test_cannot_claim_tool_validation(self):
        self.invalid_corpus(lambda c:c['cards'][0].update(tool_validation='passed'))

    def test_local_source_mismatch_rejected(self):
        value={'sources':{'bad':{'origin':'ross','path':'source.md','sha256':'0'*64}}}
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp)/'source.md').write_text('changed')
            with self.assertRaises(ValueError):verify_local_sources(value,tmp)

    def test_source_cannot_escape_root(self):
        value={'sources':{'bad':{'origin':'ross','path':'../escape.md','sha256':'0'*64}}}
        with self.assertRaises(ValueError):verify_local_sources(value,tempfile.gettempdir())

    def test_normalization_rejects_partial_codes(self):
        with self.assertRaises(ValueError):normalize_code('10-1280')
