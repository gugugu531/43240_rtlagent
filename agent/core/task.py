"""Solver-visible task information, with no judge or reference inputs."""
from __future__ import annotations
from dataclasses import dataclass, replace
from pathlib import Path
from agent.core.interface import InterfaceSpec, parse_expected_interface


@dataclass(frozen=True)
class TaskSpec:
    id: str
    prompt: str
    interface: str
    top: str
    expected_interface: InterfaceSpec
    raw_prompt: str | None = None
    raw_interface: str | None = None

    @classmethod
    def from_text(cls, task_id: str, prompt: str, interface: str = '', *, top: str = '') -> TaskSpec:
        spec = parse_expected_interface(interface, prompt, top=top or None)
        return cls(task_id, prompt, interface, top or spec.module_name or 'TopModule', spec)

    @classmethod
    def from_directory(cls, directory: Path, *, task_id: str | None = None, top: str = '') -> TaskSpec:
        def read(name):
            path = directory / name
            return path.read_text(encoding='utf-8') if path.is_file() else ''
        prompt, interface = read('prompt.txt'), read('interface.txt')
        task = cls.from_text(task_id or directory.name, prompt.strip(), interface.strip(), top=top)
        return replace(task, raw_prompt=prompt, raw_interface=interface)

    def public_dict(self):
        return dict(task_id=self.id, top=self.top, expected_interface=self.expected_interface.public_dict())
