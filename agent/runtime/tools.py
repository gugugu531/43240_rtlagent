"""Restricted tool capabilities and one lazy toolchain shared by the run."""
from __future__ import annotations
from pathlib import Path
from dataclasses import replace
import time
from agent.core.budget import BudgetExhausted
from agent.recording.artifacts import atomic_write_json, atomic_write_text


class ToolArtifacts:
    def __init__(self, root: Path):
        self._root = Path(root).resolve()

    def _path(self, name: str) -> Path:
        if Path(name).is_absolute():
            raise ValueError('tool artifact must be a relative file within artifacts')
        path = (self._root / name).resolve()
        if not path.is_relative_to(self._root) or path == self._root:
            raise ValueError('tool artifact must be a relative file within artifacts')
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def write_text(self, name: str, content: str) -> Path:
        path = self._path(name)
        atomic_write_text(path, content)
        return path

    def write_json(self, name: str, content) -> Path:
        path = self._path(name)
        atomic_write_json(path, content)
        return path


class _Toolchain:
    def __init__(self, factory):
        self.factory, self.instance = factory, None

    def get(self):
        if self.instance is None:
            self.instance = self.factory()
        return self.instance


class _TimedProcesses:
    def __init__(self, processes, timeout_s):
        self._processes = processes
        self._deadline = time.monotonic() + timeout_s

    def run(self, request):
        # All subprocesses of this tool call share one deadline; starting a
        # second command must not grant the tool another full timeout.
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            raise BudgetExhausted('tool budget exhausted')
        return self._processes.run(replace(request, timeout_s=min(request.timeout_s, remaining)))


class ManagedToolContext:
    def __init__(self, task, budget, processes, artifacts, emit, toolchain_factory, *,
                 timeout_s=None, _shared_toolchain=None):
        self.task, self.budget = task, budget
        self.processes, self.artifacts, self.emit = processes, artifacts, emit
        self.timeout_s = timeout_s
        self._toolchain = _shared_toolchain or _Toolchain(toolchain_factory)

    def toolchain(self):
        return self._toolchain.get()

    def with_timeout(self, timeout_s):
        processes = self.processes if timeout_s is None else _TimedProcesses(self.processes, timeout_s)
        # Per-call timeout wrappers share the run's lazy toolchain instance.
        return type(self)(self.task, self.budget, processes,
            self.artifacts, self.emit, None, timeout_s=timeout_s, _shared_toolchain=self._toolchain)
