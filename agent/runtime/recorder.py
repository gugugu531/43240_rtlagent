"""Local JSONL evidence with context-local span ancestry."""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import time
import uuid

from agent.runtime.redaction import Redactor

_span = ContextVar("record_span", default=None)


def serializable(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"not serializable: {type(value).__name__}")


class Recorder:
    def __init__(self, output_dir, *, level="full", root=None, secrets=()):
        self.run_id = uuid.uuid4().hex
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.level = level
        self.record_dir = (
            Path(root) if root else self.output_dir / "records"
        ) / self.run_id
        if level == "full":
            self.record_dir.mkdir(parents=True, exist_ok=True)
        self.redactor = Redactor(secrets)
        self.seq = 0
        # Preserve malformed external text as escapes; evidence must not fail
        # before the consumer can classify an invalid model/tool response.
        self._stream = (self.output_dir / "trace.jsonl").open(
            "w", encoding="utf-8", errors="backslashreplace"
        )

    def emit(self, tool, event, **fields):
        self.seq += 1
        fields.setdefault("rc", None)
        fields.setdefault("tokens_in", None)
        fields.setdefault("tokens_out", None)
        excerpt = str(fields.pop("excerpt", ""))
        fields["excerpt"] = excerpt.encode("utf-8", errors="backslashreplace")[:2048].decode(
            "utf-8", errors="ignore"
        )
        active = _span.get()
        # docs/API_CONTRACT.md asks for Unix seconds; keep an ISO copy for
        # human-readable logs and the local viewer.
        now = time.time()
        row = dict(
            run_id=self.run_id,
            seq=self.seq,
            ts=now,
            ts_iso=datetime.fromtimestamp(now, timezone.utc).isoformat(),
            tool=tool,
            event=event,
            span_id=active[0] if active else None,
            parent_span_id=active[1] if active else None,
            **fields,
        )
        clean = self.redactor.copy(json.loads(json.dumps(row, default=serializable)))
        self._stream.write(
            json.dumps(clean, ensure_ascii=False, allow_nan=False) + "\n"
        )
        self._stream.flush()

    @contextmanager
    def scope(self):
        """Assign ancestry without emitting a second call lifecycle."""
        parent = _span.get()
        token = _span.set((uuid.uuid4().hex, parent[0] if parent else None))
        try:
            yield
        finally:
            _span.reset(token)

    @contextmanager
    def span(self, tool, **fields):
        parent = _span.get()
        token = _span.set((uuid.uuid4().hex, parent[0] if parent else None))
        started = time.monotonic()
        try:
            self.emit(tool, "started", **fields)
            yield
        except BaseException as exc:
            self.emit(
                tool,
                "failed",
                elapsed_s=time.monotonic() - started,
                error_type=type(exc).__name__,
                error=str(exc),
                **fields,
            )
            raise
        else:
            self.emit(tool, "finished", elapsed_s=time.monotonic() - started, **fields)
        finally:
            _span.reset(token)

    def write_text(self, relative, text):
        if self.level != "full":
            return None
        return self._write_record(relative, self.redactor.copy(str(text)))

    def _write_record(self, relative, text):
        """Write already-sanitized content without altering its encoding."""
        if self.level != "full":
            return None
        path = (self.record_dir / relative).resolve()
        if not path.is_relative_to(self.record_dir.resolve()):
            raise ValueError("record path escapes run directory")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            text, encoding="utf-8", errors="backslashreplace"
        )
        return str(path)

    def write_json(self, relative, data):
        # Redact values before serialization; text redaction after json.dumps
        # can consume escape characters and corrupt the JSON document.
        return self._write_record(
            relative,
            json.dumps(
                self.redactor.copy(json.loads(json.dumps(data, default=serializable))),
                ensure_ascii=False,
                indent=2,
            ),
        )

    def close(self):
        self._stream.close()
