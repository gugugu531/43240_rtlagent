"""Framework extension, isolation and default-policy acceptance tests."""
from __future__ import annotations
from dataclasses import dataclass
import importlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from baseline import MAX_TOKENS
from agent.core.budget import Budget, BudgetExhausted
from agent.core.components import Component, ComponentSpec
from agent.core.config import ModelConfig
from agent.core.registry import Registry, build_node, build_workflow, load_extensions, WORKFLOW_REGISTRY
from agent.core.state import WorkflowResult
from agent.core.task import TaskSpec
from agent.core.runner import Runner, RunOptions
from agent.nodes.generate import GenerateInput
from agent.nodes.extract import ExtractInput
from support import FakeBackend, FakeToolchain, reply, events, tool_result

TASK = TaskSpec.from_text('test', 'Implement a module named TopModule.')
CODE = 'module TopModule; endmodule\n'


class RegistryTests(unittest.TestCase):
    def test_registration_has_no_constructor_side_effects_and_builds_fresh_instances(self):
        registry = Registry('test')
        calls = []
        @registry.register('test_component')
        class Example(Component):
            def __init__(self, value=5):
                self.value = value
                calls.append(value)
            def run(self, ctx, input):
                return self.value
        self.assertEqual(calls, [])
        one, two = registry.build('test_component', value=7), registry.build('test_component')
        self.assertIsNot(one, two)
        self.assertEqual(one.describe().public_dict()['parameters'], {'value': 7})
        self.assertEqual(two.describe().public_dict()['parameters'], {'value': 5})
        self.assertEqual(registry.get('test_component'), Example)
        self.assertEqual(registry.names(), ('test_component',))
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            registry.register('test_component')(Example)
        with self.assertRaisesRegex(KeyError, 'available: test_component'):
            registry.get('missing')
        with self.assertRaises(TypeError):
            registry.register('bad')(object)
        with self.assertRaises(ValueError) as caught:
            registry.build('test_component', bad='should-not-be-printed')
        self.assertNotIn('should-not-be-printed', str(caught.exception))

    def test_direct_construction_provides_equivalent_metadata(self):
        @dataclass(frozen=True)
        class DirectNode(Component):
            strength: float = 0.4
            def run(self, ctx, input):
                return input
        self.assertEqual(DirectNode(0.7).describe().public_dict()['parameters'], {'strength': 0.7})
        spec = build_node('rtl_generate', temperature=0.3).describe()
        self.assertEqual(spec.parameters['temperature'], 0.3)
        with self.assertRaises(TypeError):
            spec.parameters['temperature'] = 0.5

    def test_explicit_extension_registers_node_and_workflow(self):
        name = 'test_extension_' + uuid.uuid4().hex
        with tempfile.TemporaryDirectory() as temp:
            Path(temp, name+'.py').write_text(f'''
from agent.core.components import Component
from agent.core.registry import NODE_REGISTRY, WORKFLOW_REGISTRY, build_node
@NODE_REGISTRY.register("{name}_node")
class AddedNode(Component):
    def __init__(self, value=9): self.value=value
    def run(self, ctx, input): return self.value
@WORKFLOW_REGISTRY.register("{name}_workflow")
class AddedWorkflow(Component):
    def __init__(self): self.node=build_node("{name}_node", value=11)
    def run(self, ctx):
        ctx.emit("custom_value", value=ctx.execute(self.node, None))
        return ctx.finish(reason="custom_completed")
''')
            sys.path.insert(0, temp)
            try:
                load_extensions([name])
                load_extensions([name])
                result = Runner(ModelConfig()).run(TASK, lambda: build_workflow(name+'_workflow'),
                                                  options=RunOptions(Path(temp)/'output'))
                self.assertEqual(result.stop_reason, 'custom_completed')
                trace = events(Path(temp)/'output')
                started = next(e for e in trace if e['tool']=='node' and e['event']=='started')
                action = next(e for e in trace if e['tool']=='node' and e['event']=='succeeded')
                self.assertEqual(started['component']['parameters']['value'], 11)
                self.assertEqual(action['output'], 11)
            finally:
                sys.path.remove(temp)
                sys.modules.pop(name, None)


class WorkflowTests(unittest.TestCase):
    def run_fake(self, temp, factory=None, outcomes=None, tools=None):
        backend = FakeBackend(outcomes or [reply(CODE)])
        def forbidden_tools():
            raise AssertionError('default workflow must not construct toolchain')
        result = Runner(ModelConfig(), backend_factory=lambda cfg: backend,
                        toolchain_factory=(lambda: tools) if tools else forbidden_tools).run(
            TASK, factory or (lambda: build_workflow('single_generate')),
            options=RunOptions(Path(temp)))
        return result, backend

    def test_default_is_one_direct_generation_without_skills_or_checks(self):
        with tempfile.TemporaryDirectory() as temp, patch('agent.prompts.builder.load_skills', side_effect=AssertionError):
            result, backend = self.run_fake(temp)
            self.assertEqual(result.status, 'completed')
            self.assertEqual(len(backend.requests), 1)
            request = backend.requests[0]
            self.assertEqual(request.temperature, 0.0)
            self.assertEqual(request.max_tokens, MAX_TOKENS)
            self.assertLessEqual(request.timeout_s, 180)
            self.assertEqual(request.messages[-1]['content'], TASK.prompt)
            self.assertEqual(len(request.messages), 2)
            self.assertIn('Output only code', request.messages[0]['content'])
            self.assertEqual(Path(temp, 'solution.v').read_text(), CODE)
            self.assertFalse(any(e['tool'] in ('lint', 'synth', 'check_interface') for e in events(temp)))
            started = [e for e in events(temp) if e['tool']=='node' and e['event']=='started']
            self.assertEqual([e['component']['name'] for e in started], ['baseline_generate', 'baseline_extract'])
            actions = [e for e in events(temp) if e['tool']=='node' and e['event']=='succeeded']
            call = next(e for e in events(temp) if e['tool']=='llm' and e['event']=='succeeded')
            self.assertEqual(call['execution_id'], actions[0]['execution_id'])
            created = next(e for e in events(temp) if e['tool']=='candidate' and e['event']=='create')
            self.assertEqual(created['source_call_id'], call['call_id'])
            self.assertEqual(created['execution_id'], actions[1]['execution_id'])

    def test_default_does_not_retry_incomplete_output(self):
        with tempfile.TemporaryDirectory() as temp:
            result, backend = self.run_fake(temp, outcomes=[reply('module TopModule;')])
            self.assertEqual(result.stop_reason, 'completed')
            self.assertEqual(len(backend.requests), 1)
            self.assertEqual(Path(temp, 'solution.v').read_text(), 'module TopModule;\n')
            self.assertEqual(result.selected_candidate.extraction_status, 'incomplete')

    def test_unknown_workflow_leaves_contract_files_and_error_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            result, backend = self.run_fake(temp, factory=lambda: build_workflow('unknown'))
            self.assertEqual(result.status, 'error')
            self.assertEqual(backend.requests, [])
            self.assertEqual(Path(temp, 'solution.v').read_text(), '')
            self.assertTrue(any(e['tool']=='agent' and e['event']=='error' for e in events(temp)))

    def test_each_run_gets_fresh_workflow_state_and_read_only_context(self):
        instances = []
        class Counter(Component):
            def __init__(self):
                self.count = 0
                instances.append(self)
            def run(self, ctx):
                self.count += 1
                with self_test.assertRaises(TypeError):
                    ctx.state.candidates['illegal'] = None
                ctx.emit('count', value=self.count)
                return ctx.finish(reason='counted')
        self_test = self
        with tempfile.TemporaryDirectory() as temp:
            for i in range(2):
                result, backend = self.run_fake(Path(temp)/str(i), factory=lambda: Counter())
                self.assertEqual(result.stop_reason, 'counted')
                self.assertEqual(backend.requests, [])
            self.assertIsNot(instances[0], instances[1])
            self.assertEqual([obj.count for obj in instances], [1, 1])

    def test_nested_actions_have_parent_ids_and_restore_call_scope(self):
        class Nested(Component):
            def run(self, ctx, input):
                return ctx.execute(build_node('rtl_generate'), GenerateInput(ctx.task))
        class Flow(Component):
            def run(self, ctx):
                ctx.execute(Nested(), None)
                ctx.execute(build_node('rtl_generate'), GenerateInput(ctx.task))
                return ctx.finish(reason='nested')
        with tempfile.TemporaryDirectory() as temp:
            self.run_fake(temp, factory=lambda: Flow(), outcomes=[reply(CODE), reply(CODE)])
            calls = [e for e in events(temp) if e['tool']=='llm' and e['event']=='succeeded']
            self.assertEqual([e['execution_id'] for e in calls], ['e002', 'e003'])
            actions = [e for e in events(temp) if e['tool']=='node' and e['event']=='started']
            self.assertEqual([e['parent_execution_id'] for e in actions], [None, 'e001', None])

    def test_unhandled_node_exception_preserves_selected_answer(self):
        class Explode(Component):
            def run(self, ctx, input):
                raise ValueError('intentional test error')
        class Flow(Component):
            def run(self, ctx):
                reply = ctx.execute(build_node('rtl_generate'), GenerateInput(ctx.task))
                extracted = ctx.execute(build_node('rtl_extract'), ExtractInput(reply))
                ctx.select_candidate(extracted.candidate.id, reason='before_failure')
                ctx.execute(Explode(), None)
        with tempfile.TemporaryDirectory() as temp:
            result, _ = self.run_fake(temp, factory=lambda: Flow())
            self.assertEqual(result.status, 'error')
            self.assertEqual(result.selected_candidate.id, 'c001')
            self.assertEqual(Path(temp, 'solution.v').read_text(), CODE)
            failed = [e for e in events(temp) if e['tool']=='node' and e['event']=='failed']
            self.assertEqual(failed[0]['error_type'], 'ValueError')

    def test_registering_candidate_does_not_select_it(self):
        class Flow(Component):
            def run(self, ctx):
                reply = ctx.execute(build_node('rtl_generate'), GenerateInput(ctx.task))
                output = ctx.execute(build_node('rtl_extract'), ExtractInput(reply))
                self_test.assertIn(output.candidate.id, ctx.state.candidates)
                self_test.assertIsNone(ctx.state.selected_candidate_id)
                return ctx.finish(reason='unselected')
        self_test = self
        with tempfile.TemporaryDirectory() as temp:
            result, _ = self.run_fake(temp, factory=lambda: Flow())
            self.assertIsNone(result.selected_candidate)
            self.assertEqual(Path(temp, 'solution.v').read_text(), '')

    def test_inconsistent_workflow_result_is_rejected(self):
        class Flow(Component):
            def run(self, ctx):
                return WorkflowResult('wrong-run', None, 'completed')
        with tempfile.TemporaryDirectory() as temp:
            result, _ = self.run_fake(temp, factory=lambda: Flow())
            self.assertEqual(result.status, 'error')


class BudgetTests(unittest.TestCase):
    def test_single_monotonic_deadline_and_reserve(self):
        now = [100.0]
        budget = Budget(10, 2, clock=lambda: now[0])
        self.assertEqual(budget.timeout_s(20), 8)
        now[0] = 105
        self.assertEqual(budget.remaining_s(), 3)
        self.assertFalse(budget.can_start(4))
        now[0] = 110
        self.assertFalse(budget.can_start())
        with self.assertRaises(BudgetExhausted):
            budget.timeout_s(1)

    def test_exhausted_budget_does_not_call_model(self):
        with tempfile.TemporaryDirectory() as temp:
            backend = FakeBackend([reply(CODE)])
            result = Runner(ModelConfig(), backend_factory=lambda cfg: backend).run(
                TASK, lambda: build_workflow('single_generate'),
                options=RunOptions(Path(temp), deadline_s=1, reserve_s=1))
            self.assertEqual(result.stop_reason, 'deadline')
            self.assertEqual(backend.requests, [])


class EvidenceTests(unittest.TestCase):
    def test_component_secret_is_redacted_in_error_evidence(self):
        from agent.core.registry import NODE_REGISTRY
        name = 'secret_test_' + uuid.uuid4().hex
        @NODE_REGISTRY.register(name)
        class Fail(Component):
            def __init__(self, api_key): self.api_key = api_key
            def run(self, ctx, input): raise ValueError('failed with ' + self.api_key)
        class Flow(Component):
            def run(self, ctx):
                ctx.execute(build_node(name, api_key='custom-secret-123'), None)
        with tempfile.TemporaryDirectory() as temp:
            result = Runner(ModelConfig()).run(TASK, lambda: Flow(), options=RunOptions(Path(temp)))
            self.assertEqual(result.status, 'error')
            failed = next(e for e in events(temp) if e['tool']=='node' and e['event']=='failed')
            self.assertEqual(failed['error_message'], 'failed with [redacted]')
            raw = '\n'.join(p.read_text() for p in Path(temp).rglob('*') if p.is_file())
            self.assertNotIn('custom-secret-123', raw)

    def test_optional_record_failure_keeps_answer(self):
        from agent.recording.recorder import RecordingConfig
        with tempfile.TemporaryDirectory() as temp:
            blocked = Path(temp, 'blocked'); blocked.write_text('file')
            backend = FakeBackend([reply(CODE)])
            with self.assertWarns(RuntimeWarning):
                result = Runner(ModelConfig(), backend_factory=lambda cfg: backend).run(
                    TASK, lambda: build_workflow('single_generate'),
                    options=RunOptions(Path(temp)/'out', recording=RecordingConfig(root=blocked)))
            self.assertEqual(result.status, 'completed')
            self.assertEqual(Path(temp, 'out/solution.v').read_text(), CODE)

    def test_tool_initialization_error_preserves_candidate(self):
        backend = FakeBackend([reply(CODE)])
        def broken(): raise RuntimeError('intentional initialization failure')
        with tempfile.TemporaryDirectory() as temp:
            result = Runner(ModelConfig(), backend_factory=lambda cfg: backend,
                            toolchain_factory=broken).run(
                TASK, lambda: build_workflow('repair_loop', use_skills=False), options=RunOptions(Path(temp)))
            self.assertEqual(result.status, 'stopped')
            self.assertEqual(Path(temp, 'solution.v').read_text(), CODE)
            check = next(e for e in events(temp) if e['tool']=='lint')
            self.assertEqual(check['status'], 'error')
            self.assertEqual(len(backend.requests), 1)


if __name__ == '__main__':
    unittest.main()
