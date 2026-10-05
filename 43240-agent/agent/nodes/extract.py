"""Extract one candidate, retaining evidence even when extraction fails."""
from dataclasses import dataclass
from ..candidate import Candidate
from ..core.components import Component
from ..core.model import ModelReply
from ..core.registry import NODE_REGISTRY
from ..extraction import ExtractionResult, extract_result


@dataclass(frozen=True)
class ExtractInput:
    reply: ModelReply
    round: int = 1
    parent_id: str | None = None
    source_stage: str = 'generate'


@dataclass(frozen=True)
class ExtractionOutput:
    extraction: ExtractionResult
    candidate: Candidate | None


@NODE_REGISTRY.register('rtl_extract')
class ExtractNode(Component):
    def run(self, ctx, input: ExtractInput) -> ExtractionOutput:
        extracted = extract_result(input.reply.content, target_module=ctx.task.top)
        candidate = None
        if extracted.code:
            candidate = ctx.create_candidate(
                extracted.code, reply=input.reply, round=input.round, parent_id=input.parent_id,
                source_stage=input.source_stage, extraction_status=extracted.status)
        ctx.record_extraction(input.reply.call_id, extracted, candidate.id if candidate else None)
        return ExtractionOutput(extracted, candidate)
