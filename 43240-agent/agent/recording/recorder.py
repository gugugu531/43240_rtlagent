"""Mandatory competition JSONL trace plus full bodies that the trace cannot hold.

Each fact is written once: events go to trace.jsonl; records/<run_id>/ keeps only
the task text, model requests and responses, candidate code and process output.
"""
from __future__ import annotations
from dataclasses import dataclass
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
import json
import os
import tempfile
import time
import uuid
import warnings
from typing import Literal
from agent.core.model import ArtifactRef, ModelCallError
from agent.recording.redaction import Redactor


class RecordingError(OSError):
    """The required trace could not be persisted."""


@dataclass(frozen=True)
class RecordingConfig:
    level: Literal['basic', 'full'] = 'full'
    root: Path | None = None

    def __post_init__(self):
        if self.level not in ('basic', 'full'):
            raise ValueError('recording level must be basic or full')


@dataclass(frozen=True)
class CallHandle:
    call_id: str
    run_id: str


class RunRecorder:
    def __init__(self, output_dir, config: RecordingConfig | None = None, *, secrets=(), run_id=None):
        self.config = config or RecordingConfig()
        self.run_id = run_id or uuid.uuid4().hex
        self.redactor = Redactor(secrets)
        self._seq = self._call_seq = 0
        self._closed = False
        self._calls = {}
        self._execution = ContextVar('node_execution', default=None)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        # Failure here is an infrastructure error, never a silent optional failure.
        self._trace = (self.output_dir / 'trace.jsonl').open('w', encoding='utf-8')
        self.run_dir = record_dir(self.output_dir, self.config, self.run_id)
        self.write_event('run', 'recording', level=self.config.level,
                         record_dir=str(self.run_dir) if self.config.level == 'full' else None)

    def write_event(self, tool: str, event: str = 'result', **fields):
        self._seq += 1
        execution_id = self._execution.get()
        if execution_id:
            fields.setdefault('execution_id', execution_id)
        data = self.redactor.copy(fields)
        if 'excerpt' in data:
            data['excerpt'] = str(data['excerpt'])[:2000]
        data.update(run_id=self.run_id, seq=self._seq, ts=round(time.time(), 3), tool=tool, event=event)
        try:
            self._trace.write(json.dumps(data, ensure_ascii=False) + '\n')
            self._trace.flush()
        except OSError as exc:
            raise RecordingError('required trace write failed') from exc

    def _artifact(self, path: str, value, *, text=False):
        if self.config.level != 'full':
            return None
        target = self.run_dir / path
        temp = None
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            data = self.redactor.copy(value)
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=target.parent,
                                             delete=False) as fh:
                temp = fh.name
                fh.write(data if text else json.dumps(data, ensure_ascii=False, indent=2))
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(temp, target)
            return ArtifactRef(self.run_id, path)
        except (OSError, TypeError, ValueError) as exc:
            # Do not report exception text: file paths can themselves contain secrets.
            try:
                warnings.warn(f'detailed recording unavailable ({type(exc).__name__})', RuntimeWarning)
            except RuntimeWarning:
                pass
            self.write_event('recording', 'warning', artifact=path, error=type(exc).__name__, rc=1)
            return None
        finally:
            if temp:
                try:
                    os.unlink(temp)
                except OSError:
                    pass

    def record_metadata(self, **metadata):
        self.write_event('run', 'metadata', **metadata)

    def begin_call(self, request, service_info, *, http_payload=None):
        self._call_seq += 1
        call = CallHandle(f'm{self._call_seq:03d}', self.run_id)
        self._calls[call.call_id] = dict(execution_id=self._execution.get())
        self.write_event('llm', 'started', call_id=call.call_id, purpose=request.purpose,
                         service=service_info)
        record = request.public_dict() if http_payload is None else dict(
            request=http_payload, timeout_s=request.timeout_s,
            purpose=request.purpose, profile=request.profile)
        self._artifact(f'calls/{call.call_id}/request.json', record)
        return call

    def record_response(self, call, response, body=None):
        """Keep one copy of the reply: parsed JSON when valid, otherwise the raw text."""
        self._calls[call.call_id]['status_code'] = response.status_code
        if body is not None:
            return self._artifact(f'calls/{call.call_id}/response.json', body)
        raw = response.raw_text if response.raw_text is not None else response.mock_content
        if raw is None:
            return None
        return self._artifact(f'calls/{call.call_id}/response.txt', raw, text=True)

    def finish_call(self, call, result):
        failed = isinstance(result, ModelCallError)
        data = result.public_dict()
        data['execution_id'] = self._calls[call.call_id]['execution_id']
        data.setdefault('status_code', self._calls[call.call_id].get('status_code'))
        self.write_event('llm', 'failed' if failed else 'succeeded', rc=1 if failed else 0, **data)

    def record_extraction(self, call_id, extraction, candidate_id=None):
        self.write_event('extract', 'result', call_id=call_id, candidate_id=candidate_id,
                         **extraction.trace_dict())

    @contextmanager
    def execution_scope(self, execution_id):
        token = self._execution.set(execution_id)
        try:
            yield
        finally:
            self._execution.reset(token)

    def record_task(self, task):
        self._artifact('task.json', dict(**task.public_dict(), prompt=task.prompt, interface=task.interface))

    def record_node(self, execution):
        # Start carries identity and input; the end refers back by execution_id.
        if execution.status == 'started':
            self.write_event('node', 'started', execution_id=execution.id,
                             parent_execution_id=execution.parent_id,
                             component=dict(execution.component), input=execution.input)
        elif execution.status == 'failed':
            self.write_event('node', 'failed', execution_id=execution.id, elapsed_s=execution.elapsed_s,
                             error_type=execution.error_type, error_message=execution.error_message)
        else:
            self.write_event('node', execution.status, execution_id=execution.id,
                             elapsed_s=execution.elapsed_s, output=execution.output)

    def record_candidate(self, candidate):
        self._artifact(f'candidates/{candidate.id}.v', candidate.code, text=True)
        self.write_event('candidate', 'create', **candidate.trace_dict())

    def record_selection(self, candidate, *, reason):
        self.write_event('candidate', 'select', candidate_id=candidate.id, reason=reason)

    def record_check(self, result):
        self.write_event('check_interface' if result.kind == 'interface' else result.kind, 'result',
                         **result.public_dict())

    def close(self):
        if self._closed:
            return
        self._closed = True
        self._trace.close()


def record_dir(output_dir, config: RecordingConfig, run_id: str) -> Path:
    return (Path(config.root) if config.root else Path(output_dir) / 'records') / run_id
