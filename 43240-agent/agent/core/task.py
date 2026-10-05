"""Solver-visible task information, with no judge or reference inputs."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from ..interface import InterfaceSpec, parse_expected_interface


@dataclass(frozen=True)
class TaskSpec:
    id: str
    prompt: str
    interface: str
    top: str
    expected_interface: InterfaceSpec

    @classmethod
    def from_text(cls, task_id: str, prompt: str, interface: str = '', *, top: str = '') -> TaskSpec:
        spec = parse_expected_interface(interface, prompt)
        return cls(task_id, prompt, interface, top or spec.module_name or 'TopModule', spec)

    @classmethod
    def from_directory(cls, directory: Path, *, task_id: str | None = None, top: str = '') -> TaskSpec:
        def read(name):
            path = directory / name
            return path.read_text(encoding='utf-8').strip() if path.is_file() else ''
        return cls.from_text(task_id or directory.name, read('prompt.txt'), read('interface.txt'), top=top)

    def public_dict(self):
        return dict(task_id=self.id, top=self.top, expected_interface=self.expected_interface.public_dict())
