"""Explicit component bindings for supported initial-response replay."""
from __future__ import annotations
from dataclasses import dataclass
from agent.core.components import Node


@dataclass(frozen=True)
class InitialReplayContract:
    request_policy: str
    extract_node: Node
    check_nodes: tuple[Node, ...]

    def __post_init__(self):
        object.__setattr__(self, 'check_nodes', tuple(self.check_nodes))
