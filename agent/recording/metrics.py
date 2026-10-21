"""Artifact-based metrics with explicit missing data and evidence references."""
from __future__ import annotations
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Protocol
import json


@dataclass(frozen=True)
class CompletedSample:
    task_id: str
    mode: str
    index: int
    output_dir: Path
    solve: dict = field(default_factory=dict)


@dataclass(frozen=True)
class MetricResult:
    name: str
    version: int
    status: str
    values: dict
    evidence: tuple[str, ...] = ()

    def __post_init__(self):
        if self.status not in ('ok', 'partial', 'unavailable', 'error', 'skipped'):
            raise ValueError('invalid metric status')

    def public_dict(self):
        return asdict(self)


class MetricCollector(Protocol):
    name: str
    version: int
    def collect(self, sample: CompletedSample) -> MetricResult: ...


def read_events(path):
    events, complete = [], True
    try:
        for line in Path(path).read_text().splitlines():
            if not line.strip(): continue
            try:
                row = json.loads(line)
                if not isinstance(row, dict): complete = False
                else: events.append(row)
            except ValueError: complete = False
    except (OSError, UnicodeError):
        complete = False
    return events, complete


class RuntimeMetric:
    name, version = 'runtime', 2

    def collect(self, sample):
        events, complete = read_events(sample.output_dir / 'trace.jsonl')
        supervision = next((x for x in reversed(events) if x.get('tool') == 'supervisor'), {})
        checks = [x for x in events if x.get('event') == 'result' and
                  all(key in x for key in ('check_id', 'candidate_id', 'kind', 'status'))]
        values = dict(solve_wall_s=sample.solve.get('wall_s'), status=sample.solve.get('status'),
                      stop_reason=supervision.get('stop_reason'),
                      node_attempts=sum(x.get('tool') == 'node' and x.get('event') == 'started' for x in events),
                      terminated_groups=supervision.get('terminated_groups'),
                      unreaped_pids=supervision.get('unreaped_pids'),
                      backend_inference_cancelled=supervision.get('backend_inference_cancelled'),
                      check_results=len(checks),
                      checks_executed=sum(x.get('details',{}).get('executed') is True for x in checks),
                      checks_unfinished=sum(x.get('event')=='check_started' and x.get('check_id') not in {r.get('check_id') for r in checks} for x in events),
                      node_wall_s_known=sum(x.get('elapsed_s',0) for x in events if x.get('tool')=='node' and x.get('event') in ('succeeded','failed')),
                      check_reused=sum(x.get('details', {}).get('executed') is False for x in checks))
        return MetricResult(self.name, self.version, 'ok' if complete else 'partial', values,
                            ('solve.json', 'trace.jsonl'))


class ModelMetric:
    name, version = 'model', 1

    def collect(self, sample):
        events, complete = read_events(sample.output_dir / 'trace.jsonl')
        calls = {}; legacy = 0
        for event in events:
            if event.get('tool') != 'llm': continue
            key = event.get('call_id')
            if key is None:
                legacy += 1; key = f'baseline_{legacy}'
            entry = calls.setdefault(key, {'started': False, 'ended': None})
            if event.get('event') == 'started': entry['started'] = True
            else: entry['ended'] = event
        ended = [c['ended'] for c in calls.values() if c['ended'] is not None]
        success = [e for e in ended if e.get('event') == 'succeeded' or
                   ('event' not in e and not e.get('error'))]
        failures = [e for e in ended if e not in success]
        unfinished = len(calls) - len(ended)
        values = dict(attempts=len(calls), succeeded=len(success), failed=len(failures), unfinished=unfinished,
                      truncated=sum(e.get('finish_reason', e.get('finish')) == 'length' for e in success),
                      retries_requested=sum(e.get('tool')=='workflow' and e.get('event')=='failure_decision'
                                             and e.get('action')=='retry_request' for e in events),
                      errors=[{'kind':e.get('kind'),'call_id':e.get('call_id')} for e in failures])
        # New traces record usage in a nested mapping.
        for field, key in [('prompt_tokens', 'prompt_tokens'), ('completion_tokens', 'completion_tokens')]:
            counts = [e.get('usage', {}).get(key, e.get('tokens_in' if key=='prompt_tokens' else 'tokens_out')) for e in success]
            known = [v for v in counts if type(v) is int and v >= 0]
            values[field] = dict(known_total=sum(known) if known else None, known_calls=len(known), unknown_calls=len(calls)-len(known))
        partial = unfinished or failures or any(v['unknown_calls'] for k,v in values.items() if k.endswith('_tokens'))
        accounting = next((e.get('snapshot') for e in reversed(events)
                           if e.get('tool') == 'tokens' and e.get('snapshot') is not None), None)
        if accounting is not None:
            values['accounting'] = accounting
        values['context'] = [dict(round=e.get('round'), count=e.get('count'), pieces=e.get('pieces'),
                                  messages_sha256=e.get('messages_sha256'))
                             for e in events if e.get('event') == 'context_assembly']
        return MetricResult(self.name, self.version, 'ok' if complete and not partial else 'partial', values,
                            ('trace.jsonl',))


def collect_metrics(sample, collectors):
    results = []
    for collector in collectors:
        try:
            result = collector.collect(sample)
            if not isinstance(result, MetricResult): raise TypeError('metric must return MetricResult')
        except Exception as exc:
            result = MetricResult(collector.name, collector.version, 'error', {'error_type': type(exc).__name__})
        results.append(result)
    return tuple(results)
