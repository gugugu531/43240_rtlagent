"""First-generation permission cannot be reused in feedback or forged assembly."""
from types import SimpleNamespace as NS
import json
import tempfile
import unittest
from unittest.mock import patch
from agent.knowledge.research import load_bundle
from agent.knowledge.pregen import decide,activation_allows
from agent.knowledge.context import prepare
from agent.rtl.task import TaskSpec
from agent.runtime.recorder import Recorder

class StageAdmission(unittest.TestCase):
    def setUp(self):self.card=next(c for c in load_bundle()['cards'] if c['card_id']=='v8-packer-temporal-order')

    def test_stage_requires_explicit_authorization(self):
        self.assertTrue(activation_allows(self.card,'pre_generation'))
        self.assertFalse(activation_allows(self.card,'post_functional_feedback'))
        self.assertFalse(activation_allows(self.card,'post_diagnostic'))
        self.assertFalse(activation_allows(self.card))

    def test_topic_without_reset_and_output_timing_stays_unknown(self):
        prompt='A binary two-item packer accepts items at the rising clock. First item low, second item high. Reset exists.'
        interface='module TopModule(input clk,reset,accept,input[3:0]item,output reg[7:0]out_word,output reg valid);endmodule'
        self.assertEqual(decide(self.card,prompt,interface)['decision_class'],'unknown')

    def test_one_cycle_valid_does_not_establish_publication_edge_or_reset_polarity(self):
        prompt='Build a two-item packer for binary four-bit items. At the rising clock accept an item. First item low, second item high. Publish out_word on the second acceptance and set out_valid for one cycle. Otherwise retain out_word. Synchronous active-high reset clears state and outputs.'
        interface='module TopModule(input clk,reset,accept,input[3:0]item,output reg[7:0]out_word,output reg out_valid);endmodule'
        self.assertEqual(decide(self.card,prompt,interface)['decision_class'],'eligible')
        for changed in (
            prompt.replace('Publish out_word on the second acceptance and set','Set'),
            prompt.replace('on the second acceptance','on the following clock edge'),
            prompt.replace('active-high','active-low'),
            prompt.replace('active-high ',''),
            prompt+' Do not publish on the second acceptance.',
            prompt+' Publish only at the third acceptance.',
            prompt+' Use asynchronous reset.',
        ):
            with self.subTest(prompt=changed):
                self.assertEqual(decide(self.card,changed,interface)['decision_class'],'unknown')

    def test_final_assembly_rechecks_stage_even_if_retriever_is_wrong(self):
        with tempfile.TemporaryDirectory() as tmp:
            record=Recorder(tmp)
            try:
                ctx=NS(store={},record=record,task=TaskSpec.from_text('stage-test','Repair the current code.'),llm=NS(tokenize=lambda m:len(json.dumps(m))//4),config=NS(services=NS(model=NS(max_model_len=65536))))
                base=[{'role':'user','content':'Repair the current code.'}];parent=NS(id='c001',code_hash='bound')
                with patch('agent.knowledge.feedback.retrieve_feedback',return_value=([self.card],{'stage':'post_functional_feedback'})):
                    packed,trace=prepare(ctx,base,parent,None,skill_ids=[],skill_phases=['repair'],rag=False,rag_mode='on',max_tokens=1024,max_extra_tokens=1024,retrieval_options={'research_feedback':True,'strategy':'bm25'})
                self.assertEqual(packed,base);self.assertFalse(trace['sent'])
                self.assertEqual(trace['retrieval']['rejected'][0]['reason'],'card_stage_not_authorized_at_assembly')
            finally:record.close()

if __name__=='__main__':unittest.main()
