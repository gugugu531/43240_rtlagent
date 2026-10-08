"""Run-local reuse with exact task/source/configuration/tool identity."""
from dataclasses import dataclass


@dataclass(frozen=True)
class CheckKey:
    task_fingerprint: str
    code_hash: str
    kind: str
    config_fingerprint: str
    tool_fingerprint: str


class CheckCache:
    def __init__(self):
        self._results = {}

    def get(self, key: CheckKey | None):
        return self._results.get(key) if key else None

    def put(self, key: CheckKey | None, result):
        if key and (result.status == 'passed' or result.classify() == 'code'):
            self._results[key] = result
