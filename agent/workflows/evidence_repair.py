"""Minimal evidence-gated workflow: one initial candidate and at most one repair."""
from __future__ import annotations

from agent.core.registry import WORKFLOW_REGISTRY, build_node
from agent.core.state import SelectionDecision
from agent.nodes.feedback import FeedbackInput
from agent.workflows.repair_loop import RepairLoop


@WORKFLOW_REGISTRY.register('evidence_repair')
class EvidenceRepair(RepairLoop):
    """Scheme A without ICL, planning, RAG, reflection, or testbench access."""

    def __init__(self, max_tokens: int = 8192, temperature: float = 0.0,
                 timeout_s: float = 300.0, max_request_retries: int = 1,
                 max_model_calls: int | None = None, minimum_action_s: float = 0.05,
                 max_feedback_chars: int = 1600):
        if max_model_calls is None:
            max_model_calls = 2 + max_request_retries
        super().__init__(max_rounds=2, max_tokens=max_tokens, temperature=temperature,
                         timeout_s=timeout_s, use_skills=False,
                         max_request_retries=max_request_retries,
                         max_model_calls=max_model_calls,
                         minimum_action_s=minimum_action_s,
                         repair_output_drivers=False)
        self.max_feedback_chars = max_feedback_chars
        self.generate = build_node('rtl_generate', max_tokens=max_tokens,
                                   temperature=temperature, top_p=1.0,
                                   timeout_s=timeout_s, prompt_style='repair', use_skills=False)
        self.feedback_builder = build_node('structured_feedback',
                                           max_summary_chars=max_feedback_chars)

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
