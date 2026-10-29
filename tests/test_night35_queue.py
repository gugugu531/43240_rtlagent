"""Fault-injection test: a failed card must not prevent the following card."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'dev/optimization-v35'))
spec=importlib.util.spec_from_file_location('test_night35_queue_impl',ROOT/'dev/optimization-v35/night_queue.py')
q=importlib.util.module_from_spec(spec);spec.loader.exec_module(q)


class NightQueueIsolation(unittest.TestCase):
    def test_worker_exception_does_not_stop_next_card(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary)
            campaign={'campaign_id':'fault-test','hosts':{'33376':{'case_ids':['broken','next'],'max_calls':4}},'work_seconds':27000,'per_case_worker_timeout_s':2200}
            (folder/'campaign.json').write_text(json.dumps(campaign))
            started=[]
            class Child:
                pid=12345
                def __init__(self,command,**kwargs):
                    identity=command[command.index('--case')+1];started.append(identity)
                    if identity=='broken':raise OSError('injected worker launch failure')
                    path=Path(command[command.index('--output')+1]);path.mkdir(parents=True);(path/'status.json').write_text(json.dumps({'status':'preflight_passed'}));self.returncode=0
                def wait(self,timeout):return self.returncode
            fake=types.ModuleType('audit');fake.run=lambda *a:{'status':'passed'}
            with patch.object(q,'HERE',folder),patch.object(q,'ROOT',folder),patch.object(q,'validate',return_value={}),patch.object(q,'health',return_value=True),patch.object(q.subprocess,'Popen',Child),patch.dict(os.environ,{'RTLA_NIGHT_MODEL_LOCK':str(folder/'model.lock')}),patch.dict(sys.modules,{'audit':fake}):
                result=q.run(33376)
            self.assertEqual(started,['broken','next'])
            self.assertEqual([r['status'] for r in result['completed']],['job_error','preflight_passed'])
            self.assertEqual(result['actual_calls'],0)
            self.assertEqual(result['status'],'completed_with_records')

    def test_scope_and_budget_are_independent(self):
        campaign=json.loads((ROOT/'dev/optimization-v35/campaign.json').read_text())
        tasks=json.loads((ROOT/'dev/optimization-v35/tasks.json').read_text())['tasks']
        self.assertEqual(len({r['card_id'] for r in tasks}),97)
        self.assertEqual(sorted(v['cards'] for v in campaign['hosts'].values()),[48,49])
        self.assertEqual(sum(v['max_calls'] for v in campaign['hosts'].values()),campaign['max_new_generation_calls'])
        self.assertEqual(campaign['max_new_generation_calls'],106)
        self.assertFalse(campaign['automatic_retries'])
        self.assertTrue(campaign['new_budget_independent_of_previous_60'])

if __name__=='__main__':unittest.main()
