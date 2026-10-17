"""Minimal evidence-gated workflow: one initial candidate and at most one repair."""
from __future__ import annotations

from agent.core.components import Node
from agent.core.extraction import ExtractInput, ExtractionOutput
from agent.core.model import ModelReply
from agent.core.state import CheckResult, SelectionDecision
from agent.nodes.check import CheckInput
from agent.nodes.feedback import FeedbackInput, StructuredFeedback
from agent.nodes.generate import GenerateInput
from agent.workflows.repair_loop import RepairLoop


class EvidenceRepair(RepairLoop):
    component_name = 'evidence_repair'
    dependencies = {**RepairLoop.dependencies, 'feedback_builder': 'node'}
    dependency_types = {**RepairLoop.dependency_types, 'feedback_builder': (FeedbackInput, StructuredFeedback)}
    """Scheme A without ICL, planning, RAG, reflection, or testbench access."""

    def __init__(self, generate: Node[GenerateInput, ModelReply],
                 extract: Node[ExtractInput, ExtractionOutput],
                 interface: Node[CheckInput, CheckResult],
                 lint: Node[CheckInput, CheckResult],
                 synth: Node[CheckInput, CheckResult],
                 feedback_builder: Node[FeedbackInput, StructuredFeedback], *,
                 max_rounds: int = 2, max_request_retries: int = 1,
                 max_model_calls: int | None = None, minimum_action_s: float = 0.05,
                 repair_output_drivers: bool = False) -> None:
        if max_model_calls is None:
            max_model_calls = max_rounds + max_request_retries
        super().__init__(generate, extract, interface, lint, synth,
                         max_rounds=max_rounds, max_request_retries=max_request_retries,
                         max_model_calls=max_model_calls, minimum_action_s=minimum_action_s,
                         repair_output_drivers=repair_output_drivers)
        self.feedback_builder = feedback_builder

    def choose(self, state) -> SelectionDecision:
        decision = super().choose(state)
        if decision.candidate_id is not None:
            return decision
        # Keep complete source even when every candidate has a known defect.
        # This is a last-resort answer, never evidence that a check passed.
        fallbacks = []
        for candidate in state.candidates.values():
            if candidate.extraction_status not in ('ok', 'complete', 'ambiguous'):
                continue
            evidence = [check for check in state.checks if check.candidate_id == candidate.id]
            passes = {check.kind for check in evidence if check.status == 'passed'}
            rank = ('synth' in passes, 'lint' in passes, 'interface' in passes)
            fallbacks.append((candidate.id, rank, tuple(check.id for check in evidence)))
        if not fallbacks:
            return decision
        # Creation order breaks ties, so a failed repair cannot replace its parent.
        candidate_id, _, evidence_ids = max(fallbacks, key=lambda item: item[1])
        return SelectionDecision(candidate_id, candidate_id != state.selected_candidate_id,
                                 'failed_check_fallback', evidence_ids)

    def build_extraction_feedback(self, ctx, reply, extraction) -> str:
        summary = '; '.join(extraction.diagnostics) or f'extraction status: {extraction.status}'
        result = ctx.execute(self.feedback_builder, FeedbackInput(
            reply.call_id, 'extraction', extraction.status, 'extraction', summary))
        return result.text

    def build_check_feedback(self, ctx, checks) -> str:
        failed = [check for check in checks if check.status != 'passed']
        check = failed[-1] if failed else checks[-1]
        result = ctx.execute(self.feedback_builder, FeedbackInput(
            check.id, check.kind, check.status, check.classify(), check.summary))
        return result.text
