"""Deterministic sampling schedule for search experiments."""
from dataclasses import dataclass, replace
from agent.core.model import ModelRequest
from agent.nodes.generate import GenerateNode


@dataclass(frozen=True)
class SeededGenerate(GenerateNode):
    component_name = 'seeded_generate'
    base_seed: int = 20261013

    def __post_init__(self):
        super().__post_init__()
        ModelRequest([], seed=self.base_seed)
        ModelRequest([], seed=self.base_seed + 2)

    def run(self, ctx, input):
        return super().run(ctx, replace(input, seed=self.base_seed + input.round - 1))
