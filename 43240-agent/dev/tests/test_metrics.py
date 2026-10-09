"""Metric errors and unknown model usage."""
from pathlib import Path
import json
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from agent.recording.metrics import CompletedSample, ModelMetric, collect_metrics


class MetricsTests(unittest.TestCase):
    def test_interrupted_and_failed_calls_preserve_unknown_tokens(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);rows=[{'tool':'llm','event':'started','call_id':'m1'},
                              {'tool':'llm','event':'started','call_id':'m2'},
                              {'tool':'llm','event':'failed','call_id':'m2','kind':'timeout'}]
            (root/'trace.jsonl').write_text('\n'.join(json.dumps(x) for x in rows))
            result=ModelMetric().collect(CompletedSample('x','agent',0,root))
            self.assertEqual(result.status,'partial');self.assertEqual(result.values['attempts'],2)
            self.assertEqual(result.values['unfinished'],1);self.assertEqual(result.values['failed'],1)
            self.assertIsNone(result.values['prompt_tokens']['known_total'])

    def test_known_zero_and_unknown_are_distinct(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            (root/'trace.jsonl').write_text(json.dumps({'tool':'llm','event':'succeeded','call_id':'m1','tokens_in':0,'tokens_out':0}))
            result=ModelMetric().collect(CompletedSample('x','agent',0,root))
            self.assertEqual(result.status,'ok');self.assertEqual(result.values['prompt_tokens']['known_total'],0)

    def test_collector_exception_is_explicit_error(self):
        class Failing:
            name,version='custom',1
            def collect(self,sample):raise RuntimeError('do not expose secret')
        result=collect_metrics(CompletedSample('x','agent',0,Path('/tmp')),[Failing()])[0]
        self.assertEqual(result.status,'error');self.assertNotIn('secret',json.dumps(result.public_dict()))



if __name__ == '__main__':
    unittest.main()
