"""Paused samples must not become scored zeros or duplicate valid answers."""
import json
from pathlib import Path
import tempfile
import unittest
from dev.tools.combine_runs import combine


class CombineRunsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.old = Path(self.temp.name)/'old'
        self.new = Path(self.temp.name)/'new'
        for run, status, tasks in ((self.old, 'cancelled', ['a', 'b']),
                                   (self.new, 'completed', ['b'])):
            (run/'source').mkdir(parents=True)
            self.write(run/'experiment.json', {'status': status, 'experiment':
                       {'modes': ['agent', 'baseline'], 'samples': 1}})
            (run/'resolved.yaml').write_text('effective configuration\n')
            self.write(run/'source/manifest.json', {'files':
                       [{'path': 'agent/test.py', 'sha256': 'unchanged'}]})
            self.write(run/'tasks.json', {'tasks':
                       [{'task_id': t, 'inputs': {'prompt.txt': t}} for t in tasks]})
        self.old_rows = [self.row(t, m, t == 'a') for t in ('a', 'b')
                         for m in ('agent', 'baseline')]
        self.new_rows = [self.row('b', m) for m in ('agent', 'baseline')]
        self.write(self.old/'metrics.json', self.old_rows)
        self.write(self.new/'metrics.json', self.new_rows)

    @staticmethod
    def write(path, value):
        path.write_text(json.dumps(value))

    @staticmethod
    def row(task, mode, valid=True):
        return {'task_id': task, 'mode': mode, 'index': 0, 'output_dir': '/unused',
                'solve': {'status': 'ok' if valid else 'cancelled', 'wall_s': 1},
                'metrics': [
                    {'name': 'model', 'version': 1, 'status': 'ok',
                     'values': {'failed': 0, 'unfinished': 0}},
                    {'name': 'judge', 'version': 1, 'status': 'ok' if valid else 'skipped',
                     'values': {'verdict': {'level': 3, 'coefficient': 1, 'elapsed_s': 1}
                                if valid else None}}]}

    def test_complete_merge_and_no_original_mutation(self):
        before = (self.old/'metrics.json').read_bytes()
        summary, samples, provenance = combine(self.old, self.new)
        self.assertEqual(len(samples), 4)
        self.assertEqual(len(provenance['skipped']), 2)
        self.assertTrue(summary['comparison']['full_comparison_valid'])
        self.assertEqual(summary['modes']['agent']['judge']['set_score'], 1)
        self.assertEqual((self.old/'metrics.json').read_bytes(), before)

    def test_duplicate_rejected(self):
        self.write(self.new/'metrics.json', self.new_rows+[self.row('a', 'agent')])
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            combine(self.old, self.new)

    def test_incomplete_rejected(self):
        self.write(self.new/'metrics.json', self.new_rows[:1])
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            combine(self.old, self.new)

    def test_model_failure_rejected(self):
        self.new_rows[0]['metrics'][0]['values']['failed'] = 1
        self.write(self.new/'metrics.json', self.new_rows)
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            combine(self.old, self.new)

    def test_changed_configuration_rejected(self):
        (self.new/'resolved.yaml').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'configurations'):
            combine(self.old, self.new)

    def test_changed_source_rejected(self):
        self.write(self.new/'source/manifest.json', {'files':
                   [{'path': 'agent/test.py', 'sha256': 'changed'}]})
        with self.assertRaisesRegex(ValueError, 'source hashes'):
            combine(self.old, self.new)

    def test_changed_task_rejected(self):
        self.write(self.new/'tasks.json', {'tasks': [{'task_id': 'b', 'inputs': {}}]})
        with self.assertRaisesRegex(ValueError, 'input hashes'):
            combine(self.old, self.new)
