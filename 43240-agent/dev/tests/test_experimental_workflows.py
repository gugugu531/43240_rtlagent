"""Deterministic integration tests; no official TB, answers or paid model."""
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from agent.core.budget import BudgetExhausted
from agent.core.config import ModelConfig
from agent.core.model import ModelCallError, ModelReply
from agent.core.registry import build_workflow
from agent.core.runner import Runner, RunOptions
from agent.core.task import TaskSpec
from agent.nodes.behavior import BehaviorNode
from agent.services.behavior import analyze_trace
from agent.services.repair_feedback import extract_diagnostics
from support import FakeBackend, reply, tool_result, events

TABLE = 'The module should implement a combinational circuit for the following truth table:\na | y\n0 | 1\n1 | 0\n'
TASK = TaskSpec.from_text('synthetic', TABLE, 'module TopModule(input a, output y);')
GOOD = 'module TopModule(input a, output y); assign y=~a; endmodule\n'
BAD = 'module TopModule(input a, output y); assign y=a; endmodule\n'
BROKEN = 'module TopModule(input a, output y); assign y=broken; endmodule\n'
MISSING = 'module TopModule(input a, output logic y); logic missing; endmodule\n'
WARN = 'WARNING: [Synth 8-3848] Net y in module/entity TopModule does not have driver.'
ERROR = "ERROR: [VRFC 10-3818] variable 'y' is driven by invalid combination of procedural drivers [/tmp/solution.sv:1]"


class ExperimentTools:
    def __init__(self, *, values=None, lint_status=None, synth_status='ok', behavior_status=None):
        self.calls = []
        self.values, self.lint_status = values, lint_status
        self.synth_status, self.behavior_status = synth_status, behavior_status

    def fingerprint(self): return 'synthetic-tool-v1'
    def replay_fingerprint(self): return 'synthetic-tool-v1'
    def behavior_fingerprint(self): return 'synthetic-tool-v1'

    def lint(self, code, top, timeout_s):
        self.calls.append(('lint', code))
        status = self.lint_status or ('failed' if 'broken' in code else 'ok')
        return tool_result('lint', status, ERROR if status == 'failed' else 'lint ' + status)

    def synth(self, code, top, timeout_s):
        self.calls.append(('synth', code))
        text = WARN if 'missing' in code else 'Synthesis finished'
        return replace(tool_result('synth', self.synth_status, text),
                       details={'repair_diagnostics': extract_diagnostics(text)})

    def behavior(self, code, top, plan, timeout_s):
        self.calls.append(('behavior', code))
        values = self.values(code, plan) if self.values else (['1', '0'] if '~a' in code else ['0', '1'])
        trace = '\n'.join(f'AGENT_SAMPLE|{i}|y={v}' for i,v in enumerate(values)) + f'\nAGENT_DONE|{len(values)}'
        details = analyze_trace(trace, plan)
        status = self.behavior_status or ('failed' if details['mismatches'] else 'unavailable'
                    if details['property_inconclusive'] or details['hypothesis_inconclusive'] else 'ok')
        return replace(tool_result('behavior', status, 'synthetic behavioral observation'),
                       failure_kind='behavior' if status == 'failed' else 'test' if status == 'unavailable' else 'unknown',
                       details=details)


class ExperimentalTests(unittest.TestCase):
    def run_flow(self, outcomes, *, workflow='spec_test_repair', task=TASK, tools=None,
                 params=None, config=None, deadline_s=120):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        backend = FakeBackend(outcomes)
        tools = tools or ExperimentTools()
        result = Runner(config or ModelConfig(), backend_factory=lambda config: backend,
            toolchain_factory=lambda: tools).run(task,
                lambda: build_workflow(workflow, **(params or {})),
                options=RunOptions(Path(temp.name), deadline_s=deadline_s, reserve_s=0))
        self.assertNotEqual(result.status, 'error', events(temp.name))
        return result, backend, tools, temp.name

    def test_registered_classes_and_first_requests_match_scheme_a(self):
        requests = []
        for name, count in [('tool_feedback', 2), ('spec_test_repair', 3), ('behavior_divergence', 4)]:
            instance = build_workflow(name)
            self.assertEqual(instance.max_calls, count)
            result, backend, _, _ = self.run_flow([reply(GOOD), reply(GOOD)], workflow=name)
            # HTTP content and sampling are identical; transport timeout is
            # independently bounded by each run's actual remaining wall time.
            requests.append(backend.requests[0].payload('fake-model'))
            self.assertEqual(result.selected_candidate.code, GOOD)
        self.assertEqual(requests[0], requests[1]); self.assertEqual(requests[1], requests[2])
        result, backend, _, _ = self.run_flow([reply(GOOD)], workflow='evidence_a0')
        self.assertEqual(requests[0], backend.requests[0].payload('fake-model'))
        self.assertEqual(build_workflow('single_generate').describe().name, 'single_generate')

    def test_public_truth_table_repairs_and_rechecks_before_synthesis(self):
        result, backend, tools, temp = self.run_flow([reply(BAD), reply(GOOD)])
        self.assertEqual(result.stop_reason, 'self_test_and_synth_passed')
        self.assertIn('~a', result.selected_candidate.code)
        self.assertEqual(len(backend.requests), 2)  # table plan used zero requests
        self.assertEqual([k for k,_ in tools.calls], ['lint', 'behavior', 'lint', 'behavior', 'synth'])
        feedback = backend.requests[1].messages[-1]['content']
        self.assertIn('full input prefix', feedback)
        self.assertIn('public_literal_truth_table', feedback)
        self.assertIn('history', feedback)
        self.assertTrue(any(e.get('event') == 'experimental_repair' for e in events(temp)))

    def test_compilation_repair_enters_functional_stage_with_no_repair_slots_left(self):
        result, backend, tools, _ = self.run_flow([reply(BROKEN), reply(GOOD)])
        self.assertEqual(result.stop_reason, 'self_test_and_synth_passed')
        self.assertEqual([k for k,_ in tools.calls], ['lint', 'lint', 'behavior', 'synth'])
        self.assertEqual(len(backend.requests), 2)

    def test_compilation_repair_creates_model_plan_after_repair(self):
        task = TaskSpec.from_text('comb', 'The output y equals the inverse of input a.', TASK.interface)
        raw = dict(timing={'kind':'combinational'}, steps=[dict(inputs={'a':0}, wait_ns=1, expected={'y':1}, basis=[0]),
                                                      dict(inputs={'a':1}, wait_ns=1, expected={'y':0}, basis=[0])])
        result, backend, tools, _ = self.run_flow([reply(BROKEN), reply(GOOD), ModelReply('unused', json.dumps(raw))], task=task)
        self.assertEqual(result.stop_reason, 'self_test_and_synth_passed')
        self.assertEqual([r.purpose for r in backend.requests], ['generate', 'repair', 'spec_test_plan'])
        self.assertEqual(len(backend.requests), 3)

    def test_invalid_plan_stops_without_synthesis_repair_or_retry(self):
        task = TaskSpec.from_text('comb', 'The output y equals the inverse of input a.', TASK.interface)
        for outcome in [ModelReply('unused', '{}'), ModelReply('unused', '{}', finish_reason='length'),
                        ModelCallError('failed', kind='connection', retryable=True)]:
            with self.subTest(outcome=outcome):
                result, backend, tools, _ = self.run_flow([reply(GOOD), outcome], task=task)
                self.assertEqual(len(backend.requests), 2)
                self.assertEqual([k for k,_ in tools.calls], ['lint'])
                self.assertEqual(result.selected_candidate.code, GOOD)
                self.assertNotEqual(result.status, 'completed')

    def test_model_hypothesis_mismatch_does_not_trigger_repair(self):
        task = TaskSpec.from_text('comb', 'The output y equals the inverse of input a.', TASK.interface)
        raw = dict(steps=[dict(inputs={'a':0}, expected={'y':0}, wait_ns=1, basis=[0]),
                          dict(inputs={'a':1}, expected={'y':1}, wait_ns=1, basis=[0])])
        result, backend, tools, _ = self.run_flow([reply(GOOD), ModelReply('unused', json.dumps(raw))], task=task)
        self.assertEqual(result.stop_reason, 'hypothesis_only_mismatch')
        self.assertEqual(len(backend.requests), 2)
        self.assertEqual([k for k,_ in tools.calls], ['lint','behavior'])
        self.assertIn('~a', result.selected_candidate.code)

    def test_unknown_behavior_does_not_trigger_repair_or_synthesis(self):
        result, backend, tools, _ = self.run_flow([reply(GOOD)], tools=ExperimentTools(values=lambda c,p:['x','z']))
        self.assertEqual(result.stop_reason, 'verification_unavailable')
        self.assertEqual(len(backend.requests), 1)
        self.assertEqual([k for k,_ in tools.calls], ['lint','behavior'])

    def test_failed_repair_and_model_error_keep_old_answer(self):
        for outcome in [reply(BROKEN), ModelCallError('transport', kind='connection', retryable=True), reply('not RTL')]:
            with self.subTest(outcome=outcome):
                result, backend, _, temp = self.run_flow([reply(BAD), outcome])
                self.assertEqual(result.selected_candidate.code, BAD)
                self.assertEqual(Path(temp,'solution.v').read_text(), BAD)
                self.assertLessEqual(len(backend.requests), 2)

    def test_deadline_before_repaired_self_test_cannot_displace_old_answer(self):
        original = BehaviorNode.run
        def stop_on_repair(node, ctx, input):
            if input.candidate.parent_id:
                raise BudgetExhausted('test deadline')
            return original(node, ctx, input)
        with patch.object(BehaviorNode, 'run', stop_on_repair):
            result, backend, tools, temp = self.run_flow([reply(BAD), reply(GOOD)])
        self.assertEqual(result.stop_reason, 'deadline')
        self.assertEqual(result.selected_candidate.code, BAD)
        self.assertEqual(Path(temp,'solution.v').read_text(), BAD)
        self.assertEqual([k for k,_ in tools.calls], ['lint','behavior','lint'])

    def test_deadline_during_repaired_synthesis_keeps_old_answer(self):
        tools = ExperimentTools()
        def synth(code, top, timeout_s): raise BudgetExhausted('deadline')
        tools.synth = synth  # service records environment error, not a successful synth
        result, _, _, _ = self.run_flow([reply(BAD), reply(GOOD)], tools=tools)
        self.assertEqual(result.selected_candidate.code, BAD)
        self.assertNotEqual(result.status, 'completed')

    def test_dual_candidates_compare_same_plan_but_never_vote(self):
        result, backend, tools, temp = self.run_flow([reply(BAD), reply(GOOD)], workflow='behavior_divergence')
        self.assertEqual(result.stop_reason, 'self_test_and_synth_passed')
        self.assertIn('~a', result.selected_candidate.code)
        self.assertEqual(len(backend.requests), 2)
        self.assertEqual(backend.requests[1].temperature, .4)
        self.assertNotIn(BAD.strip(), backend.requests[1].messages[-1]['content'])
        rows = [e for e in events(temp) if e.get('event') == 'behavior_divergence']
        self.assertEqual(len(rows), 1)
        self.assertIs(rows[0]['repair_trigger'], False)

    def test_dual_unknown_samples_are_not_compared(self):
        _, _, _, temp = self.run_flow([reply(GOOD), reply(GOOD)], workflow='behavior_divergence',
                                     tools=ExperimentTools(values=lambda c,p:['x','z']))
        self.assertFalse(any(e.get('event') == 'behavior_divergence' for e in events(temp)))

    def test_tool_warning_repair_requires_real_synthesis_improvement(self):
        for new, expected in [(GOOD, GOOD), (MISSING, MISSING),
                              (GOOD.replace('input a', 'input signed a'), MISSING)]:
            with self.subTest(new=new):
                result, backend, tools, _ = self.run_flow([reply(MISSING), reply(new)], workflow='tool_feedback')
                self.assertEqual(result.selected_candidate.code, expected)
                self.assertEqual(len(backend.requests), 2)

    def test_spec_group_does_not_bypass_property_protection_for_warning(self):
        result, backend, _, _ = self.run_flow([reply(MISSING)],
            tools=ExperimentTools(values=lambda c,p:['1','0']))
        self.assertEqual(result.stop_reason, 'synth_output_warning')
        self.assertEqual(result.selected_candidate.code, MISSING)
        self.assertEqual(len(backend.requests), 1)

    def test_initial_checkpoint_is_saved_before_plan_and_is_replayable(self):
        first, _, _, origin = self.run_flow([reply(BAD), reply(GOOD)])
        path = Path(origin, 'initial.json')
        initial = json.loads(path.read_text())
        self.assertEqual(initial['tokens']['calls'], 1)
        self.assertEqual([c['kind'] for c in initial['checks']], ['interface','lint'])
        for workflow in ['tool_feedback','spec_test_repair','behavior_divergence']:
            with self.subTest(workflow=workflow):
                result, backend, _, temp = self.run_flow([reply(GOOD)], workflow=workflow, params={'initial_state':str(path)})
                # Tool-only cannot see BAD's functional error and legitimately stops.
                self.assertEqual(len(backend.requests), 0 if workflow == 'tool_feedback' else 1)
                imported = [e for e in events(temp) if e.get('event') == 'initial_replayed']
                self.assertEqual(len(imported), 1)
                self.assertEqual(imported[0]['initial_calls'], 1)

    def test_existing_a0_synthesis_success_does_not_skip_new_self_test(self):
        _, _, _, origin = self.run_flow([reply(BAD)], workflow='evidence_a0')
        result, backend, tools, _ = self.run_flow([reply(GOOD)], params={'initial_state': str(Path(origin,'initial.json'))})
        self.assertEqual(result.stop_reason, 'self_test_and_synth_passed')
        self.assertIn('~a', result.selected_candidate.code)
        self.assertEqual([k for k,_ in tools.calls], ['behavior','lint','behavior','synth'])

    def test_token_budget_and_service_failure_have_distinct_stop_reasons(self):
        result, backend, _, _ = self.run_flow([], config=ModelConfig(token_total_limit=10))
        self.assertEqual(result.stop_reason, 'model_token_budget')
        self.assertEqual(len(backend.requests), 0)
        result, backend, _, _ = self.run_flow([ModelCallError('transport', kind='connection', retryable=True)])
        self.assertEqual(result.stop_reason, 'model_connection')
        self.assertEqual(len(backend.requests), 1)

    def test_model_limits_are_not_reported_as_deadlines(self):
        from agent.workflows.spec_repair import ExperimentalRepair, ModelCallLimit
        with patch.object(ExperimentalRepair, '_require_call', side_effect=ModelCallLimit()):
            result, backend, _, _ = self.run_flow([])
        self.assertEqual(result.stop_reason, 'model_call_limit')
        self.assertEqual(len(backend.requests), 0)

    def test_missing_module_can_be_repaired_once(self):
        result, backend, tools, _ = self.run_flow([reply('no code'), reply(GOOD)])
        self.assertIn('~a', result.selected_candidate.code)
        self.assertEqual(len(backend.requests), 2)
        self.assertEqual([k for k,_ in tools.calls], ['lint','behavior','synth'])

    def test_repair_cannot_trade_away_previously_passed_public_property(self):
        tools = ExperimentTools(values=lambda code,plan: ['1','1'] if '~a' in code else ['0','0'])
        result, backend, _, _ = self.run_flow([reply(BAD), reply(GOOD)], tools=tools)
        self.assertEqual(result.selected_candidate.code, BAD)
        self.assertEqual(result.stop_reason, 'spec_property_failure')
        self.assertEqual(len(backend.requests), 2)

    def test_changed_interface_cannot_displace_compilable_incumbent(self):
        changed = GOOD.replace('output y', 'output [1:0] y')
        result, _, _, _ = self.run_flow([reply(BAD), reply(changed)])
        self.assertEqual(result.selected_candidate.code, BAD)

    def test_full_call_limits_include_model_plan_alternative_and_repair(self):
        task = TaskSpec.from_text('comb', 'The output y equals the inverse of input a.', TASK.interface)
        raw = dict(steps=[dict(inputs={'a':0},expected={'y':1},wait_ns=1,basis=[0]),
                          dict(inputs={'a':1},expected={'y':0},wait_ns=1,basis=[0])])
        # Known compile defect first: plan runs only after a compilable repair.
        for workflow, outcomes, count in [
                ('tool_feedback', [reply(BROKEN), reply(GOOD)], 2),
                ('spec_test_repair', [reply(BROKEN), reply(GOOD), ModelReply('unused',json.dumps(raw))], 3),
                ('behavior_divergence', [reply(BROKEN), reply(BROKEN), reply(GOOD),
                                         ModelReply('unused',json.dumps(raw))], 4)]:
            with self.subTest(workflow=workflow):
                result, backend, _, _ = self.run_flow(outcomes, workflow=workflow, task=task)
                self.assertEqual(len(backend.requests), count)
                self.assertEqual(result.status, 'completed')

    def test_divergence_alone_neither_repairs_nor_replaces_old_candidate(self):
        task = TaskSpec.from_text('comb', 'The output y equals the inverse of input a.', TASK.interface)
        raw = dict(steps=[dict(inputs={'a':0},expected={'y':1},wait_ns=1,basis=[0]),
                          dict(inputs={'a':1},expected={'y':0},wait_ns=1,basis=[0])])
        result, backend, _, temp = self.run_flow([reply(BAD), ModelReply('unused',json.dumps(raw)), reply(GOOD)],
                                               workflow='behavior_divergence', task=task)
        self.assertEqual(len(backend.requests), 3)
        self.assertEqual(result.selected_candidate.code, BAD)
        self.assertEqual(result.stop_reason, 'hypothesis_only_mismatch')
        self.assertTrue(any(e.get('event') == 'behavior_divergence' for e in events(temp)))
        self.assertFalse(any(e.get('event') == 'experimental_repair' for e in events(temp)))

    def test_passing_initial_candidate_stops_without_unneeded_repair(self):
        for workflow in ['tool_feedback', 'spec_test_repair']:
            result, backend, _, _ = self.run_flow([reply(GOOD)], workflow=workflow)
            self.assertEqual(result.status, 'completed')
            self.assertEqual(len(backend.requests), 1)

    def test_missing_tool_and_tb_failure_never_become_rtl_repair(self):
        for tools in [ExperimentTools(lint_status='unavailable'),
                      ExperimentTools(behavior_status='unavailable')]:
            result, backend, _, _ = self.run_flow([reply(GOOD)], tools=tools)
            self.assertEqual(result.stop_reason, 'verification_unavailable')
            self.assertEqual(len(backend.requests), 1)

    def test_existing_synth_pass_is_preserved_when_repair_synthesis_fails(self):
        _, _, _, origin = self.run_flow([reply(BAD)], workflow='evidence_a0')
        tools = ExperimentTools(synth_status='timeout')
        result, _, _, _ = self.run_flow([reply(GOOD)], tools=tools,
            params={'initial_state': str(Path(origin,'initial.json'))})
        self.assertEqual(result.selected_candidate.code, BAD)

    def test_synthesis_code_error_cannot_remove_compilable_property_protection(self):
        tools = ExperimentTools(synth_status='failed')
        result, backend, _, _ = self.run_flow([reply(GOOD)], tools=tools)
        self.assertEqual(result.selected_candidate.code, GOOD)
        self.assertNotEqual(result.status, 'completed')
        self.assertEqual(len(backend.requests), 1)

    def test_partial_unknown_observation_does_not_allow_property_replacement(self):
        tools = ExperimentTools(values=lambda code,plan: ['1','x'] if '~a' in code else ['0','0'])
        result, _, _, _ = self.run_flow([reply(BAD), reply(GOOD)], tools=tools)
        self.assertEqual(result.selected_candidate.code, BAD)

    def test_development_configs_resolve_without_network_or_secret(self):
        from agent.core.configuration import load_config, resolve_config
        from dev.tools.experiment import parse_experiment, select_tasks
        root = Path(__file__).resolve().parents[2]
        for stem, workflow in [('tool','tool_feedback'), ('spec','spec_test_repair'),
                               ('divergence','behavior_divergence')]:
            config = resolve_config(load_config(root / f'dev/configs/workflow-{stem}-quick.yaml'), env={})
            self.assertEqual(config.agent.workflow.type, workflow)
            self.assertEqual(config.agent.services.model.backend, 'mock')
            self.assertEqual(config.agent.services.model.timeout_s, 300)
            experiment = parse_experiment(config)
            self.assertTrue(select_tasks(experiment.selection))

    def test_all_new_entries_run_without_dev_in_isolated_submission(self):
        from dev.tools.submission import stage_submission
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as temp:
            staged = Path(temp,'submission')
            stage_submission(root, staged)
            self.assertFalse((staged/'dev').exists())
            env = {k:v for k,v in os.environ.items() if not k.startswith(('LLM_', 'AGENT_')) and k != 'PYTHONPATH'}
            env.update(LLM_BACKEND='mock', VIVADO_BIN='/nonexistent/experimental-test')
            for workflow in ['tool_feedback','spec_test_repair','behavior_divergence']:
                output = Path(temp,workflow)
                completed = subprocess.run(['bash',str(staged/'run.sh'),
                    str(root.parent/'tasks/example/example_ex03_lfsr8'),str(output)],
                    cwd=staged, env=dict(env,AGENT_WORKFLOW=workflow), capture_output=True, timeout=20)
                self.assertEqual(completed.returncode, 0, completed.stderr.decode())
                self.assertGreater((output/'solution.v').stat().st_size, 0)
                self.assertFalse(any(e.get('event') == 'error' and e.get('tool') == 'agent' for e in events(output)))


if __name__ == '__main__':
    unittest.main()
