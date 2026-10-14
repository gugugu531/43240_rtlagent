"""Synthetic self-test service/selection regressions; no official TB or API."""
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from agent.core.budget import Budget, BudgetExhausted
from agent.core.candidate import CandidateFactory
from agent.core.components import Component
from agent.core.config import ModelConfig, ToolConfig
from agent.core.model import ModelCallError, ModelReply
from agent.core.runner import Runner, RunOptions
from agent.core.state import CheckResult, RunStateView
from agent.core.task import TaskSpec
from agent.core.tokens import TokenPolicy
from agent.nodes.behavior import TestPlanNode, BehaviorNode, BehaviorInput
from agent.recording.recorder import RunRecorder
from agent.services.behavior import parse_plan, literal_truth_table_plan, analyze_trace, run_behavior, render_driver
from agent.services.literal_spec import parse_literal_truth_table
from agent.services.model import ModelService
from agent.services.tools import ToolService
from agent.services.vivado import RtlToolchain, _CommandOutcome
from agent.workflows.spec_selection import choose_spec_candidate
from support import FakeBackend, tool_result, events
from test_plan_format import fixture

TABLE = 'The module should implement a combinational circuit for the following truth table:\na | y\n0 | 1\n1 | 0\n'
TASK = TaskSpec.from_text('synthetic', TABLE, 'module TopModule(input a, output y);')
GOOD = 'module TopModule(input a, output y); assign y=~a; endmodule'
BAD = 'module TopModule(input a, output y); assign y=a; endmodule'


def samples(plan, values):
    return '\n'.join(f'AGENT_SAMPLE|{i}|y={v}' for i, v in enumerate(values)) + f'\nAGENT_DONE|{len(plan.steps)}'


class PlanNodeTests(unittest.TestCase):
    def invoke(self, task, outcomes, *, policy=None):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        recorder = RunRecorder(Path(temp.name)); self.addCleanup(recorder.close)
        backend = FakeBackend(outcomes)
        service = ModelService(backend, recorder, token_policy=policy)
        emitted = []
        ctx = SimpleNamespace(task=task, llm=service, budget=Budget(30, 0),
                              emit=lambda event, **data: emitted.append((event, data)))
        return ctx, backend, emitted

    def test_public_table_skips_model_and_model_expectations_cannot_override_it(self):
        ctx, backend, emitted = self.invoke(TASK, [])
        result = TestPlanNode().run(ctx, TASK)
        self.assertEqual(result.plan.oracle_source, 'public_literal_truth_table')
        self.assertEqual(backend.requests, [])
        self.assertEqual(result.call_id, '')
        raw = dict(steps=[dict(inputs={'a':0}, expected={'y':0}, wait_ns=1, basis=[0])])
        with self.assertRaisesRegex(ValueError, 'contradicts'):
            parse_plan(json.dumps(raw), TASK)

    def test_plan_request_is_public_only_and_explicitly_sampled(self):
        task, raw = fixture()
        ctx, backend, _ = self.invoke(task, [ModelReply('unused', json.dumps(raw), finish_reason='stop')])
        result = TestPlanNode().run(ctx, task)
        self.assertIsNotNone(result.plan)
        request = backend.requests[0]
        self.assertEqual((request.temperature, request.top_p, request.purpose), (0.0, 1.0, 'spec_test_plan'))
        self.assertEqual(len(request.messages), 2)
        self.assertIn(task.prompt, request.messages[1]['content'])
        self.assertIn('SEQUENTIAL plan format', request.messages[0]['content'])
        self.assertNotIn('solution.v', request.messages[1]['content'])

    def test_truncation_invalid_plan_and_model_failure_do_not_retry(self):
        task, _ = fixture()
        for reply in (ModelReply('unused', '{}', finish_reason='length'),
                      ModelReply('unused', '{"unsupported":"ambiguous"}', finish_reason='stop'),
                      ModelCallError('transport failed', kind='connection', retryable=True)):
            with self.subTest(reply=type(reply).__name__):
                ctx, backend, _ = self.invoke(task, [reply])
                result = TestPlanNode().run(ctx, task)
                self.assertIsNone(result.plan)
                self.assertTrue(result.reason)
                self.assertEqual(len(backend.requests), 1)

    def test_existing_token_limits_apply_before_plan_model_call(self):
        task, raw = fixture()
        ctx, backend, _ = self.invoke(task, [], policy=TokenPolicy(total_limit=10))
        result = TestPlanNode().run(ctx, task)
        self.assertEqual(result.reason, 'model_token_budget')
        self.assertEqual(backend.requests, [])
        ctx, backend, _ = self.invoke(task, [ModelReply('unused', json.dumps(raw))],
                                      policy=TokenPolicy(output_limit=2))
        TestPlanNode().run(ctx, task)
        self.assertEqual(backend.requests[0].max_tokens, 2)

    def test_unsupported_interface_cannot_gain_literal_table_trust(self):
        for declaration in ('input signed a', 'input a [0:1]', 'input [0:0][0:0] a', 'input bit a'):
            with self.subTest(declaration=declaration):
                task = TaskSpec.from_text('unsupported', TABLE, f'module TopModule({declaration}, output y);')
                ctx, backend, _ = self.invoke(task, [])
                self.assertIsNone(TestPlanNode().run(ctx, task).plan)
                self.assertIsNone(parse_literal_truth_table(task))
                self.assertEqual(backend.requests, [])

    def test_unknown_sample_is_inconclusive_not_a_property_failure_or_pass(self):
        plan = literal_truth_table_plan(TASK)
        observation = analyze_trace(samples(plan, ['x', '0']), plan)
        self.assertEqual(observation['property_inconclusive'], 1)
        self.assertEqual(observation['property_mismatches'], 0)
        self.assertEqual(observation['property_checks'][0]['status'], 'inconclusive')

    def test_literal_shortcut_rejects_incomplete_duplicate_conflicting_and_caveated_tables(self):
        for text in (TABLE.replace('1 | 0\n',''), TABLE+'0 | 1\n', TABLE+'0 | 0\n',
                     TABLE.replace('1 | 0','1 | x'), TABLE+'Except when enabled.',
                     'Do not implement this example. '+TABLE,
                     TABLE+'a | y\n0 | 1\n1 | 0\n'):
            with self.subTest(text=text):
                task = TaskSpec.from_text('synthetic',text,TASK.interface)
                self.assertIsNone(parse_literal_truth_table(task))

    def test_reordered_table_header_and_multiple_outputs_map_by_name(self):
        prompt = TABLE[:TABLE.index('a | y')] + 'v | a | u\n1 | 0 | 0\n0 | 1 | 1\n'
        task = TaskSpec.from_text('synthetic',prompt,'module TopModule(input a,output u,output v);')
        table = parse_literal_truth_table(task)
        self.assertEqual(table.expected({'a':0}), {'u':0,'v':1})
        self.assertEqual(table.expected({'a':1}), {'u':1,'v':0})

    def test_plan_json_does_not_execute_embedded_code_or_accept_duplicate_keys(self):
        task = TaskSpec.from_text('synthetic','Output y equals a. $system("injected");',TASK.interface)
        raw = dict(steps=[dict(inputs={'a':0},expected={'y':0},wait_ns=1,basis=[0])])
        self.assertNotIn('$system', render_driver(parse_plan(json.dumps(raw), task)))
        for text in ('{"steps":[],"steps":[]}', '{"steps":[],"code":"injected"}', 'not JSON'):
            with self.subTest(text=text),self.assertRaises(ValueError): parse_plan(text,task)

    def test_named_mixed_outputs_cannot_be_certified_as_all_registered(self):
        task, raw = fixture()
        task = TaskSpec.from_text('mixed', task.prompt + '\nflag is combinational.',
            task.interface.replace('output [3:0] q', 'output [3:0] q, output flag'))
        raw['timing']['basis'] = task.prompt
        raw['timing']['reset_values']['flag'] = 0
        with self.assertRaisesRegex(ValueError, 'ALL registered'):
            parse_plan(json.dumps(raw), task)


class ObservingTools:
    def __init__(self): self.version, self.calls = 'sim-1', []
    def behavior_fingerprint(self): return self.version
    def behavior(self, code, top, plan, timeout_s):
        self.calls.append((code, plan.fingerprint, timeout_s))
        details = analyze_trace(samples(plan, ['1', '0']), plan)
        return replace(tool_result('behavior', 'ok', 'synthetic observation'), details=details)


class ToolBoundaryTests(unittest.TestCase):
    def test_unsupported_candidate_port_shape_cannot_be_observed_as_a_pass(self):
        tools = SimpleNamespace(_command=Mock())
        plan = literal_truth_table_plan(TASK)
        for code in (GOOD.replace('input a','input signed a'),
                     GOOD.replace('input a','input a [0:1]')):
            result = run_behavior(tools,code,'TopModule',plan,10)
            self.assertEqual(result.status,'unavailable')
            self.assertFalse(result.details['valid_observation'])
        tools._command.assert_not_called()

    def test_simulator_file_change_invalidates_behavior_fingerprint(self):
        with tempfile.TemporaryDirectory() as temp:
            executable = Path(temp,'xsim'); executable.write_text('first')
            tool = RtlToolchain(config=ToolConfig(temp_dir=temp))
            tool.fingerprint = lambda:'stable-base'
            with patch('agent.services.vivado.shutil.which',return_value=str(executable)):
                before = tool.behavior_fingerprint()
                executable.write_text('different second executable')
                self.assertNotEqual(before,tool.behavior_fingerprint())
            with patch('agent.services.vivado.shutil.which',return_value=None):
                self.assertIsNone(tool.behavior_fingerprint())

    def test_plan_and_simulator_identity_are_in_cache_key_and_reuse_is_explicit(self):
        tools, checks = ObservingTools(), []
        identifiers = iter(f'k{i}' for i in range(20))
        service = ToolService(Budget(30, 0), lambda:next(identifiers), checks.append,
                              task=TASK, toolchain_factory=lambda:tools)
        candidate = CandidateFactory().create(GOOD, source_stage='generate', round=1)
        plan = literal_truth_table_plan(TASK)
        first = service.behavior(candidate, plan)
        reused = service.behavior(candidate, plan)
        self.assertEqual(len(tools.calls), 1)
        self.assertFalse(reused.details['executed'])
        self.assertEqual(reused.details['reused_from_check_id'], first.id)
        self.assertIsInstance(first.details['property_checks'], tuple)
        with self.assertRaises(TypeError): first.details['property_checks'][0]['status'] = 'failed'
        changed = replace(plan, steps=(replace(plan.steps[0], wait_ns=2),) + plan.steps[1:])
        service.behavior(candidate, changed)
        tools.version = 'sim-2'
        service.behavior(candidate, changed)
        self.assertEqual(len(tools.calls), 3)

    def test_unknown_tool_identity_does_not_reuse_and_exhausted_budget_does_not_start(self):
        tools, checks = ObservingTools(), []
        tools.version = None
        ids = iter(f'k{i}' for i in range(20))
        service = ToolService(Budget(30, 0), lambda:next(ids), checks.append,
                              task=TASK, toolchain_factory=lambda:tools)
        candidate = CandidateFactory().create(GOOD, source_stage='generate', round=1)
        plan = literal_truth_table_plan(TASK)
        service.behavior(candidate, plan); service.behavior(candidate, plan)
        self.assertEqual(len(tools.calls), 2)
        service._budget = Budget(1, 1)
        with self.assertRaises(BudgetExhausted): service.behavior(candidate, plan)
        self.assertEqual(len(tools.calls), 2)

    def test_no_following_stage_is_started_when_local_deadline_expires(self):
        with tempfile.TemporaryDirectory() as temp:
            tools = SimpleNamespace(config=ToolConfig(temp_dir=temp), available=True,
                xvlog='xvlog', xelab='xelab', log_dir=None, redactor=None,
                _command=Mock(return_value=_CommandOutcome(('xvlog',),0,'ok',0,'compiled')))
            with patch('agent.services.behavior.shutil.which', return_value='/fake/xsim'), \
                 patch('agent.services.behavior.time.monotonic', side_effect=[0,0,2]):
                result = run_behavior(tools, GOOD, 'TopModule', literal_truth_table_plan(TASK), 1)
            self.assertEqual(result.status, 'timeout')
            self.assertEqual(tools._command.call_count, 1)
            self.assertFalse(result.details['valid_observation'])

    def test_testbench_compile_error_is_not_a_dut_code_error(self):
        with tempfile.TemporaryDirectory() as temp:
            tools = SimpleNamespace(config=ToolConfig(temp_dir=temp), available=True,
                xvlog='xvlog', xelab='xelab', log_dir=None, redactor=None,
                _command=Mock(side_effect=[_CommandOutcome(('xvlog',),0,'ok',0,'compiled'),
                    _CommandOutcome(('xvlog',),1,'failed',0,'ERROR: [VRFC 10-1] syntax error')]))
            with patch('agent.services.behavior.shutil.which', return_value='/fake/xsim'):
                result = run_behavior(tools, GOOD, 'TopModule', literal_truth_table_plan(TASK), 10)
            self.assertEqual(result.failure_kind, 'test')
            self.assertFalse(result.details['valid_observation'])

    def test_behavior_node_records_nested_execution_and_check_through_public_context(self):
        class Probe(Component):
            def run(self, ctx):
                candidate = CandidateFactory().create(GOOD, source_stage='generate', round=1)
                ctx.register_candidate(candidate); ctx.select_candidate(candidate.id, reason='test')
                self.check = ctx.execute(BehaviorNode(), BehaviorInput(candidate, literal_truth_table_plan(ctx.task)))
                return ctx.finish(reason='test')
        with tempfile.TemporaryDirectory() as temp:
            workflow = Probe()
            result = Runner(ModelConfig(), backend_factory=lambda _:FakeBackend([]),
                            toolchain_factory=ObservingTools).run(TASK, workflow, options=RunOptions(Path(temp)))
            self.assertEqual(result.status, 'completed')
            self.assertEqual(workflow.check.kind, 'behavior')
            trace = events(temp)
            self.assertTrue(any(e.get('event') == 'check_started' and e.get('kind') == 'behavior' for e in trace))
            self.assertTrue(any(e['tool'] == 'behavior' for e in trace))
            self.assertTrue(any(e['tool'] == 'node' for e in trace))


class SelectionTests(unittest.TestCase):
    def state(self, old, new, *, old_synth=False, new_synth=False, new_code=GOOD,
              new_hash='p', new_status='failed', old_probe=(), new_probe=()):
        factory = CandidateFactory()
        first = factory.create(BAD, source_stage='generate', round=1)
        second = factory.create(new_code, source_stage='repair', round=2)
        checks = []
        for c, props, synth, hash_, status, probes in ((first,old,old_synth,'p','failed',old_probe),
                                                      (second,new,new_synth,new_hash,new_status,new_probe)):
            checks.append(CheckResult('l'+c.id,c.id,'lint','passed',''))
            if synth: checks.append(CheckResult('s'+c.id,c.id,'synth','passed',''))
            checks.append(CheckResult('b'+c.id,c.id,'behavior',status,'',details=dict(
                valid_observation=True,official_verification=False,oracle_protocol=2,plan_hash=hash_,
                reset_kind_probes=probes,property_checks=[dict(id=k,source='explicit_reset_literal',status=v)
                                                       for k,v in props.items()])))
        return RunStateView({c.id:c for c in (first,second)},tuple(checks),(),first.id,None)

    def test_model_only_mismatches_cannot_displace_compilable_candidate(self):
        state = self.state({}, {})
        self.assertEqual(choose_spec_candidate(state,plan_hash='p').candidate_id,'c001')

    def test_strict_improvement_preserves_port_semantics_tool_passes_and_observation_identity(self):
        old, new = {'a':'failed','b':'passed'}, {'a':'passed','b':'passed'}
        self.assertEqual(choose_spec_candidate(self.state(old,new),plan_hash='p').candidate_id,'c002')
        for overrides in (dict(old_synth=True), dict(new_hash='different'), dict(new_status='unavailable'),
                          dict(new_code=GOOD.replace('input a','input signed a')),
                          dict(new_code=GOOD.replace('input a','input [1:0] a'))):
            with self.subTest(overrides=overrides):
                self.assertEqual(choose_spec_candidate(self.state(old,new,**overrides),plan_hash='p').candidate_id,'c001')

    def test_reset_probe_discrimination_cannot_be_traded_away(self):
        old, new = {'a':'failed'}, {'a':'passed'}
        probe = [dict(step=6, signal='y', discriminating=True)]
        state = self.state(old,new,old_probe=probe,new_probe=[dict(step=6,signal='y',discriminating=False)])
        self.assertEqual(choose_spec_candidate(state,plan_hash='p').candidate_id,'c001')

    def test_later_unknown_check_cannot_be_hidden_by_an_earlier_pass(self):
        state = self.state({'a':'failed'}, {'a':'passed'})
        state = replace(state,checks=state.checks + (CheckResult('timeout','c002','lint','timeout',''),))
        self.assertEqual(choose_spec_candidate(state,plan_hash='p').candidate_id,'c001')


@unittest.skipUnless(os.environ.get('RUN_VIVADO_TESTS') == '1', 'set RUN_VIVADO_TESTS=1 for real Vivado')
class RealSpecTests(unittest.TestCase):
    def tool(self, temp):
        from agent.services.processes import ProcessExecutor
        return RtlToolchain(config=ToolConfig(bin_dir=os.environ['VIVADO_BIN'], temp_dir=temp),
                            executor=ProcessExecutor())

    def test_real_public_truth_table_observations_separate_good_and_bad_logic(self):
        with tempfile.TemporaryDirectory() as temp:
            tool = self.tool(temp); plan = literal_truth_table_plan(TASK)
            good, bad = tool.behavior(GOOD,'TopModule',plan), tool.behavior(BAD,'TopModule',plan)
            self.assertEqual(good.status,'ok',good.summary)
            self.assertEqual(bad.status,'failed',bad.summary)
            self.assertEqual(good.details['property_mismatches'],0)
            self.assertEqual(bad.details['property_mismatches'],2)
            self.assertEqual(good.details['hypothesis_assertions'],0)

    def test_real_sync_async_probes_use_observed_state_not_wrong_model_prediction(self):
        with tempfile.TemporaryDirectory() as temp:
            tool = self.tool(temp)
            for kind in ('synchronous','asynchronous'):
                task, raw = fixture(kind=kind)
                raw['cycles'][-1]['expected']['q'] = 3
                plan = parse_plan(json.dumps(raw), task)
                def code(mode):
                    event = 'posedge tick' + (' or posedge clear' if mode == 'asynchronous' else '')
                    return ('module TopModule(input tick,input clear,input [3:0] data,output reg [3:0] q); '
                            f'always @({event}) if(clear) q<=3; else q<=data; endmodule')
                good = tool.behavior(code(kind),'TopModule',plan)
                bad = tool.behavior(code('asynchronous' if kind=='synchronous' else 'synchronous'),'TopModule',plan)
                self.assertEqual(good.details.get('property_mismatches'),0,good.summary)
                self.assertEqual(good.details['hypothesis_mismatches'],1)
                self.assertGreater(bad.details.get('property_mismatches',0),0,bad.summary)
                self.assertTrue(good.details['reset_kind_probes'][0]['discriminating'])


if __name__ == '__main__': unittest.main()
