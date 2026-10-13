"""Explicit solver-only initial checkpoints for controlled repair experiments."""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path

from agent.core.model import ModelReply, ModelUsage, _thaw
from agent.core.state import CheckResult
from agent.nodes.extract import ExtractInput
from agent.recording.artifacts import atomic_write_json

ROOT = Path(__file__).resolve().parents[2]
FIELDS = {'schema_version', 'task_hash', 'runtime_hashes', 'tool_identity', 'service', 'reply', 'requests',
          'checks', 'extraction_status', 'initial_wall_s', 'tokens', 'stop_reason', 'sha256'}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def task_hash(task):
    return digest(dict(prompt=task.prompt, interface=task.interface, top=task.top))


def runtime_hashes(root=ROOT):
    root = Path(root)
    files = [p for p in (root / 'agent').rglob('*') if p.is_file() and p.suffix in ('.py', '.md')]
    files += [root / name for name in ('baseline.py', 'run.sh', 'requirements.txt')]
    files += list((root / 'skill').glob('rtl_cards*'))
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}


def save_initial(path, ctx, reply, result, checks, stop_reason, identity):
    import time
    service = ctx.llm.backend.describe()
    data = dict(schema_version=1, task_hash=task_hash(ctx.task), runtime_hashes=runtime_hashes(),
        tool_identity=identity, service=dict(service), requests=ctx.llm.requests,
        reply=dict(call_id=reply.call_id, content=reply.content, model=reply.model,
                   request_id=reply.request_id, finish_reason=reply.finish_reason,
                   usage=asdict(reply.usage), elapsed_s=reply.elapsed_s),
        checks=[dict(id=c.id, candidate_id=c.candidate_id, kind=c.kind, status=c.status,
                     summary=c.summary, blocking=c.blocking, rc=c.rc, elapsed_s=c.elapsed_s,
                     command=[list(x) for x in c.command], details=_thaw(c.details),
                     log_paths=list(c.log_paths), work_dir=c.work_dir) for c in checks],
        extraction_status=result.extraction.status, initial_wall_s=time.monotonic() - ctx.started_at,
        tokens=ctx.llm.tokens.snapshot(), stop_reason=stop_reason)
    data['sha256'] = digest(data)
    atomic_write_json(path, data)
    ctx.emit('initial_checkpoint', sha256=data['sha256'], path=str(path),
             initial_wall_s=data['initial_wall_s'], candidate_id=result.candidate.id if result.candidate else None)
    return data


def load_initial(path, ctx, extract_node):
    path = Path(path)
    if path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError('initial checkpoint exceeds size limit')
    data = json.loads(path.read_text())
    if set(data) != FIELDS or data['schema_version'] != 1:
        raise ValueError('initial checkpoint contains unsupported fields')
    checksum = data.pop('sha256')
    if digest(data) != checksum or data['task_hash'] != task_hash(ctx.task):
        raise ValueError('initial checkpoint identity differs')
    if data['runtime_hashes'] != runtime_hashes() or data['service'] != dict(ctx.llm.backend.describe()):
        raise ValueError('initial runtime or model service differs')
    elapsed = data['initial_wall_s']
    if type(elapsed) not in (int, float) or not math.isfinite(elapsed) or elapsed < 0:
        raise ValueError('invalid initial time')
    ctx.tools.restore_identity(data['tool_identity'])
    from agent.core.model import ModelRequest
    from agent.prompts.builder import assemble_messages
    expected, _ = assemble_messages(ctx.task, style='repair', use_skills=False)
    if not data['requests'] or len(data['requests']) != data['tokens']['calls']:
        raise ValueError('initial request accounting differs')
    for entry in data['requests']:
        if set(entry) != {'call_id', 'request'}:
            raise ValueError('unsupported initial request fields')
        request = ModelRequest(**entry['request'])
        if [dict(m) for m in request.messages] != expected or request.purpose != 'generate':
            raise ValueError('initial messages differ from scheme A')
    expected_ids = [f'm{i:03d}' for i in range(1, len(data['requests']) + 1)]
    if ([r['call_id'] for r in data['requests']] != expected_ids
            or sorted(data['tokens']['entries']) != expected_ids):
        raise ValueError('initial request IDs differ from accounting')
    ctx.llm.tokens.import_initial(data['tokens'])
    if ctx.llm.tokens.snapshot()['blocked'] and callable(getattr(ctx.llm.counter, 'mark_mismatch', None)):
        ctx.llm.counter.mark_mismatch()
    ctx.llm.recorder.resume_call_sequence(len(expected_ids))
    original = dict(data['reply'])
    if set(original) != {'call_id', 'content', 'model', 'request_id', 'finish_reason', 'usage', 'elapsed_s'}:
        raise ValueError('unsupported replay reply fields')
    original['usage'] = ModelUsage(**original['usage'])
    reply = ModelReply(**original)
    result = ctx.execute(extract_node, ExtractInput(reply, 1, source_stage='initial_replay'))
    if result.extraction.status != data['extraction_status']:
        raise ValueError('initial extraction differs')
    checks = []
    for saved in data['checks']:
        if result.candidate is None or saved['candidate_id'] != result.candidate.id:
            raise ValueError('check is not linked to initial candidate')
        values = dict(saved)
        values['id'] = ctx.new_check_id()
        values['details'] = dict(values['details'], executed=False, initial_check_id=saved['id'])
        check = CheckResult(**values)
        ctx.record_check(check)
        checks.append(check)
    ctx.budget.consume_previous(elapsed)
    ctx.emit('initial_replayed', sha256=checksum, initial_wall_s=elapsed,
             initial_calls=data['tokens']['calls'], original_stop_reason=data['stop_reason'],
             tokens=data['tokens'])
    return data, reply, result, checks
