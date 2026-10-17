"""Managed RTL checks: budget, exact reuse, evidence IDs and publication."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import time

from agent.core.components import describe_component
from agent.core.state import CheckResult
from agent.core.tool import CheckOutcome
from agent.runtime.validation import validate_component_value
from agent.runtime.check_cache import CheckCache, CheckKey


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


class CheckService:
    def __init__(self, budget, allocate_id, publish, *, task, emit, tool_context):
        self._budget, self._allocate_id, self._publish = budget, allocate_id, publish
        self._task = task
        self._tool_context = tool_context
        self._emit = emit
        self._task_hash = digest([task.id, task.top, task.prompt, task.interface])
        self.cache = CheckCache()
        self._identity = None

    def fingerprint(self):
        toolchain = self._tool_context.toolchain()
        function = getattr(toolchain, 'fingerprint', None)
        return function() if callable(function) else function

    def identify(self):
        self.fingerprint()
        toolchain = self._tool_context.toolchain()
        probe = getattr(toolchain, 'identify', None)
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
        toolchain = self._tool_context.toolchain()
        function = getattr(toolchain, 'replay_fingerprint', None)
        return function() if callable(function) else self.fingerprint()

    def replay_provider(self, tool):
        identity = type(tool).__dict__.get('replay_identity')
        fingerprint = identity(tool, self._tool_context) if callable(identity) else None
        return dict(component=describe_component(tool).public_dict(), fingerprint=fingerprint)

    def _cache_identity(self, tool):
        # A subclass must opt in itself: an inherited fingerprint may omit
        # behavior or parameters introduced by the new implementation.
        identity = type(tool).__dict__.get('cache_identity')
        value = identity(tool, self._tool_context) if callable(identity) else None
        return value if isinstance(value, str) and value else None

    @staticmethod
    def _cache_request(tool, input):
        request = type(tool).__dict__.get('cache_request')
        value = request(tool, input) if callable(request) else None
        if value is None:
            return None
        try:
            json.dumps(value, sort_keys=True, allow_nan=False)
        except (TypeError, ValueError):
            return None
        return value

    @staticmethod
    def _provider_key(tool, fingerprint):
        # The toolchain alone does not identify an injected Python Tool. A run
        # may use distinct implementations or parameters for the same check kind.
        return digest([describe_component(tool).public_dict(), fingerprint])

    def restore_identity(self, identity):
        if identity.get('fingerprint') != self.replay_fingerprint():
            raise ValueError('replay tool identity changed')
        self._identity = identity
        self._emit('tool_identity_restored', identity=identity)

    def _reuse(self, key, candidate):
        old = self.cache.get(key)
        if old is None:
            return None
        # Reuse the evidence, not its ID: this candidate gets a new check
        # record linked to the original, with no claimed tool execution.
        result = replace(old, id=self._allocate_id(), candidate_id=candidate.id, elapsed_s=0.0,
                         details=dict(old.details, reused_from_check_id=old.id, executed=False))
        self._publish(result)
        return result

    def check(self, tool, input, *, candidate, timeout_s=None, minimum_s=0.0):
        kind = tool.check_kind
        if kind == 'interface':
            if timeout_s is not None:
                raise ValueError('interface check does not accept timeout')
            validate_component_value(tool, 'input_type', input)
            started = time.monotonic()
            identity = self._cache_identity(tool)
            request = self._cache_request(tool, input) if identity else None
            key = (CheckKey(digest([self._task.id, self._task.top, self._task.prompt,
                                   self._task.interface]), candidate.code_hash, 'interface',
                            digest(['interface-v1', request]), self._provider_key(tool, identity))
                   if identity and request is not None else None)
            reused = self._reuse(key, candidate)
            if reused:
                return reused
            outcome = tool.run(self._tool_context, input)
            validate_component_value(tool, 'output_type', outcome)
            if not isinstance(outcome, CheckOutcome):
                raise TypeError('check tool must return CheckOutcome')
            check = self._publish_outcome(self._allocate_id(), candidate, kind, outcome,
                                          elapsed_override=time.monotonic() - started)
            self.cache.put(key, check)
            return check

        # Budget is checked before cache lookup, as in the original service.
        timeout = self._budget.timeout_s(timeout_s, minimum_s)
        validate_component_value(tool, 'input_type', input)
        check_id = None
        started = time.monotonic()
        try:
            fingerprint = self._cache_identity(tool)
            request = self._cache_request(tool, input) if fingerprint else None
            parameters = [self._task.top, timeout_s, request]
            key = (CheckKey(self._task_hash, candidate.code_hash, kind, digest(parameters),
                            self._provider_key(tool, fingerprint))
                   if fingerprint and request is not None and self._task_hash else None)
            reused = self._reuse(key, candidate)
            if reused:
                return reused
            check_id = self._allocate_id()
            self._emit('check_started', check_id=check_id, candidate_id=candidate.id, kind=kind,
                       executed=True)
            outcome = tool.run(self._tool_context.with_timeout(timeout), input)
            validate_component_value(tool, 'output_type', outcome)
            if not isinstance(outcome, CheckOutcome):
                raise TypeError('check tool must return CheckOutcome')
        except Exception as exc:
            check = CheckResult(check_id or self._allocate_id(), candidate.id, kind, 'error',
                                f'check service failed ({type(exc).__name__})', rc=1,
                                elapsed_s=time.monotonic() - started,
                                details={'error_type': type(exc).__name__, 'failure_kind': 'environment',
                                         'executed': check_id is not None})
            self._publish(check)
            return check
        details = dict(outcome.details)
        diagnostic_tool = details.get('diagnostic_tool')
        details['tool_version'] = details.get('tool_version') or (self._identity or {}).get(
            'tools', {}).get(diagnostic_tool, {}).get('version')
        outcome = replace(outcome, details=details)
        check = self._publish_outcome(check_id, candidate, kind, outcome)
        self.cache.put(key, check)
        return check

    def _publish_outcome(self, identity, candidate, kind, outcome, *, elapsed_override=None):
        # Tools report outcomes only; the runtime adds candidate identity and
        # publishes exactly once at this boundary.
        check = CheckResult(identity, candidate.id, kind, outcome.status, outcome.summary,
                            blocking=outcome.blocking, rc=outcome.rc,
                            elapsed_s=outcome.elapsed_s if elapsed_override is None else elapsed_override,
                            command=outcome.command, details=dict(outcome.details, executed=True),
                            log_paths=outcome.log_paths, work_dir=outcome.work_dir)
        self._publish(check)
        return check
