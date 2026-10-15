"""Opt-in real Vivado integration using synthetic circuits and fixed replies."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from agent.core.config import ModelConfig, ToolConfig
from agent.core.model import ModelReply
from agent.core.registry import build_workflow
from agent.core.runner import Runner, RunOptions
from support import FakeBackend, reply, events
from test_experimental_workflows import TASK, BAD, GOOD
from test_plan_format import fixture


@unittest.skipUnless(os.environ.get('RUN_VIVADO_TESTS') == '1', 'set RUN_VIVADO_TESTS=1 for real Vivado')
class RealExperimentalTests(unittest.TestCase):
    def invoke(self, task, outcomes, workflow='spec_test_repair'):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        backend = FakeBackend(outcomes)
        result = Runner(ModelConfig(), backend_factory=lambda _:backend,
            tool_config=ToolConfig(bin_dir=os.environ['VIVADO_BIN'], temp_dir=temp.name)).run(
                task, lambda:build_workflow(workflow),
                options=RunOptions(Path(temp.name,'output'), deadline_s=300, reserve_s=0))
        self.assertNotEqual(result.status, 'error')
        return result, backend, events(Path(temp.name,'output'))

    def test_public_literal_repair_is_functionally_rechecked_before_selection(self):
        result, backend, trace = self.invoke(TASK, [reply(BAD), reply(GOOD)])
        self.assertEqual(result.stop_reason, 'self_test_and_synth_passed')
        self.assertEqual(result.selected_candidate.code, GOOD)
        self.assertEqual(len(backend.requests), 2)
        selected = next(i for i,e in enumerate(trace) if e.get('event') == 'selection_decision'
                        and e.get('candidate_id') == 'c002' and e.get('changed'))
        verified = [i for i,e in enumerate(trace) if e.get('candidate_id') == 'c002'
                    and e.get('tool') in ('behavior','synth') and e.get('status') == 'passed']
        self.assertEqual(len(verified), 2)
        self.assertGreater(selected, max(verified))

    def test_reset_kind_violation_is_repaired_using_observed_not_predicted_state(self):
        task, raw = fixture(kind='synchronous')
        def code(asynchronous):
            event = 'posedge tick' + (' or posedge clear' if asynchronous else '')
            return ('module TopModule(input tick,input clear,input [3:0] data,output reg [3:0] q); '
                    f'always @({event}) if(clear) q<=3; else q<=data; endmodule\n')
        result, backend, trace = self.invoke(task, [reply(code(True)), ModelReply('unused',json.dumps(raw)), reply(code(False))])
        self.assertEqual(result.stop_reason, 'self_test_and_synth_passed')
        self.assertEqual(result.selected_candidate.code, code(False))
        self.assertEqual(len(backend.requests), 3)
        self.assertIn('observed_registered_hold', backend.requests[-1].messages[-1]['content'])
        self.assertIn('input_history', backend.requests[-1].messages[-1]['content'])
        checks = [e for e in trace if e.get('tool') == 'behavior']
        self.assertEqual([e['status'] for e in checks], ['failed','passed'])

    def test_real_compile_repair_cannot_skip_functional_check(self):
        broken = 'module TopModule(input a,output y); assign y=; endmodule\n'
        result, backend, trace = self.invoke(TASK, [reply(broken), reply(GOOD)])
        self.assertEqual(result.stop_reason, 'self_test_and_synth_passed')
        self.assertEqual(len(backend.requests), 2)
        checks = [e for e in trace if e.get('tool') in ('lint','behavior','synth')]
        self.assertEqual([(e['tool'],e['status']) for e in checks],
                         [('lint','failed'),('lint','passed'),('behavior','passed'),('synth','passed')])

    def test_wrong_model_prediction_is_not_used_as_reset_probe_start(self):
        task, raw = fixture(kind='synchronous')
        raw['cycles'][-1]['expected']['q'] = 3  # actual observed previous q is 2
        bad = ('module TopModule(input tick,input clear,input [3:0] data,output reg [3:0] q); '
               'always @(posedge tick or posedge clear) if(clear) q<=3; else q<=data; endmodule\n')
        good = bad.replace('posedge tick or posedge clear', 'posedge tick')
        result, backend, trace = self.invoke(task, [reply(bad), ModelReply('unused',json.dumps(raw)), reply(good)])
        self.assertEqual(result.selected_candidate.code, good)
        self.assertEqual(result.stop_reason, 'hypothesis_only_mismatch')
        self.assertEqual(result.status, 'stopped')
        self.assertEqual(len(backend.requests), 3)
        feedback = backend.requests[-1].messages[-1]['content']
        self.assertIn('observed_registered_hold', feedback)
        self.assertIn('"expected": 2', feedback)
        self.assertIn('"sampled_outputs": {"q": "2"}', feedback)
        self.assertFalse(any(e.get('tool') == 'synth' for e in trace))


if __name__ == '__main__': unittest.main()
