"""Shared fake services and evidence helpers for workflow tests."""
from __future__ import annotations
import json
from pathlib import Path
import sys

AGENT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(AGENT_ROOT))
from agent.core.model import ModelReply, BackendResponse
from agent.core.config import ModelConfig
from agent.core.registry import build_workflow
from agent.core.task import TaskSpec
from agent.core.runner import Runner, RunOptions
from agent.services.vivado import ToolResult


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
    return ToolResult(tool, ((tool,),), rc, status, 0.01, summary,
                      failure_kind='code' if status == 'failed' else 'unknown')


def events(temp):
    return [json.loads(line) for line in Path(temp, 'trace.jsonl').read_text().splitlines()]


def record_file(temp, relative):
    return next(Path(temp, 'records').glob(f'*/{relative}'))


def run_repair(temp, backend, tools, **params):
    return Runner(ModelConfig(), backend_factory=lambda config: backend,
                  toolchain_factory=lambda: tools).run(
        TaskSpec.from_text('test', 'Implement TopModule.'),
        lambda: build_workflow('repair_loop', use_skills=False, **params),
        options=RunOptions(Path(temp)))
