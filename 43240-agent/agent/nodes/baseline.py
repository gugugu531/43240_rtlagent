"""The official RTL baseline rules inside the recorded Agent lifecycle."""
from dataclasses import replace
import baseline as official

from agent.core.components import Component
from agent.core.model import ModelRequest
from agent.core.registry import NODE_REGISTRY
from agent.nodes.generate import GenerateInput
from agent.nodes.extract import ExtractInput, ExtractionOutput
from agent.nodes.extraction import extract_result


@NODE_REGISTRY.register('baseline_generate')
class BaselineGenerateNode(Component):
    def run(self, ctx, input: GenerateInput):
        task = input.task
        prompt = task.raw_prompt if task.raw_prompt is not None else task.prompt
        interface = task.raw_interface if task.raw_interface is not None else task.interface
        if interface:
            prompt += '\n\nInterface:\n' + interface
        ctx.emit('prompt_resources', round=input.round, source='baseline.py',
                 script_sha256=official.self_sha256(), track='rtl')
        model = ctx.llm.baseline_model(timeout_s=ctx.budget.timeout_s(30))
        return ctx.llm.chat(ModelRequest(
            [{'role': 'system', 'content': official.SYS['rtl']},
             {'role': 'user', 'content': prompt}],
            max_tokens=official.MAX_TOKENS, temperature=official.TEMPERATURE,
            top_p=official.TOP_P, model=model, stream=None, profile='baseline_rtl',
            timeout_s=ctx.budget.timeout_s(official.TIMEOUT_S)))


@NODE_REGISTRY.register('baseline_extract')
class BaselineExtractNode(Component):
    def run(self, ctx, input: ExtractInput) -> ExtractionOutput:
        code = official.extract(input.reply.content, 'rtl')
        # Diagnostics describe the reply; they never filter the official output.
        diagnostics = extract_result(input.reply.content, target_module='TopModule')
        extracted = replace(diagnostics, code=code)
        candidate = ctx.create_candidate(
            code, reply=input.reply, round=input.round, parent_id=input.parent_id,
            source_stage=input.source_stage, extraction_status=diagnostics.status)
        ctx.record_extraction(input.reply.call_id, extracted, candidate.id)
        return ExtractionOutput(extracted, candidate)
