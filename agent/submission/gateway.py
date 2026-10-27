"""Answer submission gateway.

`solution.v` is the only official answer file. Only this module publishes it,
and every write goes through CandidateStore's atomic replace. The current
development policy is last-write-wins; the recorded `selected_id` and
`overrode_selected` fields keep the evidence-backed choice visible for audit.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agent.domain.rtl.extract import extract_result


class SubmissionError(ValueError):
    """A draft cannot be registered as an answer candidate."""


@dataclass
class SubmissionState:
    policy: str = "last_written"
    last_written_id: str | None = None
    last_reason: str = ""
    published: list[dict] = field(default_factory=list)
    finalized: bool = False
    final_record: dict | None = None

    def public_dict(self):
        return {
            "policy": self.policy,
            "last_written_id": self.last_written_id,
            "last_reason": self.last_reason,
            "published": list(self.published),
            "finalized": self.finalized,
            "final": self.final_record,
        }


class SubmissionGateway:
    def __init__(self, ctx, *, policy="last_written"):
        if policy not in ("last_written", "selected"):
            raise ValueError("submission policy must be last_written or selected")
        self.ctx = ctx
        self.state = SubmissionState(policy=policy)

    def _emit(self, event, **fields):
        self.ctx.record.emit("submission", event, **fields)

    def _publish(self, candidate, reason):
        self.ctx.candidates.publish(candidate.id, reason)
        self.state.last_written_id = candidate.id
        self.state.last_reason = reason
        self.state.published.append(
            {"candidate_id": candidate.id, "code_hash": candidate.code_hash,
             "reason": reason}
        )
        self._emit(
            "published",
            policy=self.state.policy,
            candidate_id=candidate.id,
            code_hash=candidate.code_hash,
            reason=reason,
        )

    def register(self, candidate, *, reason):
        """Register a host-extracted candidate; publish only under LWW."""
        if self.state.finalized:
            raise SubmissionError("submission already finalized")
        if self.state.policy == "last_written":
            self._publish(candidate, reason)
        else:
            self._emit(
                "registered",
                policy=self.state.policy,
                candidate_id=candidate.id,
                code_hash=candidate.code_hash,
                reason=reason,
            )
        return self.public_dict()

    def submit_text(self, code, *, top=None, source_stage="submit", note=""):
        """Validate model-provided text, then create and register a candidate."""
        if self.state.finalized:
            raise SubmissionError("submission already finalized")
        expected = top or self.ctx.task.top
        extraction = extract_result(code, expected)
        if (
            extraction.status != "ok"
            or not extraction.complete
            or not extraction.target_module_found
            or extraction.suspected_truncation
        ):
            raise SubmissionError(
                "draft is not a complete module for " + str(expected)
            )
        candidate = self.ctx.candidates.create(
            extraction.code,
            source_stage=f"submit:{source_stage}",
            extraction_status=extraction.status,
        )
        reason = f"submit:{source_stage}:{note}" if note else f"submit:{source_stage}"
        result = self.register(candidate, reason=reason)
        return {
            **result,
            "candidate_id": candidate.id,
            "code_hash": candidate.code_hash,
            "published": self.state.last_written_id == candidate.id,
        }

    def finalize(self, reason):
        """Publish the policy-selected answer once; safe to call repeatedly."""
        if self.state.finalized:
            return self.public_dict()
        selected_id = self.ctx.candidates.selected_id
        target_id = (
            self.state.last_written_id
            if self.state.policy == "last_written"
            else selected_id
        )
        overrode = bool(
            self.state.policy == "last_written"
            and selected_id
            and target_id
            and target_id != selected_id
        )
        published = False
        if target_id:
            candidate = self.ctx.candidates.get(target_id)
            if candidate is None:
                raise SubmissionError("submission target candidate is missing")
            # Re-publishing the same id is idempotent and repairs a missing file.
            self.ctx.candidates.publish(target_id, f"finalize:{reason}")
            published = True
        record = {
            "policy": self.state.policy,
            "target_id": target_id,
            "selected_id": selected_id,
            "overrode_selected": overrode,
            "published": published,
            "delivery": "complete_rtl" if published else "empty",
            "reason": reason,
        }
        self.state.finalized = True
        self.state.final_record = record
        self._emit("finalized", **record)
        return self.public_dict()

    def public_dict(self):
        return self.state.public_dict()
