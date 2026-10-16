"""Current upstream gain formula, reusing the protected judge aggregation."""
from __future__ import annotations
import importlib.util
import json
from pathlib import Path

GAIN_FULL_MARK = 0.6


def normalized_gain(agent: float, baseline: float) -> tuple[float, float]:
    if baseline >= 1.0:
        return 1.0, 40.0
    gain = (agent - baseline) / (1.0 - baseline)
    return gain, max(0.0, min(40.0, 40.0 * gain / GAIN_FULL_MARK))


def score_results(results_dir: str) -> dict:
    path = Path(__file__).resolve().parents[3] / 'selftest/score.py'
    spec = importlib.util.spec_from_file_location('official_score_aggregation', path)
    official = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(official)
    data = official.collect(results_dir)
    report = {'modes': {mode: official.summarize(rows) for mode, rows in sorted(data.items())},
              'gain_full_mark': GAIN_FULL_MARK}
    agent, baseline = report['modes'].get('agent'), report['modes'].get('baseline')
    if agent:
        report['capability_score'] = round(30 * agent['set_score'], 2)
    if agent and baseline:
        def valid(mode):
            pairs = set()
            for path in Path(results_dir).glob(f'{mode}.*.s*.json'):
                try:
                    row = json.loads(path.read_text())
                    sample = int(path.name.rsplit('.s', 1)[1][:-5])
                    if not row.get('tool_error'):
                        pairs.add((row.get('task_id', 'unknown'), sample))
                except (OSError, ValueError, TypeError, AttributeError):
                    continue
            return pairs
        comparable = bool(valid('agent')) and valid('agent') == valid('baseline')
        report['paired_coverage'] = comparable
        report.update(gain_g=None, gain_score=None, gain_ratio=None)
        if comparable:
            a, b = agent['set_score'], baseline['set_score']
            gain, score = normalized_gain(a, b)
            report.update(gain_g=round(gain, 4), gain_score=round(score, 2),
                          gain_ratio=round(a / b, 4) if b else None)
    return report
