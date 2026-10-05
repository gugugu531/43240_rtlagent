"""Run-local evidence and mandatory competition JSONL trace."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import json
import os
import tempfile
import time
import uuid
import warnings
from typing import Literal
from ..core.model import ArtifactRef, ModelCallError
from .redaction import Redactor


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
    def __init__(self, output_dir, config: RecordingConfig | None = None, *, secrets=()):
        self.config = config or RecordingConfig()
        self.run_id = uuid.uuid4().hex
        self.redactor = Redactor(secrets)
        self._seq = self._call_seq = 0
        self._incomplete = False
        self._closed = False
        self._calls = {}
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        # Failure here is an infrastructure error, never a silent optional failure.
        self._trace = (self.output_dir / 'trace.jsonl').open('w', encoding='utf-8')
        self.run_dir = (Path(self.config.root) if self.config.root else self.output_dir / 'records') / self.run_id
        self._run = dict(run_id=self.run_id, level=self.config.level, status='started',
                         started_at=time.time(), recording_incomplete=False, calls=self._calls)
        self.write_event('run', 'recording', level=self.config.level,
                         record_dir=str(self.run_dir) if self.config.level == 'full' else None)
        self._save_run()

    def write_event(self, tool: str, event: str = 'result', **fields):
        self._seq += 1
        data = self.redactor.copy(fields)
        if 'excerpt' in data:
            data['excerpt'] = str(data['excerpt'])[:2000]
        data.update(schema_version=2, run_id=self.run_id, seq=self._seq,
                    ts=round(time.time(), 3), tool=tool, event=event)
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
            self._incomplete = True
            self._run['recording_incomplete'] = True
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

    def _save_run(self):
        self._artifact('run.json', self._run)

    def record_metadata(self, **metadata):
        self._run['metadata'] = metadata
        self.write_event('run', 'metadata', **metadata)
        self._save_run()

    def begin_call(self, request, service_info):
        self._call_seq += 1
        call = CallHandle(f'm{self._call_seq:03d}', self.run_id)
        self._calls[call.call_id] = dict(status='started', purpose=request.purpose)
        self.write_event('llm', 'started', call_id=call.call_id, purpose=request.purpose,
                         service=service_info)
        self._artifact(f'calls/{call.call_id}/request.json',
                       dict(service=service_info, request=request.public_dict()))
        self._save_run()
        return call

    def record_response(self, call, response):
        self._calls[call.call_id].update(status_code=response.status_code, elapsed_s=response.elapsed_s)
        if response.raw_text is None:
            return None
        return self._artifact(f'calls/{call.call_id}/response.txt', response.raw_text, text=True)

    def record_parsed_response(self, call, body):
        return self._artifact(f'calls/{call.call_id}/response.json', body)

    def finish_call(self, call, result):
        failed = isinstance(result, ModelCallError)
        data = result.public_dict()
        data.setdefault('status_code', self._calls[call.call_id].get('status_code'))
        self._calls[call.call_id].update(status='failed' if failed else 'succeeded', **data)
        if not failed:
            self._artifact(f'calls/{call.call_id}/content.txt', result.content, text=True)
        self._artifact(f'calls/{call.call_id}/result.json', dict(status='failed' if failed else 'succeeded', **data))
        self._save_run()
        self.write_event('llm', 'failed' if failed else 'succeeded', rc=1 if failed else 0, **data)

    def record_extraction(self, call_id, extraction, candidate_id=None):
        data = dict(call_id=call_id, candidate_id=candidate_id, **extraction.trace_dict())
        self._artifact(f'calls/{call_id}/extraction.json', data)
        self.write_event('extract', 'result', **data)

    def close(self):
        if self._closed:
            return
        self._run.update(status='closed', finished_at=time.time(), recording_incomplete=self._incomplete)
        try:
            self._save_run()
        finally:
            self._closed = True
            self._trace.close()
