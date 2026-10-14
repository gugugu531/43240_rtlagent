"""Natural public timing clauses, with independently constructed negative cases."""
import copy
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from agent.core.task import TaskSpec
from agent.services.behavior import parse_plan


def fixture(description, reset_name='areset', value=0, width=8, kind='asynchronous', data=True):
    interface=f'module TopModule(input clk, input {reset_name}, '+('input [7:0] d, ' if data else '')+f'output [{width-1}:0] q);'
    task=TaskSpec.from_text('synthetic',description,interface)
    raw=dict(timing=dict(kind='sequential',clock='clk',edge='posedge',reset=reset_name,
        reset_active=1,reset_kind=kind,reset_values=dict(q=value),basis=description,reset_basis=description),
        cycles=[dict(inputs=dict(d=19) if data else {},expected=dict(q=19 if data else value),basis=description)])
    return task,raw


class TimingCoverageTests(unittest.TestCase):
    def test_single_dff_output_and_unnamed_unique_reset(self):
        prompt=('The module should include 8 D flip-flops with active high asynchronous reset. '
                'The output should be reset to 0. All DFFs should be triggered by the positive edge of clk.')
        task,raw=fixture(prompt)
        plan=parse_plan(json.dumps(raw),task)
        self.assertEqual(dict(plan.timing.reset_values),{'q':0})
        self.assertEqual(plan.oracle_source,'model_spec_hypothesis')
        self.assertIn('The output should be reset to 0',plan.timing.reset_basis)

    def test_counter_nonzero_lfsr_and_shift_register_literal_binding(self):
        descriptions=[
            ('The module should implement a counter. All sequential logic is triggered on the positive edge of the clock. '
             'The reset input is active high synchronous, and should reset the counter to 1.',1,4,'synchronous'),
            ('The module should implement an LFSR. The active-high synchronous reset should reset the LFSR output to 1. '
             'All sequential logic is triggered on the positive edge of clk.',1,5,'synchronous'),
            ('The module should implement a shift register with active-high asynchronous reset. '
             'Reset sets the shift register to zero. All sequential logic is triggered on the positive edge of clk.',0,4,'asynchronous'),
            ('The module should include 8 D flip-flops with active high synchronous reset setting the output to zero. '
             'All DFFs should be triggered by the positive edge of clk.',0,8,'synchronous')]
        for prompt,value,width,kind in descriptions:
            with self.subTest(prompt=prompt):
                task,raw=fixture(prompt,'reset',value,width,kind,data=False)
                self.assertEqual(dict(parse_plan(json.dumps(raw),task).timing.reset_values),dict(q=value))

    def test_conflicts_missing_values_mixed_and_negated_clauses_are_rejected(self):
        prompt=('The module should include 8 D flip-flops with active high asynchronous reset. '
                'The output should be reset to 0. All DFFs should be triggered by the positive edge of clk.')
        task,raw=fixture(prompt)
        for field,value in [('reset_active',0),('reset_kind','synchronous'),('edge','negedge'),('reset_values',dict(q=1))]:
            bad=copy.deepcopy(raw);bad['timing'][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):parse_plan(json.dumps(bad),task)
        for changed in [prompt.replace('reset to 0','reset to an unspecified value'),
                        prompt.replace('reset to 0','not reset to 0'),
                        prompt+' The output is combinational.',
                        prompt.replace('reset to 0','reset to 0 or 1'),
                        prompt.replace('active high asynchronous reset','asynchronous reset')+' Enable is active high.',
                        prompt.replace('reset to 0','reset to 0, except when enabled')]:
            task,bad=fixture(changed)
            with self.subTest(prompt=changed),self.assertRaises(ValueError):parse_plan(json.dumps(bad),task)
        task,raw=fixture(prompt)
        for interface in [task.interface.replace('output [7:0] q','output [7:0] q, output flag'),
                          task.interface.replace('input areset','input areset, input rst2')]:
            changed=TaskSpec.from_text('ambiguous',prompt,interface)
            with self.assertRaises(ValueError):parse_plan(json.dumps(raw),changed)


if __name__=='__main__':unittest.main()
