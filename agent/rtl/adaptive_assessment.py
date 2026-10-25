"""Candidate check records and shared evidence validation, without selection policy."""

from copy import deepcopy
from dataclasses import asdict, dataclass, field
import re
from typing import Literal

from agent.rtl.result import CheckResult


@dataclass
class BehaviorAssessment:
    route: Literal["structural", "model", "properties"] = "structural"
    status: str = "not_executed"
    details: dict = field(default_factory=dict)
    failure_kind: str | None = None

    def public_dict(self):
        result = asdict(self)
        if self.failure_kind is None:
            del result["failure_kind"]
        return result


@dataclass
class CandidateAssessment:
    candidate_id: str
    candidate_hash: str
    parent_id: str | None
    parent_hash: str | None
    execution_id: str
    checker_hash: str
    check_plan_hash: str
    checker_implementation_hash: str
    structure: dict[str, CheckResult] = field(default_factory=dict)
    behavior: BehaviorAssessment = field(default_factory=BehaviorAssessment)

    def public_dict(self):
        """Keep the persisted schema independent of runtime objects."""
        return {
            "candidate_id": self.candidate_id, "candidate_hash": self.candidate_hash,
            "parent_id": self.parent_id, "parent_hash": self.parent_hash,
            "execution_id": self.execution_id, "checker_hash": self.checker_hash,
            "check_plan_hash": self.check_plan_hash,
            "checker_implementation_hash": self.checker_implementation_hash,
            "structure": {stage: deepcopy(result.trace_dict()) for stage, result in self.structure.items()},
            "behavior": self.behavior.public_dict(),
        }

    @property
    def structural_passed(self):
        """Completion summary only; promotion requires additional evidence checks."""
        interface = self.structure.get("interface")
        return (
            interface is not None and interface.status in ("passed", "failed", "skipped")
            and not interface.blocking
            and all(stage in self.structure and self.structure[stage].status == "passed"
                    for stage in ("lint", "synth"))
        )

    @property
    def interface_verified(self):
        interface = self.structure.get("interface")
        return interface is not None and interface.status == "passed"


class AssessmentError(ValueError):
    pass


def _hash(value, name):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise AssessmentError(name + " must be a SHA256 hex digest")
    return value


def _name(value, name):
    if not isinstance(value, str) or not value or len(value) > 256:
        raise AssessmentError(name + " must be a nonempty bounded identifier")
    return value


def validate_assessment(assessment):
    """Validate the common identity before consuming a persisted assessment."""
    if not isinstance(assessment, dict):
        raise AssessmentError("candidate assessment must be an object")
    _name(assessment.get("candidate_id"), "candidate_id")
    _hash(assessment.get("candidate_hash"), "candidate_hash")
    _name(assessment.get("execution_id"), "assessment execution_id")
    _hash(assessment.get("checker_implementation_hash"), "checker_implementation_hash")
    if not isinstance(assessment.get("structure"), dict):
        raise AssessmentError("assessment needs a structure result map")


def bound_details(result, assessment, *, behavior=False):
    """Require evidence from this candidate and checker, with an execution ID."""
    if not isinstance(result, dict) or not isinstance(result.get("details"), dict):
        raise AssessmentError("each tool result needs its full bound details")
    details = result["details"]
    if not behavior and result.get("candidate_id") != assessment["candidate_id"]:
        raise AssessmentError("tool candidate_id differs from assessment")
    if details.get("candidate_hash") != assessment["candidate_hash"]:
        raise AssessmentError("tool candidate_hash differs from assessment")
    _name(details.get("execution_id"), "tool execution_id")
    if details.get("checker_hash") != assessment["checker_implementation_hash"]:
        raise AssessmentError("tool checker implementation differs from assessment")
    return details


def structural_failures(assessment, *, require_complete=False):
    """Validate structure bindings and return explicit candidate code failures."""
    results = assessment["structure"]
    if set(results) - {"interface", "lint", "synth", "observation"}:
        raise AssessmentError("unknown structure check kind")
    if require_complete and not {"interface", "lint", "synth"}.issubset(results):
        raise AssessmentError("promotion requires interface, lint and synthesis assessments")
    failures, executions = [], []
    for kind, result in results.items():
        details = bound_details(result, assessment)
        if kind == "observation":
            _hash(assessment.get("check_plan_hash"), "observation sampling plan")
            if details.get("plan_hash") != assessment["check_plan_hash"]:
                raise AssessmentError("observation compilation used a different sampling plan")
        executions.append(details["execution_id"])
        if (result.get("status") == "failed" and result.get("failure_kind") == "code"
                and (kind != "interface" or result.get("blocking") is True)
                and type(result.get("rc")) is int and result["rc"] != 0):
            failures.append(kind)
    if len(executions) != len(set(executions)):
        raise AssessmentError("structure checks must have distinct execution identities")
    return failures
