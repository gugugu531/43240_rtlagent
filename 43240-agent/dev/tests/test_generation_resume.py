"""Cancelled-only continuation must not select samples by their score."""
import json
from pathlib import Path
import tempfile
import unittest
from dev.tools.generation_resume import pending_keys
from dev.tests import test_combine_runs, test_generation_sweep
from dev.tools.generation_sweep import audits_for_run


class ResumeSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name)
        self.write('experiment.json', {'status': 'cancelled', 'experiment':
                   {'modes': ['agent', 'baseline'], 'samples': 1}})
        self.write('tasks.json', {'tasks': [{'task_id': 'a'}]})
        self.rows = [test_combine_runs.CombineRunsTests.row('a', 'agent'),
                     test_combine_runs.CombineRunsTests.row('a', 'baseline', False)]
        self.rows[1]['metrics'][0]['status'] = 'skipped'
        self.write('metrics.json', self.rows)

    def write(self, name, value):
        (self.run/name).write_text(json.dumps(value))

    def test_only_cancelled_sample(self):
        self.assertEqual(pending_keys(self.run), {('a', 'baseline', 0)})

    def test_completed_l0_is_not_resampled(self):
        self.rows[0]['metrics'][1]['values']['verdict'].update(level=0, coefficient=0)
        self.write('metrics.json', self.rows)
        self.assertEqual(pending_keys(self.run), {('a', 'baseline', 0)})

    def test_failed_model_is_not_resampled(self):
        self.rows[0]['metrics'][0]['values']['failed'] = 1
        self.write('metrics.json', self.rows)
        with self.assertRaisesRegex(ValueError, 'manual review'):
            pending_keys(self.run)

    def test_judge_only_interruption_requires_review(self):
        self.rows[0]['metrics'][1]['status'] = 'skipped'
        self.write('metrics.json', self.rows)
        with self.assertRaisesRegex(ValueError, 'manual review'):
            pending_keys(self.run)

    def test_partial_cancelled_metrics_require_review(self):
        self.rows[1]['metrics'][0]['status'] = 'ok'
        self.write('metrics.json', self.rows)
        with self.assertRaisesRegex(ValueError, 'partial metrics'):
            pending_keys(self.run)

    def test_missing_sample_rejected(self):
        self.write('metrics.json', self.rows[:1])
        with self.assertRaisesRegex(ValueError, 'incomplete manifest'):
            pending_keys(self.run)

    def test_duplicate_rejected(self):
        self.write('metrics.json', self.rows + self.rows[:1])
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            pending_keys(self.run)


class ResumeAuditTests(unittest.TestCase):
    def test_selected_samples_only_and_unfinished_request_retained(self):
        with tempfile.TemporaryDirectory() as tmp:
            arm, run = test_generation_sweep.SweepEvidenceTests().fixture(Path(tmp))
            (arm/'gateway/0.response.json').unlink()
            discarded = []
            rows = audits_for_run(arm, run, sample_keys={('Task', 'agent', 0)},
                                  discarded_requests=discarded)
            self.assertEqual(len(rows), 2)
            self.assertEqual(len(discarded), 1)
            self.assertIsNone(discarded[0]['response'])

    def test_missing_selected_baseline_response_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            arm, run = test_generation_sweep.SweepEvidenceTests().fixture(Path(tmp))
            (arm/'gateway/0.response.json').unlink()
            with self.assertRaisesRegex(ValueError, 'upstream failure'):
                audits_for_run(arm, run, sample_keys={('Task', 'baseline', 0)}, discarded_requests=[])
