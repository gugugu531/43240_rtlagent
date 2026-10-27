"""Structured context bundle and prompt-assembly evidence.

Packing itself stays in `agent.knowledge.context` so there is only one budget
and deduplication implementation. This module turns the packer's report into
an explicit assembly record: which sections were kept or dropped, the message
hash actually sent, and the token estimate.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import uuid


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class ContextBundle:
    bundle_id: str
    sections: tuple[dict, ...]

    def public_dict(self):
        return {"bundle_id": self.bundle_id, "sections": list(self.sections)}

    @classmethod
    def for_task(cls, task, route=None):
        prompt = getattr(task, "prompt", "") or ""
        sections = [
            {
                "id": "task",
                "kind": "task",
                "trust": "host",
                "content": {
                    "task_id": getattr(task, "id", ""),
                    "top": getattr(task, "top", ""),
                    "prompt_sha256": hashlib.sha256(
                        prompt.encode("utf-8")
                    ).hexdigest(),
                    "prompt_bytes": len(prompt.encode("utf-8")),
                },
            },
            {
                "id": "interface",
                "kind": "interface",
                "trust": "host",
                "content": getattr(task, "expected_interface", None)
                .public_dict()
                if getattr(task, "expected_interface", None) is not None
                else {},
            },
        ]
        if route is not None:
            sections.append(
                {
                    "id": "route",
                    "kind": "route",
                    "trust": "host",
                    "content": route.public_dict()
                    if hasattr(route, "public_dict")
                    else dict(route),
                }
            )
        return cls(uuid.uuid4().hex, tuple(sections))


@dataclass(frozen=True)
class PromptAssembly:
    stage: str
    template: str
    assembly_id: str
    messages_sha256: str
    required_messages_sha256: str | None
    kept: tuple[str, ...]
    dropped: tuple[str, ...]
    tokens: int | None

    def public_dict(self):
        return {
            "stage": self.stage,
            "template": self.template,
            "assembly_id": self.assembly_id,
            "messages_sha256": self.messages_sha256,
            "required_messages_sha256": self.required_messages_sha256,
            "kept": list(self.kept),
            "dropped": list(self.dropped),
            "tokens": self.tokens,
        }


def assembly_from_report(stage, messages, report):
    report = report or {}
    pieces = report.get("pieces") or []
    kept = tuple(report.get("sent") or ())
    dropped = tuple(
        piece.get("id") for piece in pieces
        if piece.get("id") and piece.get("status") != "included"
    )
    return PromptAssembly(
        stage=stage,
        template="repair.j2",
        assembly_id=report.get("assembly_id") or uuid.uuid4().hex,
        messages_sha256=report.get("messages_sha256") or _digest(messages),
        required_messages_sha256=report.get("required_messages_sha256"),
        kept=kept,
        dropped=dropped,
        tokens=report.get("packed_tokens"),
    )


def record_assembly(ctx, stage, messages, report):
    """Emit one prompt-assembly event and artifact; never rewrites messages."""
    assembly = assembly_from_report(stage, messages, report)
    payload = assembly.public_dict()
    ctx.record.emit("prompt", "assembly", **payload)
    ctx.record.write_json(f"prompt/{assembly.assembly_id}.json", payload)
    return assembly
