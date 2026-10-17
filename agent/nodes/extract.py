"""Extract one candidate, retaining evidence even when extraction fails."""
from agent.core.components import Node
from agent.core.extraction import ExtractInput, ExtractionOutput
from agent.services.extraction import extract_result


class ExtractNode(Node[ExtractInput, ExtractionOutput]):
    component_name = 'rtl_extract'
    input_type = ExtractInput
    output_type = ExtractionOutput

    def run(self, ctx, input: ExtractInput) -> ExtractionOutput:
        extracted = extract_result(input.reply.content, target_module=ctx.task.top)
        candidate = None
        if extracted.code:
            candidate = ctx.create_candidate(
                extracted.code, reply=input.reply, round=input.round, parent_id=input.parent_id,
                source_stage=input.source_stage, extraction_status=extracted.status)
        ctx.record_extraction(input.reply.call_id, extracted, candidate.id if candidate else None)
        return ExtractionOutput(extracted, candidate)
