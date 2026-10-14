"""Adversarial oracle fixtures, separate from official tasks or answers."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from agent.services.behavior import parse_plan, analyze_trace
from agent.workflows.spec_selection import choose_spec_candidate
from agent.core.candidate import CandidateFactory
from agent.core.state import CheckResult, RunStateView
from test_plan_format import fixture


def observe(plan, values):
    text = '\n'.join(f'AGENT_SAMPLE|{i}|q={v}' for i,v in enumerate(values))
    return analyze_trace(text + f'\nAGENT_DONE|{len(values)}', plan)


class OracleTests(unittest.TestCase):
    def test_wrong_last_expectation_cannot_corrupt_sync_hold(self):
        task, raw = fixture()
        raw['cycles'][-1]['expected']['q'] = 3  # Wrong model state, same as reset.
        plan = parse_plan(json.dumps(raw), task)
        self.assertEqual(len(plan.steps), 8)  # Probe MUST still be scheduled.
        good = observe(plan, ['x','3','3','5','5','2','2','3'])
        bad = observe(plan, ['x','3','3','5','5','2','3','3'])
        self.assertEqual(good['hypothesis_mismatches'], 1)
        self.assertEqual(good['property_mismatches'], 0)
        self.assertEqual(bad['first_property_mismatch']['step'], 6)
        self.assertEqual(bad['first_property_mismatch']['expected'], 2)  # Observed, not predicted 3.
        self.assertTrue(bad['reset_kind_probes'][0]['discriminating'])

    def test_equal_reset_state_is_not_discriminating_coverage(self):
        task, raw = fixture()
        plan = parse_plan(json.dumps(raw), task)
        result = observe(plan, ['x','3','3','3','3','3','3','3'])
        self.assertEqual(result['property_mismatches'], 0)
        self.assertFalse(result['reset_kind_probes'][0]['discriminating'])
        self.assertGreater(result['hypothesis_mismatches'], 0)

    def test_unknown_previous_state_is_inconclusive_not_property_failure(self):
        task, raw = fixture()
        plan = parse_plan(json.dumps(raw), task)
        result = observe(plan, ['x','3','3','5','5','x','x','3'])
        self.assertEqual(result['property_mismatches'], 0)
        self.assertEqual(result['property_inconclusive'], 1)

    def test_both_clock_edges_polarities_reset_kinds_without_model_end_state(self):
        for edge in ('posedge','negedge'):
            for active in (0,1):
                for kind in ('synchronous','asynchronous'):
                    task, raw = fixture(edge, active, kind)
                    raw['cycles'][-1]['expected']['q'] = 3
                    plan = parse_plan(json.dumps(raw), task)
                    good = observe(plan, ['3','3','3','5','5','2',
                                         '2' if kind == 'synchronous' else '3','3'])
                    bad = observe(plan, ['3','3','3','5','5','2',
                                        '3' if kind == 'synchronous' else '2','3'])
                    self.assertEqual(good['property_mismatches'], 0)
                    self.assertEqual(bad['property_mismatches'], 1)

    def test_property_improvement_cannot_trade_away_old_pass_or_coverage(self):
        factory = CandidateFactory()
        candidates = {c.id:c for c in (factory.create('module TopModule(input a,output y); assign y=a; endmodule',
            source_stage='generate',round=i) for i in (1,2))}
        def choose(old, new):
            checks = []
            for n, values in [('c001',old),('c002',new)]:
                checks.append(CheckResult('lint'+n,n,'lint','passed',''))
                checks.append(CheckResult('b'+n,n,'behavior','failed','',details=dict(
                    valid_observation=True,plan_hash='p',oracle_protocol=2,official_verification=False,
                    property_checks=[dict(id=k,status=v,source='explicit_reset_literal') for k,v in values.items()])))
            return choose_spec_candidate(RunStateView(candidates,tuple(checks),(),'c001',None),plan_hash='p').candidate_id
        old = {'a':'failed','b':'passed'}
        self.assertEqual(choose(old, {'a':'passed','b':'passed'}), 'c002')
        self.assertEqual(choose(old, {'a':'passed','b':'failed'}), 'c001')
        self.assertEqual(choose(old, {'a':'passed','b':'inconclusive'}), 'c001')
        self.assertEqual(choose(old, {'a':'passed'}), 'c001')
        self.assertEqual(choose({}, {}), 'c001')


if __name__ == '__main__':
    unittest.main()
