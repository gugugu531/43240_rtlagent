"""Explicitly configured output-budget experiment."""
from agent.workflows.single_generate import SingleGenerate


class SingleGenerateLongOutput(SingleGenerate):
    component_name = 'single_generate_long_output'
    assembly_roles = ['workflow']
    assembly_defaults = {'params': {},
     'dependencies': {'generate': {'component': 'long_output_generate', 'id': 'generate'},
                      'extract': {'component': 'baseline_extract', 'id': 'extract'}}}
