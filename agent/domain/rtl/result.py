"""Check outcomes share one explicit failure classification."""

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class CheckResult:
    status: Literal["passed", "failed", "timeout", "unavailable", "error", "skipped"]
    summary: str
    blocking: bool = False
    rc: int = 0
    elapsed_s: float = 0.0
    command: tuple[tuple[str, ...], ...] = ()
    details: dict = field(default_factory=dict)
    log_paths: tuple[str, ...] = ()
    failure_kind: Literal["code", "checker", "environment", "timeout", "unknown"] = "unknown"
    id: str | None = None
    kind: str = ""
    candidate_id: str | None = None
    work_dir: str | None = None

    def trace_dict(self):
        return dict(
            id=self.id,
            kind=self.kind,
            candidate_id=self.candidate_id,
            status=self.status,
            excerpt=self.summary[:2000],
            rc=self.rc,
            elapsed_s=self.elapsed_s,
            failure_kind=self.failure_kind,
            blocking=self.blocking,
            command=self.command,
            log_paths=self.log_paths,
            details=self.details,
        )


def tool_succeeded(status, rc):
    """A reported pass needs a successful process result."""
    return status == "passed" and type(rc) is int and rc == 0


def checker_hash():
    """Identity covers validation, evaluation, trace parsing and tool adapters."""
    import hashlib
    from pathlib import Path

    root = Path(__file__).parent
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def bind_result(result, candidate, kind, suite=None):
    """Bind evidence to the actual candidate, suite and checker implementation."""
    from dataclasses import replace
    import hashlib
    import json
    from .identity import suite_hash

    version = checker_hash()
    suite_identity = (
        suite_hash(suite) if suite is not None else result.details.get("suite_hash")
    )
    identity = hashlib.sha256(
        json.dumps([candidate.code_hash, kind, suite_identity, version]).encode()
    ).hexdigest()
    return replace(
        result,
        id=identity,
        candidate_id=candidate.id,
        kind=kind,
        details={
            **result.details,
            "candidate_hash": candidate.code_hash,
            "checker_hash": version,
            "suite_hash": suite_identity,
        },
    )
