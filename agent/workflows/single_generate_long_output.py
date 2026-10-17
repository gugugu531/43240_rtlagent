"""Explicitly configured output-budget experiment."""
from agent.workflows.single_generate import SingleGenerate


class SingleGenerateLongOutput(SingleGenerate):
    component_name = 'single_generate_long_output'
