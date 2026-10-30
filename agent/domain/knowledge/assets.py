"""Strict, task-local snapshots of the packaged knowledge assets.

Adapted from the MIT-licensed task_skills/knowledge loaders at
wyc888-crypto/amd-rtlagent-prompt-engineering, fb1c2803e5db0f32b59b9ba9100877f2a0d26412.
"""

import hashlib
import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agent.config import ROOT, UniqueLoader
import yaml

Text = Annotated[str, Field(min_length=1)]
Identifier = Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]*$")]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Texts = Annotated[list[Text], Field(min_length=1)]
Phase = Literal["generate", "repair"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Origin(Strict):
    repository: Text
    commit: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
    license: Literal["MIT"]


class Resource(Strict):
    path: Text
    sha256: Digest


class Skill(Strict):
    id: Identifier = Field(alias="name")
    description: Text
    phases: Annotated[list[Phase], Field(min_length=1)] = Field(
        default_factory=lambda: ["generate", "repair"]
    )
    conflict_group: Identifier | None = None
    review_status: Literal[
        "frozen_default_fixed",
        "frozen_candidate_not_default",
        "frozen_rejected_fixed_ab",
    ] = "frozen_default_fixed"

    @field_validator("description")
    @classmethod
    def nonblank_description(cls, value):
        if not value.strip():
            raise ValueError("skill description must not be blank")
        return value

    @field_validator("phases")
    @classmethod
    def distinct_phases(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("skill phases must be distinct")
        return value


class Trigger(Strict):
    codes: Annotated[list[Annotated[str, Field(pattern=r"^(VRFC|SYNTH) \d+-\d+$")]], Field(min_length=1)]
    tools: Annotated[list[Literal["xvlog", "xelab", "vivado"]], Field(min_length=1)]
    versions: Annotated[list[Annotated[str, Field(pattern=r"^\d{4}\.\d+$")]], Field(min_length=1)]
    message_contains_any: Texts


class CardOrigin(Resource):
    card_ids: Texts


class Card(Strict):
    language: Literal['en']
    id: Identifier
    version: Text
    title: Text
    phases: Annotated[list[Literal["repair"]], Field(min_length=1)]
    triggers: Annotated[list[Trigger], Field(min_length=1)]
    applies_when: Texts
    not_applicable_when: Texts
    guidance: Texts
    verification: Texts
    hard_negatives: Texts
    conflict_groups: list[Identifier]
    source: CardOrigin
    review_status: Literal["frozen_exact_shadow_not_default"]


class Corpus(Strict):
    schema_version: Literal[1]
    source: Origin
    cards: Annotated[list[Card], Field(min_length=1, max_length=64)]


def sha256(data):
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode()).hexdigest()


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate knowledge field: " + key)
        result[key] = value
    return result


def read_resource(relative, *, root=ROOT, limit=1_048_576):
    """Only normal files inside the package; reject symlinked ancestors too."""
    root = Path(root).resolve()
    raw_path = str(relative)
    relative = Path(relative)
    if relative.is_absolute() or any(p in ("", "..", ".") for p in raw_path.split("/")):
        raise ValueError("knowledge path must stay inside the package")
    path = root / relative
    if any(p.is_symlink() for p in (path, *path.parents) if p != root and p.is_relative_to(root)):
        raise ValueError("knowledge resource cannot be a symlink")
    if not path.is_file() or not path.resolve().is_relative_to(root):
        raise ValueError("knowledge resource is missing or outside the package")
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError("knowledge resource exceeds size limit")
    return data


def _load_skills(root, result):
    root = Path(root).resolve()
    directory = root / "skill"
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("skill directory must be a normal package directory")
    for folder in sorted(directory.iterdir(), key=lambda path: path.name):
        if folder.is_symlink():
            raise ValueError("skill directory entry cannot be a symlink")
        if not folder.is_dir():
            continue
        candidates = (folder / "skill.md", folder / "SKILL.md")
        for candidate in candidates:
            if candidate.is_symlink():
                raise ValueError("skill resource cannot be a symlink")
            if candidate.exists() and not candidate.is_file():
                raise ValueError("skill resource must be a normal file")
        path = next((candidate for candidate in candidates if candidate.is_file()), None)
        if path is None:
            continue
        relative = path.relative_to(root).as_posix()
        raw = read_resource(relative, root=root, limit=32_768)
        text = raw.decode("utf-8")
        if not text.startswith("---\n") or "\n---\n" not in text[4:]:
            raise ValueError("invalid skill frontmatter: " + relative)
        head, body = text[4:].split("\n---\n", 1)
        try:
            meta = yaml.load(head, Loader=UniqueLoader)
        except yaml.YAMLError as exc:
            raise ValueError("invalid skill frontmatter: " + relative) from exc
        skill = Skill.model_validate(meta)
        if skill.id != folder.name:
            raise ValueError("skill name must match its directory: " + relative)
        if not body.strip():
            raise ValueError("skill body must not be empty: " + relative)
        if skill.id in result["skills"]:
            raise ValueError("duplicate skill name: " + skill.id)
        result["skills"][skill.id] = (skill, body.strip())
        result["resources"][relative] = sha256(raw)


def load_assets(*, skills=False, rag=False, root=ROOT):
    """Snapshot enabled assets afresh; skills are discovered in direct subdirectories."""
    result = {"skills": {}, "cards": [], "resources": {}}
    if skills:
        _load_skills(root, result)
    if rag:
        path = "knowledge/cards.json"
        raw = read_resource(path, root=root)
        data = json.loads(raw, object_pairs_hook=_unique)
        if type(data.get("schema_version")) is not int:
            raise ValueError("knowledge schema_version must be an integer")
        corpus = Corpus.model_validate(data)
        if len({card.id for card in corpus.cards}) != len(corpus.cards):
            raise ValueError("duplicate knowledge resource id")
        result["cards"] = corpus.cards
        result["resources"][path] = sha256(raw)
    return result


def card_text(card):
    lines = [f"[Knowledge Card {card.id}@{card.version}] {card.title}"]
    for label, values in (
        ("Use when", card.applies_when), ("Do not use when", card.not_applicable_when),
        ("Method", card.guidance), ("Verify", card.verification),
        ("Forbidden / hard negatives", card.hard_negatives),
    ):
        lines.append(label + ":\n" + "\n".join("- " + value for value in values))
    lines.append("This card provides a general method, not proof that the current candidate is functionally correct. Re-run the checks.")
    return "\n".join(lines)
