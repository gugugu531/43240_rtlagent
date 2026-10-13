"""Formal run.sh replay with local fake tools; no remote service or GPU."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from agent.core.configuration import ENV_FIELDS
from support import events

ROOT = Path(__file__).resolve().parents[2]


class EntryReplayTests(unittest.TestCase):
    def prepare(self, root):
        tools = root/'tools'; tools.mkdir()
        for name in ('xvlog', 'xelab', 'vivado'):
            text = '#!/bin/sh\nif [ "$1" = "-version" ]; then echo "Vivado Simulator v2026.1"; exit 0; fi\n'
            text += ('echo "ERROR: [VRFC 10-1280] artificial test failure"\nexit 1\n'
                     if name=='xvlog' else 'echo "Synthesis finished"\n')
            path = tools/name; path.write_text(text); path.chmod(0o755)
        task = root/'task'; task.mkdir()
        (task/'prompt.txt').write_text('Implement module Demo.')
        (task/'interface.txt').write_text('module Demo(input a, output q);')
        env = {k:v for k,v in os.environ.items() if k not in (*ENV_FIELDS, 'AGENT_CONFIG',
            'AGENT_CALLER_CWD', 'AGENT_TASK_ID', 'RTL_TOP', 'MODEL_NAME', 'PYTHONPATH',
            'AGENT_TMP', 'EDA_TMP', 'TRACK_TMP')}
        env.update(LLM_BACKEND='mock', VIVADO_BIN=str(tools),
                   PATH=str(Path(sys.executable).parent)+os.pathsep+env.get('PATH',''))
        return task, tools, env

    def invoke(self, root, task, env, workflow, initial=None):
        config = root/(workflow+'.json')
        data = dict(schema_version=1, runtime={'deadline_s':20, 'reserve_s':0,
                                              'initial_state':str(initial) if initial else None})
        config.write_text(json.dumps(data))
        out = root/(workflow+'-out')
        process = subprocess.run([str(ROOT/'run.sh'), str(task), str(out)], cwd=ROOT,
            env=dict(env, AGENT_CONFIG=str(config), AGENT_WORKFLOW=workflow),
            capture_output=True, text=True, timeout=25)
        self.assertEqual(process.returncode, 0, process.stderr)
        return out

    def test_workflow_environment_change_replays_through_formal_entry(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); task, tools, env = self.prepare(root)
            initial = self.invoke(root, task, env, 'search_initial')/'initial.json'
            self.assertTrue(initial.is_file())
            out = self.invoke(root, task, env, 'search_r2', initial)
            rows = events(out)
            self.assertTrue(any(e.get('event')=='initial_replayed' for e in rows))
            self.assertFalse(any(e.get('event')=='error' and e.get('tool')=='agent' for e in rows))
            self.assertGreater((out/'solution.v').stat().st_size, 0)
            self.assertEqual(sum(e.get('tool')=='llm' and e.get('event')=='started' for e in rows), 2)
            prefix = json.loads((out/'stop_after_two.json').read_text())
            self.assertEqual(prefix['tokens']['calls'], 2)

    def test_replay_still_rejects_license_config_and_tool_file_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); task, tools, env = self.prepare(root)
            initial = self.invoke(root, task, env, 'search_initial')/'initial.json'
            for change in ('license', 'part', 'binary'):
                altered = dict(env)
                if change=='license': altered['LM_LICENSE_FILE']='different-test-license'
                if change=='part': altered['RTL_PART']='different-test-part'
                if change=='binary':
                    path = tools/'xelab'; path.write_text(path.read_text()+'\n# changed tool\n')
                case = root/change; case.mkdir()
                out = self.invoke(case, task, altered, 'search_r2', initial)
                rows = events(out)
                self.assertTrue(any(e.get('event')=='error' and
                                    'replay tool identity changed' in e.get('excerpt','') for e in rows))
                self.assertFalse(any(e.get('event')=='initial_replayed' for e in rows))
