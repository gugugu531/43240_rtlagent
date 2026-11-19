"""Publish an explicit decision or keep the best available interruption fallback."""

from __future__ import annotations

from dataclasses import dataclass, field

from agent.domain.rtl.extract import extract_result
from agent.domain.rtl.result import tool_succeeded


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
        if policy not in ("last_written", "selected", "author_decides"):
            raise ValueError("unknown submission policy: " + str(policy))
        self.ctx = ctx
        self.state = SubmissionState(policy=policy)
        # Registration order is draft order. Rechecking an older draft must
        # not move it ahead of a newer draft which has also passed both tools.
        self._assessments = {}
        self._checkpoint_basis = None
        self._pending_decision = None
        if policy == "author_decides":
            self._emit("started", policy=policy)

    def _emit(self, event, **fields):
        self.ctx.record.emit("submission", event, **fields)

    def _publish(self, candidate, reason):
        self.ctx.candidates.publish(candidate.id, reason)
        self._note_publication(candidate, reason)

    def _note_publication(self, candidate, reason):
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
        """Register a complete draft and update the on-disk answer for this policy."""
        if self.state.policy == "author_decides":
            candidate = self._stored_candidate(candidate)
            if candidate.id in self._assessments:
                if not self.state.finalized and not self._pending_decision:
                    self._checkpoint()
                return self.public_dict()
        if self.state.finalized or self._pending_decision:
            raise SubmissionError("submission already finalized")
        if self.state.policy == "author_decides":
            extraction = extract_result(candidate.code, self.ctx.task.top)
            if (candidate.extraction_status not in ("ok", "complete")
                    or extraction.status != "ok" or not extraction.complete
                    or extraction.suspected_truncation):
                raise SubmissionError("fallback requires a complete RTL draft for the requested top")
            self._assessments[candidate.id] = None
            self._emit("registered", policy=self.state.policy, candidate_id=candidate.id,
                       code_hash=candidate.code_hash, reason=reason)
            self._checkpoint()
        elif self.state.policy == "last_written":
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

    def _stored_candidate(self, candidate):
        try:
            stored = self.ctx.candidates.get(candidate.id)
        except (AttributeError, KeyError) as error:
            raise SubmissionError("unknown submission candidate") from error
        if stored is None or stored.code_hash != candidate.code_hash or stored.code != candidate.code:
            raise SubmissionError("submission candidate differs from its stored identity")
        return stored

    def record_structure(self, candidate, assessment):
        """Checkpoint only after candidate-bound tool results have been returned."""
        candidate = self._stored_candidate(candidate)
        if self.state.policy != "author_decides" or candidate.id not in self._assessments:
            raise SubmissionError("structure can be recorded only for a registered author draft")
        if (not isinstance(assessment, dict) or assessment.get("candidate_id") != candidate.id
                or assessment.get("candidate_hash") != candidate.code_hash):
            raise SubmissionError("structural assessment belongs to a different candidate")
        checks = assessment.get("checks")
        if not checks or not isinstance(checks, dict):
            raise SubmissionError("structural assessment needs actual tool results")
        for stage, check in checks.items():
            if (stage not in ("interface", "lint", "synth") or not isinstance(check, dict)
                    or check.get("kind") != stage
                    or check.get("candidate_id") != candidate.id
                    or not isinstance(check.get("details"), dict)
                    or check["details"].get("candidate_hash") != candidate.code_hash):
                raise SubmissionError(f"unbound structural tool result: {stage}")
            if check.get("status") not in ("passed", "failed", "timeout", "unavailable", "error", "skipped"):
                raise SubmissionError(f"invalid structural tool status: {stage}")
        toolchain_passed = all(stage in checks and tool_succeeded(checks[stage]["status"], checks[stage].get("rc"))
                               for stage in ("lint", "synth"))
        code_failed = any(check.get("status") == "failed" and check.get("failure_kind") == "code"
                          for check in checks.values())
        result = {"toolchain_passed": toolchain_passed, "code_failed": code_failed}
        if self._assessments[candidate.id] == result:
            if not self.state.finalized and not self._pending_decision:
                self._checkpoint()
            return self.public_dict()
        if self.state.finalized or self._pending_decision:
            raise SubmissionError("submission already finalized")
        self._assessments[candidate.id] = result
        self._checkpoint()
        return self.public_dict()

    def _fallback(self):
        for identity, assessment in reversed(self._assessments.items()):
            if assessment and assessment["toolchain_passed"]:
                return identity, "latest_toolchain_passed"
        if self._assessments:
            return next(reversed(self._assessments)), "latest_complete"
        return None, "no_complete_candidate"

    def _checkpoint(self):
        """Persist the interruption target before beginning another expensive stage."""
        target_id, basis = self._fallback()
        if target_id == self.state.last_written_id and basis == self._checkpoint_basis:
            return
        candidate = self.ctx.candidates.get(target_id)
        if target_id != self.state.last_written_id:
            self._publish(candidate, "checkpoint:" + basis)
        self._emit("checkpoint", policy=self.state.policy, candidate_id=target_id,
                   code_hash=candidate.code_hash, fallback_basis=basis)
        self._checkpoint_basis = basis

    def submit_candidate(self, candidate, *, mode, reason):
        """Complete a normal run by selecting the current, already assessed draft."""
        if self.state.policy != "author_decides" or mode not in ("author_submit", "structural_auto"):
            raise SubmissionError("unsupported submission decision")
        candidate = self._stored_candidate(candidate)
        if self.state.finalized:
            previous = self.state.final_record
            if previous["target_id"] == candidate.id and previous.get("mode") == mode:
                return self.public_dict()
            raise SubmissionError("a different submission is already final")
        if candidate.id != next(reversed(self._assessments), None):
            raise SubmissionError("only the current registered draft can be submitted")
        assessment = self._assessments[candidate.id]
        if assessment is None or assessment["code_failed"]:
            raise SubmissionError("submission requires a structural assessment without a known code error")
        if mode == "structural_auto" and not assessment["toolchain_passed"]:
            raise SubmissionError("automatic submission requires successful lint and synthesis")
        if self._pending_decision and self._pending_decision != (candidate.id, mode, reason):
            raise SubmissionError("a different submission is already in progress")
        self._pending_decision = (candidate.id, mode, reason)
        return self._commit_decision()

    def _commit_decision(self):
        # A soft deadline during the atomic write can be completed by main's
        # finalizer without changing an already issued author decision.
        candidate_id, mode, reason = self._pending_decision
        candidate = self.ctx.candidates.get(candidate_id)
        self._emit("decision", policy=self.state.policy, candidate_id=candidate.id,
                   code_hash=candidate.code_hash, mode=mode, reason=reason)
        self.ctx.candidates.select(candidate_id, mode)
        self._note_publication(candidate, reason)
        return self._finish(candidate, reason, mode=mode, fallback_basis=None)

    def submit_text(self, code, *, top=None, source_stage="submit", note=""):
        """Validate model-provided text, then create and register a candidate."""
        if self.state.finalized:
            raise SubmissionError("submission already finalized")
        expected = self.ctx.task.top
        if top and top != expected:
            raise SubmissionError(
                f"submitted top {top!r} does not match task top {expected!r}"
            )
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
        if self.state.policy == "author_decides":
            if self._pending_decision:
                return self._commit_decision()
            target_id, basis = self._fallback()
            candidate = self.ctx.candidates.get(target_id)
            if candidate is not None:
                self._publish(candidate, f"finalize:{reason}")
            else:
                self.ctx.candidates.publish_empty(f"finalize:{reason}")
            return self._finish(candidate, reason, mode="fallback", fallback_basis=basis)
        selected_id = self.ctx.candidates.selected_id
        target_id = (
            self.state.last_written_id
            if self.state.policy == "last_written"
            else selected_id
        )
        candidate = self.ctx.candidates.get(target_id)
        if target_id:
            if candidate is None:
                raise SubmissionError("submission target candidate is missing")
            # Re-publishing the same id is idempotent and repairs a missing file.
            self.ctx.candidates.publish(target_id, f"finalize:{reason}")
        return self._finish(candidate, reason)

    def _finish(self, candidate, reason, **decision):
        target_id = candidate.id if candidate is not None else None
        selected_id = self.ctx.candidates.selected_id
        record = {
            "policy": self.state.policy,
            "target_id": target_id,
            "code_hash": candidate.code_hash if candidate is not None else None,
            "selected_id": selected_id,
            "overrode_selected": bool(selected_id and target_id and selected_id != target_id),
            "published": candidate is not None,
            "delivery": "complete_rtl" if candidate is not None else "empty",
            "reason": reason,
            **decision,
        }
        if self.state.policy == "author_decides":
            assessment = self._assessments.get(target_id)
            if assessment is None:
                record["structure_status"] = "not_checked"
            elif assessment["code_failed"]:
                record["structure_status"] = "code_failed"
            elif assessment["toolchain_passed"]:
                record["structure_status"] = "lint_synth_passed"
            else:
                record["structure_status"] = "unverified"
        self._emit("finalized", **record)
        self.state.final_record = record
        self.state.finalized = True
        return self.public_dict()

    def public_dict(self):
        return self.state.public_dict()
