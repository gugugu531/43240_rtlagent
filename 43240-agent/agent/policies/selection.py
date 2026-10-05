"""Compare real evidence without turning unknown checks into passes."""
from dataclasses import dataclass
from collections.abc import Mapping, Sequence
from ..candidate import Candidate
from ..core.state import CheckResult
from ..core.components import Component
from .diagnostics import classify_check


@dataclass(frozen=True)
class SelectionDecision:
    candidate_id: str | None
    changed: bool
    reason: str
    evidence_ids: tuple[str, ...]


class SelectionPolicy(Component):
    def choose(self, candidates: Mapping[str, Candidate], checks: Sequence[CheckResult],
               current_id: str | None) -> SelectionDecision:
        eligible = []
        for candidate in candidates.values():
            evidence = [c for c in checks if c.candidate_id == candidate.id]
            if candidate.extraction_status not in ('ok', 'complete', 'ambiguous'):
                continue
            if any(classify_check(c)[0].kind == 'code' for c in evidence):
                continue
            passes = {c.kind for c in evidence if c.status == 'passed'}
            # Lexicographic strength; ties retain the current choice, then creation order.
            rank = ('synth' in passes, 'lint' in passes, 'interface' in passes)
            eligible.append((candidate.id, rank, tuple(c.id for c in evidence if c.status == 'passed')))
        if not eligible:
            return SelectionDecision(None, current_id is not None, 'no_eligible_candidate', ())
        strongest = max(rank for _, rank, _ in eligible)
        choices = [entry for entry in eligible if entry[1] == strongest]
        chosen = next((entry for entry in choices if entry[0] == current_id), choices[0])
        reason = 'synth_passed' if strongest[0] else 'lint_passed' if strongest[1] else 'complete_fallback'
        return SelectionDecision(chosen[0], chosen[0] != current_id, reason, chosen[2])
