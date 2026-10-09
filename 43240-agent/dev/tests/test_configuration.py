"""Configuration validation, provenance and budgets."""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from agent.core.configuration import load_config,resolve_config,RunOverrides,ConfigError,build_run_spec
from agent.core.task import TaskSpec


class ConfigurationTests(unittest.TestCase):
    def config(self, root, body):
        path = root/'config.yaml';path.write_text('schema_version: 1\n'+body)
        return load_config(path)

    def test_yaml_environment_cli_provenance_and_secret_reference(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            doc=self.config(root,'workflow: {type: repair_loop}\nservices:\n  model:\n    api_key_env: PRIVATE_MODEL_KEY\n    timeout_s: 50\nruntime:\n  recording: {root: records}\n')
            resolved=resolve_config(doc,env={'LLM_TIMEOUT_S':'80','PRIVATE_MODEL_KEY':'sensitive-value'},
                                    overrides=RunOverrides({'services.model.timeout_s':90}))
            self.assertEqual(resolved.agent.services.model.timeout_s,90)
            self.assertEqual(resolved.sources['services.model.timeout_s'],'cli')
            self.assertEqual(resolved.agent.runtime.recording_root,root/'records')
            self.assertEqual(resolved.agent.services.model.api_key,'sensitive-value')
            self.assertNotIn('sensitive-value',json.dumps(resolved.public_dict()))
            self.assertEqual(resolved.public_dict()['effective']['services']['model']['api_key_env'],'PRIVATE_MODEL_KEY')

    def test_duplicate_unknown_alias_and_invalid_scalar_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            for body in ['workflow: {type: a, type: b}\n','bindings: {}\n','imports: &x [a]\nworkflow: {type: *x}\n',
                         'runtime: {deadline_s: true}\n','runtime: {deadline_s: .nan}\n','imports: [abc, abc]\n']:
                with self.subTest(body=body),self.assertRaises((ConfigError,ValueError)):
                    resolve_config(self.config(root,body),env={})

    def test_http_budget_only_shrinks_and_reserve_is_preserved(self):
        with tempfile.TemporaryDirectory() as t:
            cfg=resolve_config(self.config(Path(t),'runtime: {deadline_s: 30, reserve_s: 2}\n'),env={})
            task=TaskSpec.from_text('x','Implement TopModule.')
            for hard,expected in [(100,30),(1,1)]:
                spec=build_run_spec(task,cfg,output_dir=Path(t)/'out',started_at=time.monotonic(),hard_deadline_s=hard)
                self.assertEqual(spec.options.deadline_s,expected)
                self.assertEqual(spec.options.reserve_s,2)

    def test_bad_config_leaves_trace_and_empty_answer_without_exposing_values(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t); task=root/'task';task.mkdir();(task/'prompt.txt').write_text('Implement TopModule.')
            path=root/'bad.yaml';path.write_text('schema_version: 1\nservices:\n  model:\n    api_key: sensitive-test-secret\n')
            result=subprocess.run([str(ROOT/'run.sh'),str(task),str(root/'out'),'--config',str(path)],
                                  env=dict(os.environ,LLM_BACKEND='mock'),capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0)
            self.assertEqual((root/'out/solution.v').read_text(),'')
            trace=(root/'out/trace.jsonl').read_text()
            self.assertTrue(trace);self.assertNotIn('sensitive-test-secret',trace)
            self.assertTrue(any(json.loads(l).get('reason')=='configuration_or_entry_error' for l in trace.splitlines()))

    def test_shell_configuration_and_record_paths_follow_callers_directory(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);task=root/'task';task.mkdir()
            (task/'prompt.txt').write_text('module TopModule(input a, output q);')
            (root/'options.yaml').write_text('schema_version: 1\n')
            result=subprocess.run([str(ROOT/'run.sh'),'task','out','--config','options.yaml','--record-root','evidence'],
                cwd=root,env=dict(os.environ,LLM_BACKEND='mock'),capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0)
            self.assertIn('module TopModule',(root/'out/solution.v').read_text())
            self.assertEqual(len(list((root/'evidence').glob('*/task.json'))),1)

    def test_explicit_tools_are_per_instance(self):
        from agent.services.vivado import RtlToolchain
        from agent.core.config import ToolConfig
        with tempfile.TemporaryDirectory() as t:
            a=RtlToolchain(config=ToolConfig(part='part_a',bin_dir=t,temp_dir=t))
            b=RtlToolchain(config=ToolConfig(part='part_b',temp_dir='/tmp'))
            self.assertFalse(a.available);self.assertEqual(a.config.part,'part_a')
            self.assertEqual(b.config.part,'part_b')



if __name__ == '__main__':
    unittest.main()
