"""Deterministic sampling schedule for search experiments."""
from dataclasses import dataclass, replace
from agent.core.model import ModelRequest
from agent.nodes.generate import GenerateNode


@dataclass(frozen=True)
class SeededGenerate(GenerateNode):
    component_name = 'seeded_generate'
    assembly_roles = ['alternative', 'generate']
    assembly_defaults = {'params': {'max_tokens': 8192,
                'temperature': 0.6,
                'timeout_s': 300.0,
                'prompt_style': 'repair',
                'use_skills': False,
                'minimum_s': 0.0,
                'top_p': 0.95,
                'base_seed': 20261013},
     'dependencies': {'skill_tool': {'component': 'skill_lookup', 'id': 'skill_tool',
                                     'when': {'use_skills': True}}}}
    base_seed: int = 20261013

    def __post_init__(self):
        super().__post_init__()
        ModelRequest([], seed=self.base_seed)
        ModelRequest([], seed=self.base_seed + 2)

    def run(self, ctx, input):
        return super().run(ctx, replace(input, seed=self.base_seed + input.round - 1))
