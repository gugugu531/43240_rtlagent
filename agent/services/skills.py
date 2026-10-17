"""Read skill files and match their literal log signatures."""
from __future__ import annotations

import os
import re

from agent.core.skill import Skill


def load_skills(skill_dir: str) -> list[Skill]:
    skills: list[Skill] = []
    if not os.path.isdir(skill_dir):
        return skills
    # Selection takes the first matching entries, so directory sorting is
    # part of the prompt's reproducibility contract.
    for entry in sorted(os.listdir(skill_dir)):
        path = os.path.join(skill_dir, entry, "SKILL.md")
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                raw = fh.read()
        except OSError:
            continue
        meta, body = _split_front_matter(raw)
        skills.append(Skill(
            name=meta.get("name", entry),
            description=meta.get("description", ""),
            signatures=tuple(_bullet_code_items(body, "Log signatures")),
            trigger=_bullet_text(body, "Trigger"),
            body=body,
            path=path,
        ))
    return skills


def select(skills: list[Skill], *context: str, limit: int = 2) -> list[Skill]:
    # Signatures are literal substrings, not regular expressions or scores;
    # preserve loader order when more skills match than the requested limit.
    haystack = "\n".join(text.lower() for text in context if text)
    return [skill for skill in skills if skill.signatures and
            any(signature.lower() in haystack for signature in skill.signatures)][:limit]


def _bullet_code_items(body: str, label: str) -> list[str]:
    line = _bullet_text(body, label)
    return re.findall(r"`([^`]+)`", line)


def _bullet_text(body: str, label: str) -> str:
    match = re.search(rf"^\s*[-*]\s*\*\*{re.escape(label)}:?\*\*\s*(.+)$",
                      body, re.MULTILINE | re.IGNORECASE)
    return match.group(1).strip() if match else ""


def _split_front_matter(raw: str) -> tuple[dict, str]:
    """Parse the two scalar keys used by the bundled skill format."""
    if not raw.lstrip().startswith("---"):
        return {}, raw.strip()
    match = re.match(r"^\s*---\s*\n(.*?)\n---\s*\n?(.*)$", raw, re.DOTALL)
    if not match:
        return {}, raw.strip()
    head, body = match.group(1), match.group(2)
    meta: dict = {}
    key: str | None = None
    block: list[str] = []
    for line in head.splitlines():
        if not line.strip():
            continue
        if line[0] in " \t" and key:
            block.append(line.strip())
            continue
        # Finish the previous multiline value before reading the next key.
        if key and block:
            meta[key] = " ".join(block).strip()
            block = []
        key = None
        if ":" not in line:
            continue
        name, _, value = line.partition(":")
        name, value = name.strip(), value.strip()
        if value in ("|", ">", "|-", ">-", ""):
            key = name
        else:
            meta[name] = value.strip("\"'")
    if key and block:
        meta[key] = " ".join(block).strip()
    return meta, body.strip()
