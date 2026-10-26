"""Local-only safety tests; all model and judge calls are mocked."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace as NS
import run_skill_pilot as pilot
from agent.config import Config


class BatchSafety(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.source=pilot.HERE
        self.row=json.loads((self.source/'inputs.json').read_text())[0]
        for name in (self.row['body_file'],'boundary-only.txt'):
            (self.root/name).write_text((self.source/name).read_text())

    def config(self,**kwargs):
        return Config(**{**kwargs,'services':{'model':{'backend':'mock','max_model_len':65536}}})

    def judge(self,command,**kwargs):
        Path(command[-1]).write_text(json.dumps({'level':1,'mismatches':1,'tool_error':None}))
        return NS(returncode=0,stdout='mock judge',stderr='')

    def execute(self,arm,judge=None):
        with patch.object(pilot,'HERE',self.root),patch.object(pilot,'Config',self.config),\
             patch.object(pilot,'checks',lambda ctx,state:state.update(check_passed=False)),\
             patch.object(pilot.subprocess,'run',judge or self.judge):
            return pilot.run(self.row,arm)

    def test_all_three_arms_include_exact_assigned_knowledge(self):
        for arm in ('control','skill-v2','boundary-only'):
            result=self.execute(arm)
            self.assertIsNone(result['error'])
            self.assertEqual(result['knowledge_sent'],[] if arm=='control' else [self.row['skill_id']])
            self.assertTrue((self.root/'runs'/self.row['case']/arm/'model-result.json').exists())

    def test_partial_result_never_regenerates(self):
        folder=self.root/'runs'/self.row['case']/'control';folder.mkdir(parents=True)
        (folder/'started.json').write_text('{}')
        with self.assertRaises(FileExistsError):self.execute('control')

    def test_completed_result_reuses_without_any_request(self):
        first=self.execute('control')
        with patch.object(pilot,'Client',side_effect=AssertionError('unexpected model client')):
            self.assertEqual(self.execute('control'),first)

    def test_judge_failure_is_persisted(self):
        def broken(*args,**kwargs):raise TimeoutError('mock judge timeout')
        result=self.execute('control',broken)
        self.assertIn('judge:',result['error'])
        self.assertIsNone(result['judge'])
        self.assertTrue((self.root/'runs'/self.row['case']/'control'/'result.json').exists())


if __name__=='__main__':unittest.main()
