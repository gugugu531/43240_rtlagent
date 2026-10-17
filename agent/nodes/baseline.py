"""The official RTL baseline rules inside the recorded Agent lifecycle."""
from dataclasses import replace
import baseline as official

from agent.core.components import Node
from agent.core.model import ModelRequest, ModelReply
from agent.nodes.generate import GenerateInput
from agent.core.extraction import ExtractInput, ExtractionOutput
from agent.services.extraction import extract_result


class BaselineGenerateNode(Node[GenerateInput, ModelReply]):
    component_name = 'baseline_generate'
    input_type = GenerateInput
    output_type = ModelReply

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


class BaselineExtractNode(Node[ExtractInput, ExtractionOutput]):
    component_name = 'baseline_extract'
    input_type = ExtractInput
    output_type = ExtractionOutput
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
