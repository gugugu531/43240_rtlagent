"""Repair workflow regressions use recorded model calls and fixed check results."""
from __future__ import annotations
import json
from pathlib import Path
import sys
import tempfile
import unittest

AGENT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(AGENT_ROOT))
from agent.core.model import ModelReply, ModelCallError, BackendResponse
from agent.core.config import ModelConfig
from agent.core.registry import build_workflow
from agent.core.task import TaskSpec
from agent.runner import Runner, RunOptions
from agent.tools import ToolResult


def reply(code):
    return ModelReply('unused', f'```verilog\n{code}```\n', model='fake-model', finish_reason='stop')


class FakeBackend:
    def __init__(self, outcomes):
        self.outcomes = iter(outcomes)
        self.requests = []

    def describe(self):
        return dict(backend='test', model='fake-model')

    def complete(self, request):
        self.requests.append(request)
        outcome = next(self.outcomes)
        if isinstance(outcome, BaseException):
            raise outcome
        return BackendResponse(0.01, 200, json.dumps(dict(
            model=outcome.model, choices=[dict(message=dict(content=outcome.content),
                                             finish_reason=outcome.finish_reason)])))


class FakeToolchain:
    def __init__(self, lint_results=(), synth_results=()):
        self.lint_results = iter(lint_results)
        self.synth_results = iter(synth_results)

    def lint(self, source, top, timeout_s):
        return next(self.lint_results)

    def synth(self, source, top, timeout_s):
        return next(self.synth_results)


def tool_result(tool, status, summary):
    rc = {'ok': 0, 'failed': 1, 'timeout': 124, 'unavailable': -1}[status]
    return ToolResult(tool, ((tool,),), rc, status, 0.01, summary)


def events(temp):
    return [json.loads(line) for line in Path(temp, 'trace.jsonl').read_text().splitlines()]


def run_repair(temp, backend, tools, **params):
    return Runner(ModelConfig(), backend_factory=lambda config: backend,
                  toolchain_factory=lambda: tools).run(
        TaskSpec.from_text('test', 'Implement TopModule.'),
        lambda: build_workflow('repair_loop', use_skills=False, **params),
        options=RunOptions(Path(temp), save_candidates=True))


class CandidateFlowTests(unittest.TestCase):
    def test_incomplete_extraction_is_explicitly_traced(self):
        backend = FakeBackend([ModelReply('unused', '```verilog\nmodule TopModule;\n```', finish_reason='length')])
        with tempfile.TemporaryDirectory() as temp:
            result = run_repair(temp, backend, FakeToolchain(), max_rounds=1)
            extracted = [e for e in events(temp) if e['tool']=='extract']
            self.assertIsNone(result.selected_candidate)
            self.assertEqual(extracted[0]['status'], 'incomplete')
            self.assertTrue(extracted[0]['suspected_truncation'])
            self.assertEqual(extracted[0]['call_id'], 'm001')
            self.assertEqual(len(backend.requests), 1)

    def test_second_model_failure_preserves_first_candidate(self):
        code = 'module TopModule; endmodule\n'
        backend = FakeBackend([reply(code), ModelCallError('request timed out', kind='timeout')])
        tools = FakeToolchain([tool_result('lint', 'failed', 'lint failed')])
        with tempfile.TemporaryDirectory() as temp:
            result = run_repair(temp, backend, tools)
            self.assertEqual(result.selected_candidate.id, 'c001')
            self.assertEqual(result.stop_reason, 'model_timeout')
            self.assertEqual(Path(temp, 'solution.v').read_text(), code)
            self.assertEqual(Path(temp, 'candidates/c001.v').read_text(), code)
            self.assertEqual(len(backend.requests), 2)
            self.assertIn('lint failed', backend.requests[1].messages[-1]['content'])
            self.assertIn(code.strip(), backend.requests[1].messages[-1]['content'])

    def test_candidate_history_reconstructs_repairs_and_final_selection(self):
        first_code = 'module TopModule; endmodule\n'
        second_code = 'module TopModule; wire fixed; endmodule\n'
        backend = FakeBackend([reply(first_code), reply(second_code)])
        tools = FakeToolchain([tool_result('lint', 'failed', 'lint failed'), tool_result('lint', 'ok', 'lint ok')],
                              [tool_result('synth', 'ok', 'Synthesis finished')])
        with tempfile.TemporaryDirectory() as temp:
            result = run_repair(temp, backend, tools)
            first = json.loads(Path(temp, 'candidates/c001.json').read_text())
            second = json.loads(Path(temp, 'candidates/c002.json').read_text())
            selection = json.loads(Path(temp, 'selection.json').read_text())
            self.assertEqual(first['source_call_id'], 'm001')
            self.assertEqual(second['source_call_id'], 'm002')
            self.assertEqual(second['parent_id'], 'c001')
            self.assertEqual(second['source_stage'], 'repair')
            self.assertEqual(result.selected_candidate.id, 'c002')
            self.assertEqual(selection['reason'], 'synth_passed')
            self.assertEqual(Path(temp, 'solution.v').read_text(), second_code)
            checks = [e for e in events(temp) if e['tool'] in ('lint', 'synth')]
            self.assertEqual([(e['tool'], e['status']) for e in checks],
                             [('lint', 'failed'), ('lint', 'passed'), ('synth', 'passed')])
            self.assertEqual([e['candidate_id'] for e in checks], ['c001', 'c002', 'c002'])
            self.assertEqual(len({e['check_id'] for e in checks}), 3)
            self.assertTrue(all(e['execution_id'] for e in checks))


if __name__ == '__main__':
    unittest.main()
