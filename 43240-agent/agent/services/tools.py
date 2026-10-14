"""Record checks and exact run-local reuse; decisions remain in workflows."""
from __future__ import annotations
from dataclasses import replace
import hashlib
import json
import time
from agent.core.state import CheckResult
from agent.core.interface import check_interface_result
from agent.services.vivado import RtlToolchain
from agent.services.check_cache import CheckCache, CheckKey


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


class ToolService:
    def __init__(self, budget, allocate_id, publish, *, toolchain_factory=RtlToolchain,
                 task=None, emit=None):
        self._budget, self._allocate_id, self._publish = budget, allocate_id, publish
        self._factory, self._toolchain = toolchain_factory, None
        self._emit = emit or (lambda *args, **kwargs: None)
        self._task_hash = digest([task.id, task.top, task.prompt, task.interface]) if task else ''
        self.cache = CheckCache()
        self._identity = None

    def fingerprint(self):
        if self._toolchain is None:
            self._toolchain = self._factory()
        function = getattr(self._toolchain, 'fingerprint', None)
        return function() if callable(function) else function

    def identify(self):
        self.fingerprint()
        probe = getattr(self._toolchain, 'identify', None)
        self._emit('tool_identity_started')
        started = time.monotonic()
        try:
            self._identity = (probe(timeout_s=self._budget.timeout_s(5.0)) if callable(probe)
                              else dict(fingerprint=self.replay_fingerprint(), tools={}, elapsed_s=0))
        except OSError as exc:
            self._identity = dict(fingerprint=self.replay_fingerprint(), tools={}, elapsed_s=0,
                                  status='unavailable', error_type=type(exc).__name__)
        self._identity['elapsed_s'] = time.monotonic() - started
        self._emit('tool_identity', identity=self._identity)
        return self._identity

    def replay_fingerprint(self):
        self.fingerprint()
        function = getattr(self._toolchain, 'replay_fingerprint', None)
        return function() if callable(function) else self.fingerprint()

    def restore_identity(self, identity):
        if identity.get('fingerprint') != self.replay_fingerprint():
            raise ValueError('replay tool identity changed')
        self._identity = identity
        self._emit('tool_identity_restored', identity=identity)

    def _reuse(self, key, candidate):
        old = self.cache.get(key)
        if old is None:
            return None
        result = replace(old, id=self._allocate_id(), candidate_id=candidate.id, elapsed_s=0.0,
                         details=dict(old.details, reused_from_check_id=old.id, executed=False))
        self._publish(result)
        return result

    def check_interface(self, task, candidate):
        start = time.monotonic()
        key = CheckKey(digest([task.id, task.top, task.prompt, task.interface]), candidate.code_hash,
                       'interface', digest('interface-v1'), digest('python-interface-v1'))
        reused = self._reuse(key, candidate)
        if reused:
            return reused
        result = check_interface_result(candidate.code, task.interface, task.prompt)
        status = {'ok': 'passed', 'mismatch': 'failed', 'advisory': 'failed',
                  'skipped': 'skipped', 'parse_error': 'error'}[result.status]
        check = CheckResult(self._allocate_id(), candidate.id, 'interface', status,
                            result.summary, blocking=result.blocking, rc=result.rc,
                            elapsed_s=time.monotonic() - start,
                            details=dict(result.trace_dict(), executed=True))
        self.cache.put(key, check)
        self._publish(check)
        return check

    def lint(self, candidate, top, *, timeout_s=300.0):
        return self._run('lint', candidate, top, timeout_s)

    def synth(self, candidate, top, *, timeout_s=900.0):
        return self._run('synth', candidate, top, timeout_s)

    def _run(self, kind, candidate, top, timeout_s):
        timeout = self._budget.timeout_s(timeout_s)
        check_id = None
        start = time.monotonic()
        try:
            if self._toolchain is None:
                self._toolchain = self._factory()
            fingerprint = getattr(self._toolchain, 'fingerprint', None)
            fingerprint = fingerprint() if callable(fingerprint) else fingerprint
            key = (CheckKey(self._task_hash, candidate.code_hash, kind, digest([top, timeout_s]),
                            str(fingerprint)) if fingerprint and self._task_hash else None)
            reused = self._reuse(key, candidate)
            if reused:
                return reused
            check_id = self._allocate_id()
            self._emit('check_started', check_id=check_id, candidate_id=candidate.id, kind=kind,
                       executed=True)
            result = getattr(self._toolchain, kind)(candidate.code, top, timeout_s=timeout)
        except Exception as exc:
            check = CheckResult(check_id or self._allocate_id(), candidate.id, kind, 'error',
                                f'check service failed ({type(exc).__name__})', rc=1,
                                elapsed_s=time.monotonic() - start,
                                details={'error_type': type(exc).__name__, 'failure_kind': 'environment',
                                         'executed': check_id is not None})
            self._publish(check)
            return check
        check = CheckResult(check_id, candidate.id, kind,
                            'passed' if result.status == 'ok' else result.status,
                            result.summary, blocking=result.status == 'failed' and result.failure_kind == 'code',
                            rc=result.rc, elapsed_s=result.elapsed_s, command=result.command,
                            details={**result.details, 'failure_kind': result.failure_kind, 'executed': True,
                                     'diagnostic_tool': result.diagnostic_tool,
                                     'tool_version': result.tool_version or (self._identity or {}).get('tools', {}).get(
                                         result.diagnostic_tool, {}).get('version')},
                            log_paths=result.log_paths, work_dir=result.work_dir)
        self.cache.put(key, check)
        self._publish(check)
        return check
