"""Regressions for actual v35 recording and semantic-witness failures."""
import json
from pathlib import Path
import tempfile
import unittest
from agent.runtime.recorder import Recorder
from agent.knowledge.research import load_bundle
from agent.knowledge.pregen import decide,retrieve_spec
from agent.knowledge.catalog import validate_catalog


class CatalogV3(unittest.TestCase):
    def test_record_json_escapes_and_credentials_survive_sanitization(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=Recorder(tmp)
            body={'choices':[{'message':{'reasoning_content':'Change one token: \\"Use the conditional operator.\\" Then deliver.','content':'module X; endmodule'}}], 'access_token':'fake-test-credential'}
            for name in ('response.json','response.txt'):
                r.write_json(name,body) if name.endswith('.json') else r.write_text(name,json.dumps(body))
                actual=json.loads((r.record_dir/name).read_text())
                self.assertEqual(actual['access_token'],'[redacted]')
                self.assertEqual(actual['choices'][0]['message']['content'],'module X; endmodule')
            self.assertEqual(json.loads((r.record_dir/'response.json').read_text()),json.loads((r.record_dir/'response.txt').read_text()))
            r.close()

    def test_generic_system_and_bad_code_are_not_known_fact_witnesses(self):
        data=load_bundle();cards={c['card_id']:c for c in data['cards']}
        checks=[('v9-public-sticky-event-memory','At rising clock accumulate event bits in sticky pending until clear.','Do not promote declarations in a buggy example or previous candidate.'),
            ('v9-lang-nba-rhs-sampling','At rising clock output the previous sampled tag and capture a new tag.','Use nonblocking assignments <= for sequential logic.'),
            ('v9-lang-arithmetic-right-sign','Right-shift a signed negative sample preserving sign.','```verilog\nmodule X(input [4:0] x,output signed [4:0] y);assign y=x>>>1;endmodule\n```')]
        for cid,prompt,text in checks:
            with self.subTest(cid=cid):
                d=decide(cards[cid],prompt,supplied_messages=[{'role':'system' if cid.endswith('sampling') else 'user','content':text}])
                self.assertEqual(d['decision_class'],'eligible',d)

    def test_unrelated_parameter_and_unknown_illegal_states_do_not_mask_local_method(self):
        cards={c['card_id']:c for c in load_bundle()['cards']}
        d=decide(cards['v9-lang-indexed-select-constant-width'],'Return a four-bit upward window at runtime base from 0 through 4.','module X #(parameter DELAY=2)(); endmodule')
        self.assertTrue(d['admit'])
        d=decide(cards['v9-lang-nba-rhs-sampling'],'At rising clock output the previous sampled value. Unspecified illegal states are outside scope.')
        self.assertTrue(d['admit'])

    def test_catalog_preserves_old_policy_and_keeps_unapproved_methods_shadowed(self):
        data=load_bundle();catalog=validate_catalog(data)
        self.assertEqual(len(catalog['entries']),129)
        self.assertEqual(sum(e['state']=='legacy_policy' for e in catalog['entries']),32)
        self.assertEqual(sum(e['state']=='restricted' for e in catalog['entries']),38)
        self.assertEqual({e['card_id'] for e in catalog['entries'] if e['state']=='hold'}, set())
        for cid in ('v9-lang-mixed-sign-arithmetic','v9-lang-empty-star-events'):
            card=next(c for c in data['cards'] if c['card_id']==cid)
            self.assertEqual(card['activation_state'],'shadow')
            self.assertFalse(card['injection_eligible'])
        for cid in ('v9-public-serial-sampling-vs-latch',):
            self.assertEqual(next(e['state'] for e in catalog['entries'] if e['card_id']==cid),'shadow')
        promoted={e['card_id'] for e in catalog['entries'] if e['state']=='restricted'}
        self.assertTrue({
            'v9-lang-context-before-operation','v9-public-block-carry-chain','v9-public-batch-final-sample',
            'v8-lfsr-feedback-seed','v8-packer-valid-count','v8-pipeline-valid-alignment',
            'v8-ram-port-write-mode','v8-result-backpressure-retention','v8-serializer-snapshot',
            'v8-stack-boundary-guards','v9-public-am-pm-phase',
            'v9-public-carry-lookahead-composition','v9-public-division-remainder-invariant',
        } <= promoted)
        cards,trace=retrieve_spec(
            'An unsigned counter over 0 through 9 wraps on enable at the rising clock. Reset clears it to zero.',
            'module TopModule(input clk,reset,enable,output reg[3:0]count);endmodule',{'strategy':'bm25'})
        self.assertFalse(cards)
        self.assertTrue(any(r['reason']=='catalog_shadow_or_hold' for r in trace['rejected']))

    def test_explicitly_negated_exact_fact_is_not_counted_as_known(self):
        card=next(c for c in load_bundle()['cards'] if c['card_id']=='v9-lang-conditional-x-merge')
        decision=decide(card,'Implement a mux selector with X/Z merge.',supplied_messages=[{'role':'user','content':'This claim is false: '+card['narrow_fact']}])
        self.assertEqual(decision['decision_class'],'unknown')

    def test_topic_only_or_conflicting_unknown_selector_contract_is_not_admitted(self):
        card=next(c for c in load_bundle()['cards'] if c['card_id']=='v9-lang-conditional-x-merge')
        self.assertEqual(decide(card,'Implement a mux selector with X/Z behavior.')['decision_class'],'unknown')
        self.assertEqual(decide(card,'Implement a mux selector with X/Z input. For unknown selector return zero.')['decision_class'],'not_needed')

    def test_witness_offsets_still_point_to_raw_message_after_code_fence(self):
        card=next(c for c in load_bundle()['cards'] if c['card_id']=='v9-lang-conditional-x-merge')
        raw='```verilog\nmodule Example; endmodule\n```\nUse the conditional operator to merge alternatives.'
        d=decide(card,'Implement a mux selector with X/Z merging.',supplied_messages=[{'role':'user','content':raw}])
        self.assertEqual(d['decision_class'],'not_needed')
        for w in d['witnesses']:self.assertEqual(raw[w['start']:w['end']],w['text'])

    def test_source_witness_checks_the_actual_operand_and_output(self):
        from agent.knowledge.feedback import source_method_witness
        from agent.rtl.task import TaskSpec
        interface='module TopModule(input[4:0] x,output signed[4:0] y);endmodule'
        task=TaskSpec.from_text('source-fact','Return a signed right shift.',interface)
        bad='module TopModule(input[4:0] x,output signed[4:0] y); assign y=x>>>1; endmodule'
        self.assertIsNone(source_method_witness('v9-lang-arithmetic-right-sign',task,bad))
        good=bad.replace('assign y=x>>>1;','wire signed[4:0] sx=$signed(x); assign y=sx>>>1;')
        w=source_method_witness('v9-lang-arithmetic-right-sign',task,good)
        self.assertEqual(good[w['start']:w['end']],w['text'])
        self.assertIsNone(source_method_witness('v9-lang-arithmetic-right-sign',task,bad+'\nmodule Other; wire signed[4:0] x; endmodule'))

    def test_literal_width_already_uses_method_even_when_numeric_width_is_wrong(self):
        from agent.knowledge.feedback import source_method_witness
        from agent.rtl.task import TaskSpec
        code='module TopModule(input[11:0]data,input[3:0]base,output[2:0]y);assign y=data[base +: 2];endmodule'
        task=TaskSpec.from_text('select','Return a three-bit upward window.',code.split(';')[0]+';endmodule')
        w=source_method_witness('v9-lang-indexed-select-constant-width',task,code)
        self.assertEqual(w['text'],'assign y=data[base +: 2];')
        self.assertIsNone(source_method_witness('v9-lang-indexed-select-constant-width',task,code.replace('+: 2','+: runtime_width')))

if __name__=='__main__':unittest.main()
