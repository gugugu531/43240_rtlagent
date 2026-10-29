"""Counter limits and publication state must not be inferred from topic alone."""
import unittest
from agent.knowledge.research import load_bundle
from agent.knowledge.pregen import decide,retrieve_spec
from agent.knowledge.spec_methods import METHODS

class SpecMethods(unittest.TestCase):
    def setUp(self):self.cards={c['card_id']:c for c in load_bundle()['cards']}

    def test_only_audited_first_generation_methods_leave_shadow(self):
        promoted={'v8-packer-temporal-order','v9-public-block-carry-chain','v9-public-batch-final-sample',
                  'v9-lang-boolean-versus-bitwise','v9-lang-unsigned-negative-check',
                  'v9-lang-comparison-result-sign','v9-public-sampled-edge-history'}
        for cid in METHODS:
            with self.subTest(card=cid):
                self.assertEqual(self.cards[cid]['activation_state'],'restricted' if cid in promoted else 'shadow')
        for cid in promoted:
            self.assertEqual(self.cards[cid]['injection_stages'],['pre_generation'])

    def test_width_and_counter_domain_are_actual_contract_bounds(self):
        c=self.cards['v9-public-bounded-modulus']
        prompt='A counter over 0 through 9 wraps on enable at the rising clock. Reset zero.'
        interface='module TopModule(input clk,output reg[3:0]count);endmodule'
        self.assertTrue(decide(c,prompt,interface)['admit'])
        self.assertEqual(decide(c,prompt.replace('9','15'),interface)['decision_class'],'not_needed')
        self.assertEqual(decide(c,prompt.replace('9','19'),interface)['decision_class'],'unknown')
        self.assertEqual(decide(c,prompt,'')['decision_class'],'unknown')

    def test_mask_topic_or_scalar_does_not_authorize_vector_method(self):
        c=self.cards['v9-lang-boolean-versus-bitwise']
        self.assertEqual(decide(c,'Implement a mask.','module TopModule(output[3:0]y);endmodule')['decision_class'],'unknown')
        self.assertEqual(decide(c,'Implement a combinational binary mask for each output bit.','module TopModule(output y);endmodule')['decision_class'],'unknown')

    def test_real_retrieval_refuses_a_new_shadow_method(self):
        cards,trace=retrieve_spec('An unsigned counter over 0 through 9 wraps on enable at the rising clock. Reset clears it to zero.','module TopModule(input clk,reset,enable,output reg[3:0]count);endmodule',{'strategy':'bm25'})
        self.assertFalse(cards)
        self.assertTrue(any(d.get('card_id')=='v9-public-bounded-modulus' and d['reason']=='catalog_shadow_or_hold' for d in trace['rejected']))

    def test_known_edge_method_does_not_trigger_unneeded_nba_card(self):
        prompt='At each rising clock edge sample binary signal_in. Emit a registered one-cycle rising event on each sampled low-to-high transition. Synchronous reset clears the history to zero. Store the previous sample and compare it with the current sample.'
        interface='module TopModule(input clk,reset,signal_in,output reg[0:0]rise);endmodule'
        self.assertEqual(decide(self.cards['v9-lang-nba-rhs-sampling'],prompt,interface)['decision_class'],'unknown')
        cards,trace=retrieve_spec(prompt,interface,{'strategy':'bm25'})
        self.assertFalse(cards)

    def test_block_carry_conflicts_are_not_injection_evidence(self):
        card=self.cards['v9-public-block-carry-chain']
        base=('Implement an exact combinational unsigned binary sum using two arithmetic '
              'blocks, a lower block and an upper block, with a final carry output. ')
        interface='module TopModule(input[5:0]a,b,output[6:0]sum);endmodule'
        self.assertEqual(decide(card,base+'The upper block carry-in is zero.',interface)['decision_class'],'not_needed')
        self.assertEqual(decide(card,base+'Use independent blocks without inter-block carry.',interface)['decision_class'],'not_needed')

    def test_batch_completion_conflicts_are_not_injection_evidence(self):
        card=self.cards['v9-public-batch-final-sample']
        base=('At each rising clock, form non-overlapping batches of three accepted unsigned '
              'binary samples and publish a sum on the final sample acceptance. Reset clears state. ')
        interface='module TopModule(input clk,reset,accept,input[2:0]sample,output[4:0]sum);endmodule'
        self.assertEqual(decide(card,base+'Exclude the final sample from the published sum.',interface)['decision_class'],'not_needed')
        self.assertEqual(decide(card,base+'Publish the previous accumulator on completion.',interface)['decision_class'],'not_needed')

if __name__=='__main__':unittest.main()
