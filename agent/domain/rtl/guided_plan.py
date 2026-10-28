"""Flat planner output for guided_verify; no nested objects or free-form plans."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re




class PlanError(ValueError):
    pass


@dataclass(frozen=True)
class Plan:
    method: str
    skills: tuple[str, ...]
    knowledge: tuple[str, ...]
    focus: tuple[str, ...]
    reason: str

    def public_dict(self):
        return {
            "method": self.method,
            "skills": list(self.skills),
            "knowledge": list(self.knowledge),
            "focus": list(self.focus),
            "reason": self.reason,
        }


def _strip_fence(text):
    text = text.strip()
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        return "\n".join(lines[1:-1]).strip()
    return text


def _features(task):
    """Neutral feature summary: avoid presenting an RTL coding request to a coder model."""
    ports = task.expected_interface.ports
    names = {port.name.casefold() for port in ports}
    text = task.prompt.casefold()
    words = set(re.findall(r"[a-z][a-z0-9_+-]*", text))
    clock = [p for p in ports if p.direction == "input" and p.width == 1 and re.search(r"(^|_)(clk|clock)$", p.name.casefold())]
    return {
        "sequential": bool(clock),
        "single_clock": len(clock) == 1,
        "reset": any("reset" in n or "rst" in n for n in names),
        "load": "load" in names,
        "enable": any("en" in n for n in names),
        "shift": any(word in words for word in ("shift", "rotate", "lfsr")),
        "counter": "counter" in words,
        "fsm": any(word in words for word in ("fsm", "state", "sequence")),
        "protocol": any(word in words for word in ("valid", "ready", "handshake", "fifo")),
        "signed": "signed" in text,
        "ports": [
            {"name": port.name, "direction": port.direction, "width": port.width}
            for port in ports
        ],
        "keywords": sorted(
            word for word in words
            if word in {"reset", "load", "enable", "shift", "rotate", "counter", "fsm", "state",
                        "sequence", "valid", "ready", "fifo", "signed", "hold", "priority",
                        "overflow", "saturate", "latency", "pipeline"}
        ),
    }


def plan_request(task, skills, cards):
    """Small-model request: select ids only; host restores the exact texts."""
    skill_rows = [
        {"id": item, "description": desc} for item, desc in skills
    ]
    card_rows = [
        {"id": card["card_id"], "title": card.get("title", "")}
        for card in cards
    ]
    system = (
        "Choose a checking method and optional public method material. "
        "Return only flat key=value lines. Do not use JSON, Markdown or prose. "
        "Allowed keys: method, skills, knowledge, focus, reason. "
        "method must be structural or table. Use table only when the public task "
        "defines observable behavior for a combinational block or a single-clock block. "
        "skills must come from the supplied ids; knowledge must come from the supplied card ids. "
        "Do not invent requirements or expected values."
    )
    user = (
        "Abstract features and available material:\n"
        + "\n\nFeatures:\n"
        + json.dumps(_features(task), ensure_ascii=False, separators=(",", ":"))
        + "\n\nAvailable skills:\n"
        + json.dumps(skill_rows, ensure_ascii=False, separators=(",", ":"))
        + "\n\nAvailable knowledge cards:\n"
        + json.dumps(card_rows, ensure_ascii=False, separators=(",", ":"))
        + "\n\nOutput exactly this shape, one key per line:\n"
        "method=table\n"
        "skills=<comma-separated ids or empty>\n"
        "knowledge=<comma-separated ids or empty>\n"
        "focus=<short phrases separated by | or empty>\n"
        "reason=<one short sentence>"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def parse_plan(text, *, skill_ids, card_ids, max_skills=2, max_cards=3,
               max_focus=4):
    text = _strip_fence(text)
    if not text or len(text) > 8192:
        raise PlanError("plan output missing or too large")
    values, seen = {}, set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if "=" not in line:
            raise PlanError("plan lines must be key=value")
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if key not in {"method", "skills", "knowledge", "focus", "reason"}:
            raise PlanError("unknown plan key: " + key)
        if key in seen:
            raise PlanError("duplicate plan key: " + key)
        seen.add(key)
        values[key] = value
    method = values.get("method")
    if method not in ("structural", "table"):
        raise PlanError("method must be structural or table")
    def split(key):
        value = values.get(key, "")
        return tuple(item.strip() for item in value.split(",") if item.strip())
    allowed_skills = set(skill_ids)
    allowed_cards = set(card_ids)
    # Drop unknown or duplicate ids before applying the configured limits. A
    # small model may confuse skill ids with knowledge ids; that must not
    # invalidate an otherwise usable method decision.
    skills = tuple(dict.fromkeys(
        item for item in split("skills") if item in allowed_skills
    ))
    knowledge = tuple(dict.fromkeys(
        item for item in split("knowledge") if item in allowed_cards
    ))
    # Cap rather than reject: a small model may select one item too many.
    skills = skills[:max_skills]
    knowledge = knowledge[:max_cards]
    focus = tuple(
        item.strip()
        for item in re.split(r"[|,]", values.get("focus", ""))
        if item.strip()
    )
    if len(focus) > max_focus or any(len(item) > 80 for item in focus):
        raise PlanError("invalid focus list")
    reason = values.get("reason", "")
    if len(reason) > 500:
        raise PlanError("reason too long")
    return Plan(method, skills, knowledge, focus, reason)
