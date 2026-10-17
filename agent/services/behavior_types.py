"""Shared behavior-plan data types without execution-service imports."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from agent.services.timing import TimingContract
from agent.services.literal_spec import LiteralTruthTable
from agent.core.candidate import Candidate


@dataclass(frozen=True)
class StimulusStep:
    inputs: tuple[tuple[str, int], ...]
    wait_ns: int
    expected: tuple[tuple[str, int], ...]
    basis: str


@dataclass(frozen=True)
class TestPlan:
    top: str
    ports: tuple[tuple[str, str, int], ...]
    steps: tuple[StimulusStep, ...]
    timing: TimingContract = TimingContract()
    literal_table: LiteralTruthTable | None = None

    def public_dict(self):
        result = dict(oracle_protocol=2, top=self.top, ports=[list(p) for p in self.ports], timing=self.timing.public_dict(), steps=[
            dict(inputs=dict(s.inputs), wait_ns=s.wait_ns, expected=dict(s.expected), basis=s.basis)
            for s in self.steps])
        if self.literal_table:
            result['literal_table'] = self.literal_table.public_dict()
        return result

    @property
    def oracle_source(self):
        return 'public_literal_truth_table' if self.literal_table else 'model_spec_hypothesis'

    @property
    def fingerprint(self):
        return hashlib.sha256(json.dumps(self.public_dict(), sort_keys=True).encode()).hexdigest()

    def trace_dict(self):
        return dict(plan_hash=self.fingerprint, steps=len(self.steps),
                    assertions=sum(len(s.expected) for s in self.steps),
                    oracle_protocol=2, oracle_source=self.oracle_source, official_verification=False)


@dataclass(frozen=True)
class PlanResult:
    plan: TestPlan | None
    call_id: str
    reason: str = ''


@dataclass(frozen=True)
class BehaviorInput:
    candidate: Candidate
    plan: TestPlan
