"""E1 shared starts, no-hit identity and failed repair preservation."""
from pathlib import Path
import json
import tempfile
import unittest

from agent.core.config import ModelConfig
from agent.core.registry import build_workflow
from agent.core.runner import Runner, RunOptions
from agent.core.task import TaskSpec
from agent.core.replay import digest
from agent.services.vivado import ToolResult
from agent.services.knowledge import load_corpus, retrieve_repair_guides
from support import FakeBackend, FakeToolchain, events, reply

TASK = TaskSpec.from_text('test', 'Implement TopModule.')
FIRST = 'module TopModule; wire broken; endmodule\n'
FIXED = 'module TopModule; endmodule\n'


def failure(code='VRFC 10-1280'):
    return ToolResult('lint', (), 1, 'failed', 0.01, f'ERROR: [{code}] broken',
                      failure_kind='code', diagnostic_tool='xvlog', tool_version='2026.1')


def success(kind):
    return ToolResult(kind, (), 0, 'ok', 0.01, 'passed')


def run(out, workflow, backend, tools, initial=None):
    return Runner(ModelConfig(), backend_factory=lambda config: backend,
                  toolchain_factory=lambda: tools).run(TASK,
                    lambda: build_workflow(workflow, initial_state=initial), options=RunOptions(out))


class AblationTests(unittest.TestCase):
    def capture(self, root, code='VRFC 10-1280', content=FIRST):
        out = root / 'a0'
        backend = FakeBackend([reply(content)])
        run(out, 'evidence_a0', backend, FakeToolchain(lint_results=(failure(code),)))
        return out / 'initial.json', backend.requests[0]

    def test_a0_first_prompt_matches_existing_scheme_and_never_repairs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            checkpoint, first_request = self.capture(root)
            backend = FakeBackend([reply(FIRST)])
            # Environment unavailable stops A1 after the same first request.
            tools = FakeToolchain(lint_results=(ToolResult('lint', (), -1, 'unavailable', 0, 'missing'),))
            run(root / 'a1', 'evidence_a1', backend, tools)
            self.assertEqual(first_request.messages, backend.requests[0].messages)
            self.assertTrue(checkpoint.is_file())

    def test_shared_start_has_no_extra_generation_and_original_usage_is_debited(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); checkpoint, _ = self.capture(root)
            backend = FakeBackend([reply(FIXED)])
            result = run(root / 'a1', 'evidence_a1', backend,
                         FakeToolchain((success('lint'),), (success('synth'),)), str(checkpoint))
            self.assertEqual(len(backend.requests), 1)
            self.assertEqual(result.selected_candidate.id, 'c002')
            self.assertEqual(result.selected_candidate.parent_id, 'c001')
            self.assertEqual(result.stop_reason, 'synth_passed')
            rows = events(root / 'a1')
            replay = next(e for e in rows if e.get('event') == 'initial_replayed')
            self.assertEqual(replay['initial_calls'], 1)
            accounting = next(e for e in reversed(rows) if e.get('tool') == 'tokens' and e.get('event') == 'final')['snapshot']
            self.assertEqual(accounting['calls'], 2)

    def test_a2_no_hit_messages_exactly_equal_a1(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); checkpoint, _ = self.capture(root, 'VRFC 10-9999')
            requests = []
            for arm in ('a1', 'a2'):
                backend = FakeBackend([reply(FIXED)])
                run(root / arm, 'evidence_' + arm, backend,
                    FakeToolchain((success('lint'),), (success('synth'),)), str(checkpoint))
                requests.append(backend.requests[0].messages)
            self.assertEqual(*requests)

    def test_a2_hit_uses_card_and_failed_repair_keeps_initial_candidate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); checkpoint, _ = self.capture(root)
            backend = FakeBackend([reply('not rtl')])
            result = run(root / 'a2', 'evidence_a2', backend, FakeToolchain(), str(checkpoint))
            self.assertEqual(result.selected_candidate.code, FIRST)
            self.assertIn('参考知识 procedural-variable', backend.requests[0].messages[-1]['content'])

    def test_unknown_versions_do_not_produce_guidance(self):
        corpus = load_corpus()
        for tool, version in ((None, '2026.1'), ('xvlog', None), ('xelab', '2026.1'), ('xvlog', '2025.2')):
            self.assertFalse(retrieve_repair_guides(corpus, codes=('VRFC 10-1280',), tool=tool, version=version)['pieces'])
        self.assertFalse(retrieve_repair_guides(corpus, codes=('VRFC 10-1280',), tool='xvlog', version='2026.1', max_chars=1)['pieces'])

    def test_unexpected_judge_fields_and_source_changes_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); checkpoint, _ = self.capture(root)
            original = json.loads(checkpoint.read_text())
            for change in ('judge', 'source', 'checksum'):
                data = dict(original)
                if change == 'judge': data['judge'] = {'level': 3}
                if change == 'source': data['runtime_hashes'] = {}
                if change != 'checksum':
                    data.pop('sha256'); data['sha256'] = digest(data)
                else: data['initial_wall_s'] += 1
                path = root / f'{change}.json'; path.write_text(json.dumps(data))
                backend = FakeBackend([])
                result = run(root / change, 'evidence_a1', backend, FakeToolchain(), str(path))
                self.assertEqual(result.status, 'error')
                self.assertFalse(backend.requests)

    def test_initial_extraction_failure_is_kept_and_repairable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); checkpoint, _ = self.capture(root, content='not rtl')
            backend = FakeBackend([reply(FIXED)])
            result = run(root / 'a1', 'evidence_a1', backend,
                         FakeToolchain((success('lint'),), (success('synth'),)), str(checkpoint))
            self.assertEqual(result.stop_reason, 'synth_passed')
            self.assertEqual(len(backend.requests), 1)

    def test_replayed_a1_repair_messages_match_direct_a1_including_evidence_ids(self):
        for content in (FIRST, 'not rtl'):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as temp:
                root = Path(temp); checkpoint, _ = self.capture(root, content=content)
                direct = FakeBackend([reply(content), reply(FIXED)])
                tools = FakeToolchain((failure(), success('lint')) if content == FIRST else (success('lint'),),
                                      (success('synth'),))
                run(root / 'direct', 'evidence_a1', direct, tools)
                replayed = FakeBackend([reply(FIXED)])
                run(root / 'replay', 'evidence_a1', replayed,
                    FakeToolchain((success('lint'),), (success('synth'),)), str(checkpoint))
                self.assertEqual(direct.requests[1].messages, replayed.requests[0].messages)
                calls = [e for e in events(root / 'replay') if e.get('tool')=='llm' and e.get('event')=='started']
                self.assertEqual(calls[0]['call_id'], 'm002')

    def test_failed_replayed_repair_stops_at_one_repair(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); checkpoint, _ = self.capture(root)
            backend = FakeBackend([reply(FIXED)])
            result = run(root / 'a1', 'evidence_a1', backend,
                         FakeToolchain((failure(),)), str(checkpoint))
            self.assertEqual(result.stop_reason, 'code')
            self.assertEqual(len(backend.requests), 1)

    def test_initial_time_exhaustion_stops_before_request_and_keeps_candidate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); checkpoint, _ = self.capture(root)
            data = json.loads(checkpoint.read_text()); data.pop('sha256')
            data['initial_wall_s'] = 1000; data['sha256'] = digest(data); checkpoint.write_text(json.dumps(data))
            backend = FakeBackend([])
            result = run(root / 'a1', 'evidence_a1', backend, FakeToolchain(), str(checkpoint))
            self.assertEqual(result.stop_reason, 'deadline')
            self.assertEqual(result.selected_candidate.code, FIRST)
            self.assertFalse(backend.requests)
