"""Read the public workflow event stream while its task directory still exists."""

import json
import math
from pathlib import Path
import threading


def _finite(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("event numbers must be finite")
    return number


class RunFeed:
    def __init__(self):
        self._lock = threading.Lock()
        self._path = None
        self._offset = 0
        self._events = []
        self.error = None

    def attach(self, directory):
        with self._lock:
            self._path = Path(directory) / "live.jsonl"

    def _read(self, final=False):
        if self._path is None:
            return
        try:
            with self._path.open("rb") as stream:
                stream.seek(self._offset)
                for line in stream:
                    if not line.endswith(b"\n"):
                        # The writer may still be flushing this line. Retry at
                        # the same byte offset on the next poll.
                        if final:
                            self.error = "最后一条流程事件未写完。"
                        break
                    self._offset += len(line)
                    try:
                        event = json.loads(line, parse_float=_finite, parse_constant=_finite)
                        if not isinstance(event, dict) or type(event.get("v")) is not int or event["v"] != 1:
                            raise ValueError("unknown event schema")
                        if not isinstance(event.get("type"), str):
                            raise ValueError("missing event type")
                    except (ValueError, RecursionError):
                        self.error = "部分流程事件格式无效。"
                        continue
                    self._events.append(event)
        except FileNotFoundError:
            pass  # The agent creates its journal after reading the configuration.
        except OSError:
            self.error = "暂时无法读取流程记录。"

    def finish(self, *, baseline=False):
        # Drain before TemporaryDirectory is removed, even with no browsers.
        with self._lock:
            self._read(final=True)
            self._path = None
            if not baseline and not any(e["type"] == "run_end" for e in self._events):
                self.error = self.error or "求解已结束，缺少流程结束记录。"

    def page(self, after):
        with self._lock:
            self._read()
            start = min(after, len(self._events))
            cursor = min(start + 96, len(self._events))
            return dict(events=self._events[start:cursor], cursor=cursor,
                        more=cursor < len(self._events), error=self.error)

    def discard(self):
        with self._lock:
            self._path = None
            self._events.clear()
