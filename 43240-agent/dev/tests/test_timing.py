"""Synthetic timing fixtures only; no official TB or reference data."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from agent.core.task import TaskSpec
from agent.services.behavior import parse_plan, analyze_trace, render_driver


def sequential_fixture(edge='posedge', reset_kind='synchronous', active=1):
    inactive = 0 if edge == 'posedge' else 1
    clock_quote = f"On each {'rising' if edge == 'posedge' else 'falling'} edge of clk, registered output q takes d."
    reset_quote = f"rst is an active-{'high' if active else 'low'} {reset_kind} reset: q = 0."
    task = TaskSpec.from_text('timing', clock_quote + '\n' + reset_quote,
                              'module TopModule(input clk, input rst, input d, output q);')
    def step(inputs, expected):
        return dict(inputs=inputs, wait_ns=1, expected=expected, basis=task.prompt if expected else '')
    raw = dict(timing=dict(kind='sequential', clock='clk', edge=edge, reset='rst', reset_active=active,
        reset_kind=reset_kind, reset_values=dict(q=0), basis=clock_quote, reset_basis=reset_quote), steps=[
        step(dict(clk=inactive,rst=active,d=0), dict(q=0) if reset_kind == 'asynchronous' else {}),
        step(dict(clk=1-inactive), dict(q=0)),
        step(dict(clk=inactive,rst=1-active,d=1), dict(q=0)),
        step(dict(clk=1-inactive), dict(q=1)),
        step(dict(clk=inactive,d=0), dict(q=1)),
        step(dict(clk=1-inactive), dict(q=0))])
    return task, raw


class TimingTests(unittest.TestCase):
    def test_edges_polarities_and_reset_kinds(self):
        for edge in ('posedge','negedge'):
            for kind in ('synchronous','asynchronous'):
                for active in (0,1):
                    with self.subTest(edge=edge,kind=kind,active=active):
                        task, raw = sequential_fixture(edge, kind, active)
                        plan = parse_plan(json.dumps(raw), task)
                        self.assertEqual(plan.timing.edge, edge)
                        driver = render_driver(plan)
                        self.assertLess(driver.index('clk ='), driver.index('d ='))

    def test_reject_active_edge_data_race_and_high_phase_changes(self):
        task, raw = sequential_fixture()
        for index, changes in [(3,dict(d=0)), (3,dict(rst=1))]:
            bad = copy.deepcopy(raw); bad['steps'][index]['inputs'].update(changes)
            with self.assertRaisesRegex(ValueError, 'coincide'):
                parse_plan(json.dumps(bad), task)
        bad = copy.deepcopy(raw)
        bad['steps'].insert(4, dict(inputs=dict(d=0),wait_ns=1,expected=dict(q=1),basis=task.prompt))
        with self.assertRaisesRegex(ValueError, 'inactive'):
            parse_plan(json.dumps(bad),task)

    def test_hold_violation_after_data_change_and_omitted_expectation(self):
        task, raw = sequential_fixture()
        bad = copy.deepcopy(raw); bad['steps'][4]['expected'] = dict(q=0)
        with self.assertRaisesRegex(ValueError, 'without an effective'):
            parse_plan(json.dumps(bad),task)
        bad = copy.deepcopy(raw)
        bad['steps'][4]['expected'] = {}
        bad['steps'].insert(5, dict(inputs={},wait_ns=1,expected=dict(q=0),basis=task.prompt))
        with self.assertRaisesRegex(ValueError, 'without an effective'):
            parse_plan(json.dumps(bad),task)

    def test_reset_initialization_and_unreliable_contracts(self):
        task, raw = sequential_fixture()
        bad = copy.deepcopy(raw); bad['steps'][0]['expected'] = dict(q=0); bad['steps'][0]['basis'] = task.prompt
        with self.assertRaisesRegex(ValueError, 'unknown state'):
            parse_plan(json.dumps(bad),task)
        for field, value in [('edge','negedge'),('reset_active',0),('reset_kind','asynchronous'),
                             ('reset_values',dict(q=1)),('reset_values',{}),('basis','invented')]:
            bad = copy.deepcopy(raw); bad['timing'][field] = value
            with self.subTest(field=field,value=value), self.assertRaises(ValueError):
                parse_plan(json.dumps(bad),task)
        bad = copy.deepcopy(raw); del bad['timing']
        with self.assertRaisesRegex(ValueError,'explicit sequential'):
            parse_plan(json.dumps(bad),task)

    def test_async_reset_without_edge_and_sync_reset_hold(self):
        for kind in ('synchronous','asynchronous'):
            task, raw = sequential_fixture(reset_kind=kind)
            # After q=1, assert reset on the inactive phase, without active edge.
            raw['steps'][4]['inputs'] = dict(clk=0,rst=1,d=0)
            raw['steps'][4]['expected'] = dict(q=0 if kind == 'asynchronous' else 1)
            parse_plan(json.dumps(raw),task)

    def test_reset_must_cover_edge_and_reset_only_is_not_functional(self):
        task, raw = sequential_fixture()
        bad = copy.deepcopy(raw); del bad['steps'][1]
        with self.assertRaisesRegex(ValueError,'hold initial reset'):
            parse_plan(json.dumps(bad),task)
        bad = copy.deepcopy(raw); bad['steps'] = bad['steps'][:2]
        with self.assertRaisesRegex(ValueError,'functional active edge'):
            parse_plan(json.dumps(bad),task)

    def test_multiple_clocks_and_mixed_outputs_fall_back(self):
        task, raw = sequential_fixture()
        task2 = TaskSpec.from_text('multi',task.prompt,
            'module TopModule(input clk, input clk2, input rst, input d, output q);')
        with self.assertRaisesRegex(ValueError,'multiple clocks'):
            parse_plan(json.dumps(raw),task2)
        task2 = TaskSpec.from_text('mixed',task.prompt,
            'module TopModule(input clk, input rst, input d, output q, output y);')
        with self.assertRaisesRegex(ValueError,'ALL registered'):
            parse_plan(json.dumps(raw),task2)

    def test_mismatch_feedback_contains_reset_and_all_effective_edges(self):
        task, raw = sequential_fixture()
        plan = parse_plan(json.dumps(raw),task)
        samples = '\n'.join(f'AGENT_SAMPLE|{i}|q=0' for i in range(6)) + '\nAGENT_DONE|6'
        result = analyze_trace(samples,plan)
        first = result['first_mismatch']
        self.assertEqual(first['step'],3)
        history = first['input_history']
        self.assertEqual(len(history),4)
        self.assertEqual([h['active_edge_count'] for h in history],[0,1,1,2])
        self.assertEqual([h['reset_active'] for h in history],[True,True,False,False])
        self.assertEqual(history[2]['inputs'],dict(clk=0,rst=0,d=1))
        self.assertEqual(history[3]['sampled_outputs'],dict(q='0'))


if __name__ == '__main__':
    unittest.main()
