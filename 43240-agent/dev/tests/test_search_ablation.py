"""E2 routes, shared starts, bounded calls and independent candidates."""
from pathlib import Path
import json
import tempfile
import unittest

from agent.core.model import ModelCallError, ModelRequest
from agent.services.vivado import ToolResult, classify_tool_failure
from agent.workflows.search_ablation import normalize_tool_paths
from test_evidence_ablation import run, FIRST, FIXED, failure, success
from support import FakeBackend, FakeToolchain, events, reply, write_synthetic_corpus

SECOND = 'module TopModule; wire second_attempt; endmodule\n'
THIRD = 'module TopModule; wire third_attempt; endmodule\n'


class SearchTests(unittest.TestCase):
    def test_first_model_failure_does_not_fabricate_initial_or_stop_view(self):
        for workflow in ('search_r2', 'search_c3'):
            with self.subTest(workflow=workflow), tempfile.TemporaryDirectory() as temp:
                out = Path(temp)
                run(out, workflow, FakeBackend([ModelCallError('offline', kind='connection')]), FakeToolchain())
                self.assertFalse((out/'initial.json').exists())
                self.assertFalse((out/'stop_after_two.json').exists())

    def test_direct_first_check_unavailable_records_early_stop_without_more_calls(self):
        for workflow in ('search_r2', 'search_c3'):
            with self.subTest(workflow=workflow), tempfile.TemporaryDirectory() as temp:
                out = Path(temp); backend = FakeBackend([reply(FIRST)])
                run(out, workflow, backend,
                    FakeToolchain((ToolResult('lint', (), -1, 'unavailable', 0, 'missing'),)))
                prefix = json.loads((out/'stop_after_two.json').read_text())
                self.assertEqual(prefix['tokens']['calls'], 1)
                self.assertEqual(len(backend.requests), 1)
                self.assertIn(prefix['stop_reason'], ('environment', 'verification_unavailable'))

    def test_replayed_stop_view_uses_verified_initial_not_a_later_file_read(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); initial, _ = self.capture(root)
            initial_sha256 = json.loads(Path(initial).read_text())['sha256']
            class Backend(FakeBackend):
                def complete(self, request):
                    if not self.requests: Path(initial).unlink()
                    return super().complete(request)
            backend = Backend([reply(SECOND), reply(FIXED)])
            run(root/'replay', 'search_r2', backend,
                FakeToolchain((failure(), success('lint')), (success('synth'),)), initial)
            prefix = json.loads((root/'replay/stop_after_two.json').read_text())
            self.assertEqual(prefix['initial_sha256'], initial_sha256)
            self.assertEqual(prefix['tokens']['calls'], 2)
            self.assertEqual(len(backend.requests), 2)

    def test_direct_three_call_workflows_save_prefix_before_third_request(self):
        for workflow in ('search_r2', 'search_c3'):
            with self.subTest(workflow=workflow), tempfile.TemporaryDirectory() as temp:
                root = Path(temp); out = root/'direct'
                class Backend(FakeBackend):
                    def complete(self, request):
                        if len(self.requests)==2:
                            self.prefix_before_third = json.loads((out/'stop_after_two.json').read_text())
                        return super().complete(request)
                backend = Backend([reply(FIRST), reply(SECOND), reply(THIRD)])
                tools = FakeToolchain((failure(), failure(), failure()))
                run(out, workflow, backend, tools)
                self.assertEqual(len(backend.requests), 3)
                prefix = backend.prefix_before_third
                self.assertEqual(prefix['tokens']['calls'], 2)
                self.assertEqual(prefix['candidate_ids'], ['c001', 'c002'])
                self.assertEqual(prefix['code'], FIRST)
                self.assertNotIn('c003', prefix['candidate_ids'])
                initial = json.loads((out/'initial.json').read_text())
                self.assertEqual(prefix['initial_sha256'], initial['sha256'])
                self.assertEqual(prefix['shared_initial_wall_s'], initial['initial_wall_s'])
                self.assertGreaterEqual(prefix['branch_wall_s'], 0)

    def test_direct_repair_that_passes_early_saves_one_call_stop_view(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            backend = FakeBackend([reply(FIRST)])
            result = run(out, 'search_r2', backend,
                         FakeToolchain((success('lint'),), (success('synth'),)))
            prefix = json.loads((out/'stop_after_two.json').read_text())
            self.assertEqual(result.stop_reason, 'synth_passed')
            self.assertEqual(prefix['stop_reason'], 'synth_passed')
            self.assertEqual(prefix['tokens']['calls'], 1)
            self.assertEqual(len(backend.requests), 1)

    def test_direct_candidates_prefix_records_selection_and_survives_third_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            backend = FakeBackend([reply(FIRST), reply(SECOND), ModelCallError('offline', kind='connection')])
            result = run(out, 'search_c3', backend,
                FakeToolchain((failure(), success('lint')), (success('synth'),)))
            prefix = json.loads((out/'stop_after_two.json').read_text())
            self.assertEqual(result.selected_candidate.code, SECOND)
            self.assertEqual(prefix['code'], SECOND)
            self.assertEqual(prefix['tokens']['calls'], 2)
            self.assertEqual(prefix['stop_reason'], 'candidate_limit')

    def test_direct_first_extraction_failure_still_creates_valid_prefix(self):
        for workflow in ('search_r2', 'search_c3'):
            with self.subTest(workflow=workflow), tempfile.TemporaryDirectory() as temp:
                out = Path(temp)
                backend = FakeBackend([reply('not rtl'), reply('not rtl'), reply(FIXED)])
                run(out, workflow, backend, FakeToolchain((success('lint'),), (success('synth'),)))
                prefix = json.loads((out/'stop_after_two.json').read_text())
                self.assertEqual(prefix['code'], '')
                self.assertEqual(prefix['candidate_ids'], [])
                self.assertEqual(prefix['tokens']['calls'], 2)

    def test_guided_r2_uses_latest_error_and_same_bounds_as_r2(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); initial, _ = self.capture(root)
            corpus = write_synthetic_corpus(root)
            backend = FakeBackend([reply(SECOND), reply(FIXED)])
            tools = FakeToolchain((failure('VRFC 10-9336'), success('lint')), (success('synth'),))
            result = run(root/'guided', 'search_r2_guided', backend, tools, initial, corpus)
            self.assertEqual([r.seed for r in backend.requests], [20261014, 20261015])
            self.assertIn('SYNTHETIC_GUIDANCE', backend.requests[0].messages[-1]['content'])
            self.assertNotIn('SYNTHETIC_GUIDANCE', backend.requests[1].messages[-1]['content'])
            self.assertIn('10-9336', backend.requests[1].messages[-1]['content'])
            self.assertEqual(result.selected_candidate.code, FIXED)

    def test_guided_r2_without_corpus_matches_plain_r2_and_records_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); initial, _ = self.capture(root)
            requests = []
            for workflow in ('search_r2', 'search_r2_guided'):
                backend = FakeBackend([reply(FIXED)])
                run(root/workflow, workflow, backend,
                    FakeToolchain((success('lint'),), (success('synth'),)), initial)
                requests.append(backend.requests[0].payload('model'))
            self.assertEqual(*requests)
            self.assertTrue(any(e.get('reason') == 'corpus_not_configured'
                                for e in events(root/'search_r2_guided')))

    def capture(self, root, content=FIRST, passed=False):
        backend=FakeBackend([reply(content)])
        tools=FakeToolchain((success('lint'),) if passed else (failure(),), (success('synth'),))
        run(root/'initial','search_initial',backend,tools)
        return str(root/'initial/initial.json'),backend.requests[0]

    def test_second_repair_uses_latest_candidate_and_new_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);initial,_=self.capture(root)
            backend=FakeBackend([reply(SECOND),reply(FIXED)])
            tools=FakeToolchain((failure('VRFC 10-9336'),success('lint')),(success('synth'),))
            result=run(root/'r2','search_r2',backend,tools,initial)
            self.assertEqual([r.seed for r in backend.requests],[20261014,20261015])
            self.assertTrue(all(r.temperature==0.6 and r.top_p==0.95 for r in backend.requests))
            self.assertIn(SECOND.strip(),backend.requests[1].messages[-1]['content'])
            self.assertIn('10-9336',backend.requests[1].messages[-1]['content'])
            self.assertEqual(result.selected_candidate.parent_id,'c002')
            self.assertEqual(result.selected_candidate.code,FIXED)
            prefix=json.loads((root/'r2/stop_after_two.json').read_text())
            self.assertEqual(prefix['tokens']['calls'],2)
            self.assertEqual(prefix['candidate_ids'],['c001','c002'])
            self.assertEqual(prefix['code'],FIRST)
            self.assertNotIn('c003',prefix['candidate_ids'])

    def test_r1_and_r2_have_identical_first_repair_request(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);initial,_=self.capture(root)
            requests=[]
            for arm in ('r1','r2'):
                backend=FakeBackend([reply(FIXED)])
                run(root/arm,'search_'+arm,backend,FakeToolchain((success('lint'),),(success('synth'),)),initial)
                requests.append(backend.requests[0].payload('model'))
            self.assertEqual(*requests)

    def test_r1_stops_after_one_failed_repair_r2_after_two(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);initial,_=self.capture(root)
            for arm,count in (('r1',1),('r2',2)):
                backend=FakeBackend([reply(SECOND),reply(THIRD)])
                result=run(root/arm,'search_'+arm,backend,FakeToolchain((failure(),failure())),initial)
                self.assertEqual(len(backend.requests),count)
                self.assertEqual(result.selected_candidate.code,FIRST)

    def test_repair_stops_when_initial_passes_but_candidate_group_explores(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);initial,first=self.capture(root,passed=True)
            backend=FakeBackend([])
            run(root/'r2','search_r2',backend,FakeToolchain(),initial)
            self.assertFalse(backend.requests)
            backend=FakeBackend([reply(SECOND),reply(THIRD)])
            tools=FakeToolchain((success('lint'),success('lint')),(success('synth'),success('synth')))
            result=run(root/'c3','search_c3',backend,tools,initial)
            self.assertEqual(len(backend.requests),2)
            self.assertTrue(all(r.messages==first.messages for r in backend.requests))
            self.assertEqual((first.temperature,first.top_p),(0.6,0.95))
            prefix=json.loads((root/'c3/stop_after_two.json').read_text())
            self.assertEqual(prefix['code'],FIRST)
            self.assertEqual(prefix['tokens']['calls'],2)
            self.assertEqual(prefix['candidate_ids'],['c001','c002'])
            self.assertTrue(all(r.purpose=='generate' for r in backend.requests))
            self.assertEqual(result.selected_candidate.code,FIRST)

    def test_candidate_selection_keeps_earlier_when_both_new_candidates_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);initial,first=self.capture(root)
            backend=FakeBackend([reply(SECOND),reply(THIRD)])
            tools=FakeToolchain((success('lint'),success('lint')),(success('synth'),success('synth')))
            result=run(root/'c3','search_c3',backend,tools,initial)
            self.assertEqual(result.selected_candidate.code,SECOND)
            prefix=json.loads((root/'c3/stop_after_two.json').read_text())
            self.assertEqual(prefix['code'],SECOND)
            self.assertEqual(prefix['candidate_ids'],['c001','c002'])
            self.assertIsNone(result.selected_candidate.parent_id)
            self.assertEqual([r.seed for r in backend.requests],[20261014,20261015])
            self.assertTrue(all(r.messages==first.messages for r in backend.requests))

    def test_new_extraction_failure_does_not_discard_old_candidate(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);initial,_=self.capture(root)
            backend=FakeBackend([reply('not rtl'),reply(FIXED)])
            result=run(root/'c3','search_c3',backend,FakeToolchain((success('lint'),),(success('synth'),)),initial)
            self.assertEqual(len(backend.requests),2)
            self.assertEqual(result.selected_candidate.code,FIXED)

    def test_candidate_environment_failure_stops_and_retains_answer(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);initial,_=self.capture(root)
            backend=FakeBackend([reply(SECOND),reply(THIRD)])
            result=run(root/'c3','search_c3',backend,
                FakeToolchain((ToolResult('lint',(),-1,'unavailable',0,'missing'),)),initial)
            self.assertEqual(len(backend.requests),1)
            self.assertIsNotNone(result.selected_candidate)
            self.assertEqual(result.stop_reason,'environment')

    def test_transport_failure_is_not_resampled(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);initial,_=self.capture(root)
            for arm in ('r2','c3'):
                backend=FakeBackend([ModelCallError('offline',kind='connection',retryable=True)])
                result=run(root/arm,'search_'+arm,backend,FakeToolchain(),initial)
                self.assertEqual(len(backend.requests),1)
                self.assertEqual(result.selected_candidate.code,FIRST)

    def test_tool_path_normalization_preserves_location_and_other_paths(self):
        a='ERROR: [VRFC 10-1219] bad [/tmp/agent_lint_random123/solution.sv:17]'
        b='ERROR: [VRFC 10-1219] bad [/tmp/agent_lint_other_42/solution.sv:17]'
        self.assertEqual(normalize_tool_paths(a),normalize_tool_paths(b))
        self.assertIn('solution.sv:17',normalize_tool_paths(a))
        self.assertEqual(normalize_tool_paths('/source/solution.sv:17'),'/source/solution.sv:17')

    def test_select_direction_is_primary_code_error_and_environment_still_precedes(self):
        text='ERROR: [VRFC 10-1219] part-select direction is opposite from prefix index direction'
        self.assertEqual(classify_tool_failure(text),'code')
        self.assertEqual(classify_tool_failure('permission denied\n'+text),'environment')
        self.assertEqual(classify_tool_failure('ERROR: [XSIM 43-3322] elaboration failed'),'unknown')

    def test_explicit_seed_does_not_change_default_or_baseline_payload(self):
        self.assertNotIn('seed',ModelRequest([]).payload('model'))
        self.assertNotIn('seed',ModelRequest([],profile='baseline_rtl').payload('model'))
        self.assertEqual(ModelRequest([],seed=123).payload('model')['seed'],123)
        for value in (True,-1,2**32):
            with self.assertRaises(ModelCallError):ModelRequest([],seed=value)
        with self.assertRaises(ModelCallError):ModelRequest([],profile='baseline_rtl',seed=123)
