"""Synthetic protocol fixtures; no benchmark-specific expectations in runtime code."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from agent.core.task import TaskSpec
from agent.nodes.behavior import plan_messages
from agent.services.behavior import parse_plan, render_driver
from agent.services.plan_format import evidence_catalog
from agent.services.timing import timing_history, explicit_reset_values


def fixture(edge='posedge', active=1, kind='synchronous'):
    prompt = (f"On the {'positive' if edge == 'posedge' else 'negative'} edge of tick, registered output q takes data.\n\n"
              f"clear is an active-{'high' if active else 'low'} {kind} reset. q is set to 4'h03.\n\n"
              'The reset has higher priority than the data input.')
    task = TaskSpec.from_text('synthetic', prompt,
        'module TopModule(input tick, input clear, input [3:0] data, output [3:0] q);')
    raw = dict(timing=dict(kind='sequential',clock='tick',edge=edge,reset='clear',
        reset_active=active,reset_kind=kind,reset_values=dict(q=3),basis=[0],reset_basis=[1,2]),
        cycles=[dict(inputs=dict(data=5),expected=dict(q=5),basis=[0]),
                dict(inputs=dict(data=2),expected=dict(q=2),basis=[0])])
    return task, raw


class PlanFormatTests(unittest.TestCase):
    def test_nonadjacent_reset_evidence_survives_both_scheduled_checks(self):
        task, raw = fixture()
        prompt = task.prompt.replace('\n\nThe reset',
            '\n\nData input data is four bits wide.\n\nThe reset')
        task = TaskSpec.from_text('separated', prompt, task.interface)
        raw['timing']['reset_basis'] = [1, 3]
        plan = parse_plan(json.dumps(raw), task)
        for step in (plan.steps[1], plan.steps[-1]):
            self.assertEqual(step.basis, plan.timing.reset_basis)
            self.assertEqual(dict(step.expected), {'q': 3})
        # Fragment validation must still reject invented evidence.
        raw['timing']['reset_basis'] = [evidence_catalog(prompt)[1], 'Invented reset priority.']
        with self.assertRaisesRegex(ValueError, 'verbatim'):
            parse_plan(json.dumps(raw), task)

    def test_positive_and_negative_edges_cannot_use_combinational_plans(self):
        for edge in ('positive', 'negative'):
            task = TaskSpec.from_text('edge',
                f'On the {edge} edge of tick, q takes the value of d.',
                'module TopModule(input tick, input d, output q);')
            self.assertIn('SEQUENTIAL plan format', plan_messages(task)[0]['content'])
            raw = dict(timing=dict(kind='combinational'), steps=[
                dict(inputs=dict(tick=0, d=1), expected=dict(q=1), wait_ns=1, basis=[0])])
            with self.subTest(edge=edge), self.assertRaisesRegex(ValueError, 'temporal'):
                parse_plan(json.dumps(raw), task)

    def test_decimal_strings_are_only_representation_not_new_evidence(self):
        task=TaskSpec.from_text('comb','The output y equals input a.',
                               'module TopModule(input [7:0] a, output [7:0] y);')
        for value in (0,1,255):
            raw=dict(steps=[dict(inputs=dict(a=value),expected=dict(y=value),wait_ns=1,basis=[0])])
            integer=parse_plan(json.dumps(raw),task)
            raw['steps'][0].update(inputs=dict(a=str(value)),expected=dict(y=str(value)))
            normalized=parse_plan(json.dumps(raw),task)
            self.assertEqual(integer.fingerprint,normalized.fingerprint)
            self.assertEqual(normalized.oracle_source,'model_spec_hypothesis')
        for token in ('01','+1','-1',' 1','1.0','1+0','x','256',True,1.0):
            raw=dict(steps=[dict(inputs=dict(a=token),expected=dict(y=0),wait_ns=1,basis=[0])])
            with self.subTest(token=token),self.assertRaises(ValueError): parse_plan(json.dumps(raw),task)

    def test_no_clock_no_reset_is_not_temporal_evidence(self):
        prompt='The output y equals input a. This is purely combinational. There is no clock and no reset.'
        task=TaskSpec.from_text('comb',prompt,'module TopModule(input a,output y);')
        raw=dict(timing=dict(kind='combinational'),steps=[dict(inputs=dict(a=0),expected=dict(y=0),wait_ns=1,basis=[0])])
        parse_plan(json.dumps(raw),task)
        clock_task=TaskSpec.from_text('clock',prompt,'module TopModule(input clk,input a,output y);')
        with self.assertRaises(ValueError): parse_plan(json.dumps(raw),clock_task)
        state_task=TaskSpec.from_text('state',prompt+' There is previous state.',task.interface)
        with self.assertRaises(ValueError): parse_plan(json.dumps(raw),state_task)
        bad=dict(timing=dict(kind='combinational'),cycles=[])
        with self.assertRaisesRegex(ValueError,'explicit sequential'):
            parse_plan(json.dumps(bad),task)
        bad['timing']=None
        with self.assertRaisesRegex(ValueError,'explicit sequential'):
            parse_plan(json.dumps(bad),task)

    def test_clock_word_binds_only_to_unique_named_clock_input(self):
        task,raw=fixture()
        prompt=task.prompt.replace('tick','the clock')
        task=TaskSpec.from_text('unique',prompt,task.interface.replace('tick','clk'))
        raw['timing']['clock']='clk'
        parse_plan(json.dumps(raw),task)
        ambiguous=TaskSpec.from_text('ambiguous',prompt,task.interface.replace('input clk,','input clk,input clk2,'))
        with self.assertRaisesRegex(ValueError,'multiple clocks'): parse_plan(json.dumps(raw),ambiguous)
        unnamed=TaskSpec.from_text('unnamed',prompt,task.interface.replace('clk','tick'))
        raw['timing']['clock']='tick'
        with self.assertRaisesRegex(ValueError,'clock edge'): parse_plan(json.dumps(raw),unnamed)

    def test_binary_octal_are_exact_literals_not_expressions(self):
        task=TaskSpec.from_text('comb','The output y equals input a.',
                               'module TopModule(input [7:0] a, output [7:0] y);')
        for token in ('0b11111111','0o377','0xff'):
            raw=dict(steps=[dict(inputs=dict(a=token),expected=dict(y=255),wait_ns=1,basis=[0])])
            self.assertEqual(dict(parse_plan(json.dumps(raw),task).steps[0].inputs)['a'],255)
        for token in ('0b2','0b10+1','-0b1','0bxxxx','0o400'):
            raw=dict(steps=[dict(inputs=dict(a=token),expected=dict(y=255),wait_ns=1,basis=[0])])
            with self.subTest(token=token),self.assertRaises(ValueError): parse_plan(json.dumps(raw),task)

    def test_evidence_catalog_preserves_exact_paragraphs(self):
        prompt='  A line\nwrapped here.\n\n B line.\n'
        self.assertEqual(evidence_catalog(prompt), ('A line\nwrapped here.', 'B line.'))

    def test_combination_ids_and_quoted_hex(self):
        task=TaskSpec.from_text('comb','The output y equals the input a.',
                               'module TopModule(input [7:0] a, output [7:0] y);')
        raw=dict(timing=dict(kind='combinational'),steps=[
            dict(inputs=dict(a='0xff'),expected=dict(y=255),wait_ns=1,basis=[0])])
        plan=parse_plan(json.dumps(raw),task)
        self.assertEqual(dict(plan.steps[0].inputs)['a'],255)
        self.assertEqual(plan.steps[0].basis,task.prompt)
        for basis in ([1],[-1],[True],[0,0],[],['invented'],True):
            bad=copy.deepcopy(raw); bad['steps'][0]['basis']=basis
            with self.subTest(basis=basis),self.assertRaises(ValueError):
                parse_plan(json.dumps(bad),task)

    def test_bare_hex_is_not_silently_repaired(self):
        task,_=fixture()
        with self.assertRaises(ValueError):
            parse_plan('{"steps":[{"inputs":{"data":0xff}}]}',task)

    def test_all_edges_reset_polarities_and_kinds(self):
        for edge in ('posedge','negedge'):
            for active in (0,1):
                for kind in ('synchronous','asynchronous'):
                    with self.subTest(edge=edge,active=active,kind=kind):
                        task,raw=fixture(edge,active,kind)
                        plan=parse_plan(json.dumps(raw),task)
                        history=timing_history(plan)
                        self.assertEqual([h['active_edge'] for h in history], [False,True,False,True,False,True,False,True])
                        self.assertEqual(dict(plan.steps[0].expected),{})
                        self.assertEqual(dict(plan.steps[1].expected),{'q':3})
                        self.assertEqual([h['reset_active'] for h in history],[True,True,False,False,False,False,True,True])
                        for i in (3,5):
                            self.assertEqual(set(dict(plan.steps[i].inputs)),{'tick'})
                        driver=render_driver(plan)
                        self.assertLess(driver.index('tick ='),driver.index('data ='))
                        self.assertEqual(dict(plan.steps[-2].expected),{})
                        self.assertEqual(dict(plan.steps[-1].expected),{'q':3})

    def test_reject_clock_reset_unknown_ports_missing_data_and_mixed_formats(self):
        task,raw=fixture()
        for inputs in (dict(tick=0,data=5),dict(clear=1,data=5),dict(unknown=0),{}):
            bad=copy.deepcopy(raw); bad['cycles'][0]['inputs']=inputs
            with self.subTest(inputs=inputs),self.assertRaises(ValueError):
                parse_plan(json.dumps(bad),task)
        bad=copy.deepcopy(raw); bad['steps']=[]
        with self.assertRaises(ValueError): parse_plan(json.dumps(bad),task)
        bad=copy.deepcopy(raw); bad['timing']=dict(kind='combinational')
        with self.assertRaises(ValueError): parse_plan(json.dumps(bad),task)

    def test_wrong_reset_literals_and_grounding_still_rejected(self):
        task,raw=fixture()
        for field,value in [('reset_values',dict(q=0)),('basis',[1]),('reset_basis',[0]),
                            ('edge','negedge'),('reset_active',0),('reset_kind','asynchronous')]:
            bad=copy.deepcopy(raw); bad['timing'][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):
                parse_plan(json.dumps(bad),task)

    def test_cycle_limit_data_width_and_empty_functional_coverage(self):
        task,raw=fixture()
        bad=copy.deepcopy(raw); bad['cycles']*=8
        with self.assertRaisesRegex(ValueError,'cycle count'): parse_plan(json.dumps(bad),task)
        bad=copy.deepcopy(raw); bad['cycles'][0]['inputs']['data']=16
        with self.assertRaisesRegex(ValueError,'port width'): parse_plan(json.dumps(bad),task)
        bad=copy.deepcopy(raw)
        for row in bad['cycles']: row.update(expected={},basis='')
        with self.assertRaisesRegex(ValueError,'functional active edge'): parse_plan(json.dumps(bad),task)

    def test_explicit_reset_literals_do_not_truncate_or_guess(self):
        for token in ('3',"4'h03","4'd03","4'b0011","4'o03"):
            self.assertEqual(explicit_reset_values('q is set to '+token+'.','q'),[3])
        for text in ("q = 1'h3.",'q is not set to 3.','q = -3.','q is cleared.',
                     "q = 4'bx.",'q = 0x3.'):
            with self.subTest(text=text): self.assertEqual(explicit_reset_values(text,'q'),[])

    def test_unsupported_is_explicit_and_prompt_has_no_default_port_contract(self):
        task,_=fixture()
        with self.assertRaisesRegex(ValueError,'unsupported plan: multiple clocks'):
            parse_plan('{"unsupported":"multiple clocks"}',task)
        messages=plan_messages(task)
        self.assertIn('Evidence catalog',messages[1]['content'])
        self.assertNotIn('EXACT quote naming',messages[0]['content'])
        self.assertNotIn('"rst_n"',messages[0]['content'])
        self.assertNotIn('module TopModule',messages[0]['content'])


if __name__ == '__main__':
    unittest.main()
