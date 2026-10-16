"""Current scoring boundaries and asynchronous submission-client behavior."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from dev.tools.scoring import normalized_gain, score_results
from dev.tools.experiment import SampleResult, summarize_experiment
from agent.recording.metrics import MetricResult
spec = importlib.util.spec_from_file_location('alignment_submit_client', ROOT/'dev/tools/remote/submit_client.py')
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)


class GainTests(unittest.TestCase):
    def test_upstream_example_and_boundaries(self):
        gain, score = normalized_gain(0.76, 0.5)
        self.assertAlmostEqual(gain, 0.52)
        self.assertAlmostEqual(score, 34.6666666667)
        self.assertEqual(normalized_gain(0.6, 0), (0.6, 40))
        self.assertEqual(normalized_gain(1, 1), (1, 40))
        self.assertEqual(normalized_gain(0.2, 0.2), (0, 0))
        self.assertEqual(normalized_gain(0.1, 0.5), (-0.8, 0))

    def test_aggregation_requires_matching_actual_sample_ids(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for mode, coef, sample in [('agent',0.76,0), ('baseline',0.5,1)]:
                (root/f'{mode}.t.s{sample}.json').write_text(json.dumps(dict(task_id='t',coefficient=coef,level=2)))
            report = score_results(temp)
            self.assertFalse(report['paired_coverage'])
            self.assertIsNone(report['gain_g'])
            (root/'baseline.t.s1.json').rename(root/'baseline.t.s0.json')
            report = score_results(temp)
            self.assertTrue(report['paired_coverage'])
            self.assertEqual(report['gain_g'], 0.52)
            self.assertEqual(report['gain_score'], 34.67)
            self.assertEqual(report['gain_ratio'], 1.52)
            self.assertEqual(report['capability_score'], 22.8)
            (root/'baseline.t.s0.json').write_text(json.dumps(dict(task_id='t',tool_error='license')))
            self.assertIsNone(score_results(temp)['gain_score'])

    def test_current_experiment_keeps_ratio_and_adds_normalized_gain(self):
        samples = []
        for mode, coef in [('agent', 0.76), ('baseline', 0.5)]:
            metric = MetricResult('judge', 1, 'ok', {'verdict':dict(coefficient=coef,level=2)})
            samples.append(SampleResult('t',mode,0,Path('/tmp'),{},(metric,)))
        comparison = summarize_experiment(samples)['comparison']
        self.assertAlmostEqual(comparison['gain_g'], 0.52)
        self.assertAlmostEqual(comparison['gain_score'], 34.6666666667)
        self.assertEqual(comparison['gain_ratio'], 1.52)
        self.assertEqual(comparison['gain'], 1.52)
        samples[1] = SampleResult('other','baseline',0,Path('/tmp'),{},samples[1].metrics)
        self.assertIsNone(summarize_experiment(samples)['comparison']['gain_g'])


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.task = self.root/'t'; self.task.mkdir()
        (self.task/'prompt.txt').write_text('Implement TopModule.')
        self.args = SimpleNamespace(url='http://127.0.0.1:7860',token='test-token',deadline=1,no_judge=True)

    def solve(self, responses):
        with patch.object(client, 'http', side_effect=responses) as http, patch.object(client.time, 'sleep'):
            info = client.solve_one(self.args, str(self.root/'run'), 'agent', str(self.task), 0)
        return info, http

    def test_202_queued_running_done_and_file_outputs(self):
        base = dict(task_id='t',job_id='abc')
        info, http = self.solve([(202,dict(base,status='queued')), (200,dict(base,status='running')),
                                (200,dict(base,status='done',solution='module X; endmodule',trace='{}\n',elapsed_s=0.5))])
        self.assertIsNone(info['transport_error'])
        self.assertEqual([row.args[0] for row in http.call_args_list], ['POST','GET','GET'])
        self.assertEqual(http.call_args_list[1].args[1], self.args.url+'/v1/jobs/abc')
        self.assertEqual((self.root/'run/agent/t/s0/solution.v').read_text(), 'module X; endmodule')
        self.assertEqual(info['job_id'], 'abc')

    def test_bad_acceptance_is_l0_without_retry(self):
        for response in [(200,{}), (202,dict(task_id='wrong',job_id='a',status='queued')),
                         (202,dict(task_id='t',job_id='',status='queued'))]:
            info, http = self.solve([response])
            self.assertIsNotNone(info['transport_error'])
            self.assertEqual(info['solution_bytes'], 0)
            self.assertEqual(http.call_count, 1)

    def test_bad_poll_identity_status_and_result_are_l0(self):
        base = dict(task_id='t',job_id='a',status='queued')
        for result in [dict(base,job_id='other'), dict(base,status='error'), dict(base,status='done')]:
            info, http = self.solve([(202,base),(200,result)])
            self.assertIsNotNone(info['transport_error'])
            self.assertEqual(http.call_count, 2)

    def test_expired_total_clock_does_not_poll_or_resubmit(self):
        with patch.object(client, 'http', return_value=(202,dict(task_id='t',job_id='a',status='queued'))) as http, \
             patch.object(client.time, 'monotonic', side_effect=[0,0,22,23]):
            info = client.solve_one(self.args,str(self.root/'run'),'agent',str(self.task),0)
        self.assertIn('TimeoutError', info['transport_error'])
        self.assertEqual(http.call_count, 1)


if __name__ == '__main__': unittest.main()
