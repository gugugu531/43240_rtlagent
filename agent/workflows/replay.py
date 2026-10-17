"""Explicit solver-only initial checkpoints for controlled repair experiments."""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path

from agent.core.model import ModelReply, ModelUsage, _thaw
from agent.core.state import CheckResult
from agent.core.extraction import ExtractInput
from agent.core.replay_contract import InitialReplayContract
from agent.core.components import describe_component, describe_value
from agent.recording.artifacts import atomic_write_json
from agent.services.replay_validation import validate_initial_requests

ROOT = Path(__file__).resolve().parents[2]
FIELDS = {'schema_version', 'task_hash', 'runtime_hashes', 'tool_identity', 'service', 'reply', 'requests',
          'checks', 'extraction_status', 'initial_wall_s', 'tokens', 'stop_reason', 'sha256',
          'initial_contract', 'candidate', 'source_assembly_sha256'}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def task_hash(task):
    return digest(dict(prompt=task.prompt, interface=task.interface, top=task.top))


def runtime_hashes(root=ROOT):
    root = Path(root)
    files = [p for p in (root / 'agent').rglob('*') if p.is_file() and p.suffix in ('.py', '.md')]
    files += [root / name for name in ('baseline.py', 'run.sh', 'requirements.txt', 'manifest.json')]
    files += list((root / 'skill').glob('rtl_cards*'))
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}


def component_contract(component):
    """Semantic construction identity, independent of assembly-local IDs."""
    seen = {}

    def describe(value, path):
        if value is None:
            return None
        if id(value) in seen:
            return dict(reference=seen[id(value)])
        seen[id(value)] = path
        spec = describe_component(value)
        declarations = getattr(type(value), 'dependencies', {})
        parameters = {key: describe_value(item) for key, item in spec.parameters.items()
                      if key not in declarations}
        dependencies = {}
        for name in declarations:
            dependency = getattr(value, name)
            child_path = f'{path}.dependencies.{name}'
            dependencies[name] = ([describe(item, f'{child_path}[{index}]')
                                  for index, item in enumerate(dependency)]
                                 if isinstance(dependency, (tuple, list)) else describe(dependency, child_path))
        return dict(target=f'{type(value).__module__}:{type(value).__qualname__}',
                    parameters=parameters, dependencies=dependencies)

    return describe(component, '$')


def initial_contract(ctx, kinds, *, importing=False):
    declaration = ctx.initial_replay_contract
    if not isinstance(declaration, InitialReplayContract):
        raise ValueError('workflow does not declare an initial replay contract')
    extract_node, check_nodes = declaration.extract_node, declaration.check_nodes
    providers = {}
    for node in check_nodes:
        if node is not None:
            tool = getattr(node, 'tool', None)
            if tool is None or tool.check_kind not in kinds:
                continue
            if importing and not callable(type(tool).__dict__.get('replay_identity')):
                raise ValueError('initial check provider does not declare replay identity')
            providers[tool.check_kind] = dict(provider=component_contract(tool),
                fingerprint=ctx.checks.replay_provider(tool)["fingerprint"])
    if any(kind not in providers for kind in kinds):
        raise ValueError('initial check provider is unavailable')
    return dict(request_policy=declaration.request_policy, extractor=component_contract(extract_node),
                checks={kind: providers[kind] for kind in sorted(set(kinds))})


def save_initial(path, ctx, reply, result, checks, stop_reason, identity):
    import time
    service = ctx.llm.backend.describe()
    data = dict(schema_version=2, task_hash=task_hash(ctx.task), runtime_hashes=runtime_hashes(),
        tool_identity=identity, service=dict(service), requests=ctx.llm.requests,
        source_assembly_sha256=ctx.configuration.get("assembly_sha256"),
        initial_contract=initial_contract(ctx, [c.kind for c in checks]),
        candidate=(dict(id=result.candidate.id, code_hash=result.candidate.code_hash)
                   if result.candidate else None),
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


def load_initial(path, ctx):
    path = Path(path)
    if path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError('initial checkpoint exceeds size limit')
    data = json.loads(path.read_text())
    if set(data) != FIELDS or data['schema_version'] != 2:
        raise ValueError('initial checkpoint contains unsupported fields')
    checksum = data.pop('sha256')
    if digest(data) != checksum or data['task_hash'] != task_hash(ctx.task):
        raise ValueError('initial checkpoint identity differs')
    if data['runtime_hashes'] != runtime_hashes() or data['service'] != dict(ctx.llm.backend.describe()):
        raise ValueError('initial runtime or model service differs')
    elapsed = data['initial_wall_s']
    if type(elapsed) not in (int, float) or not math.isfinite(elapsed) or elapsed < 0:
        raise ValueError('invalid initial time')
    ctx.checks.restore_identity(data['tool_identity'])
    expected_contract = initial_contract(ctx, [c['kind'] for c in data['checks']], importing=True)
    if data['initial_contract'] != expected_contract:
        raise ValueError('initial extractor or check provider differs')
    expected_ids = validate_initial_requests(ctx.task, data['requests'], data['tokens'],
                                             policy=expected_contract['request_policy'])
    ctx.llm.tokens.import_initial(data['tokens'])
    if ctx.llm.tokens.snapshot()['blocked'] and callable(getattr(ctx.llm.counter, 'mark_mismatch', None)):
        ctx.llm.counter.mark_mismatch()
    ctx.llm.recorder.resume_call_sequence(len(expected_ids))
    original = dict(data['reply'])
    if set(original) != {'call_id', 'content', 'model', 'request_id', 'finish_reason', 'usage', 'elapsed_s'}:
        raise ValueError('unsupported replay reply fields')
    original['usage'] = ModelUsage(**original['usage'])
    reply = ModelReply(**original)
    result = ctx.execute(ctx.initial_replay_contract.extract_node,
                         ExtractInput(reply, 1, source_stage='initial_replay'))
    if result.extraction.status != data['extraction_status']:
        raise ValueError('initial extraction differs')
    candidate = (dict(id=result.candidate.id, code_hash=result.candidate.code_hash)
                 if result.candidate else None)
    if candidate != data['candidate']:
        raise ValueError('initial candidate content differs')
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
    ctx.mark_initial_replay_validated()
    return data, reply, result, checks
