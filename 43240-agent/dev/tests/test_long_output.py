"""The development ablation changes only output and timeout budgets."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import baseline
from agent.core.registry import build_workflow
from agent.nodes.generate import GenerateInput
from agent.nodes.baseline import BaselineGenerateNode
from agent.workflows.single_generate_long_output import LongOutputGenerate


class LongOutputTests(unittest.TestCase):
    def test_request_difference_and_original_unchanged(self):
        requests, emitted = [], []
        ctx = SimpleNamespace(
            llm=SimpleNamespace(baseline_model=lambda **kw: 'test-model',
                                chat=lambda req: requests.append(req)),
            budget=SimpleNamespace(timeout_s=lambda requested: min(requested, 920)),
            emit=lambda *args, **kw: emitted.append((args, kw)))
        task = SimpleNamespace(raw_prompt='  Prompt\n', prompt='Prompt',
                               raw_interface=' interface\n', interface='interface')
        inp = GenerateInput(task)
        BaselineGenerateNode().run(ctx, inp)
        LongOutputGenerate().run(ctx, inp)
        BaselineGenerateNode().run(ctx, inp)
        original, longer, after = requests
        expected = original.payload('unused')
        expected['max_tokens'] = 32768
        self.assertEqual(longer.payload('unused'), expected)
        self.assertEqual(longer.timeout_s, 900)
        self.assertEqual(original.public_dict(), after.public_dict())
        self.assertEqual(baseline.MAX_TOKENS, 16384)
        self.assertEqual(baseline.TIMEOUT_S, 840)
        self.assertEqual(build_workflow('single_generate').generate.__class__, BaselineGenerateNode)
        self.assertEqual(build_workflow('single_generate_long_output').extract.__class__,
                         build_workflow('single_generate').extract.__class__)
        self.assertTrue(any(e[0] == ('experiment_override',) for e in emitted))

    def test_timeout_respects_remaining_budget(self):
        requests = []
        ctx = SimpleNamespace(
            llm=SimpleNamespace(baseline_model=lambda **kw: 'test-model',
                                chat=lambda req: requests.append(req)),
            budget=SimpleNamespace(timeout_s=lambda requested: min(requested, 17)),
            emit=lambda *args, **kw: None)
        task = SimpleNamespace(raw_prompt='Prompt', prompt='Prompt',
                               raw_interface=None, interface='')
        LongOutputGenerate().run(ctx, GenerateInput(task))
        self.assertEqual(requests[0].timeout_s, 17)


if __name__ == '__main__':
    unittest.main()
