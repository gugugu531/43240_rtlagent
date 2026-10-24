"""Strict, task-local snapshots of the packaged knowledge assets.

Adapted from the MIT-licensed task_skills/knowledge loaders at
wyc888-crypto/amd-rtlagent-prompt-engineering, fb1c2803e5db0f32b59b9ba9100877f2a0d26412.
"""

import hashlib
import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

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
    id: Identifier
    version: Text
    description: Text
    task_types: Texts
    subtypes: Texts
    phases: Annotated[list[Phase], Field(min_length=1)]
    conflict_group: Identifier
    resource: Resource
    source: Resource
    review_status: Literal["reviewed_not_model_validated"]


class Catalog(Strict):
    schema_version: Literal[1]
    source: Origin
    skills: Annotated[list[Skill], Field(min_length=1, max_length=32)]


class Trigger(Strict):
    codes: Annotated[list[Annotated[str, Field(pattern=r"^(VRFC|SYNTH) \d+-\d+$")]], Field(min_length=1)]
    tools: Annotated[list[Literal["xvlog", "xelab", "vivado"]], Field(min_length=1)]
    versions: Annotated[list[Annotated[str, Field(pattern=r"^\d{4}\.\d+$")]], Field(min_length=1)]
    message_contains_any: Texts


class CardOrigin(Resource):
    card_ids: Texts


class Card(Strict):
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
    review_status: Literal["reviewed_not_model_validated"]


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
    relative = Path(relative)
    if relative.is_absolute() or any(p in ("..", ".") for p in relative.parts):
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


def load_assets(*, skills=False, rag=False, root=ROOT):
    """Load only enabled asset kinds, once per task; never read task directories."""
    result = {"skills": {}, "cards": [], "resources": {}}
    for enabled, path, model, field in (
        (skills, "knowledge/catalog.json", Catalog, "skills"),
        (rag, "knowledge/cards.json", Corpus, "cards"),
    ):
        if not enabled:
            continue
        raw = read_resource(path, root=root)
        data = json.loads(raw, object_pairs_hook=_unique)
        if type(data.get("schema_version")) is not int:
            raise ValueError("knowledge schema_version must be an integer")
        manifest = model.model_validate(data)
        result["resources"][path] = sha256(raw)
        items = getattr(manifest, field)
        if len({item.id for item in items}) != len(items):
            raise ValueError("duplicate knowledge resource id")
        if field == "cards":
            result[field] = items
            continue
        for item in items:
            if item.resource.path != f"skill/{item.id}/skill.md":
                raise ValueError("skill resource path does not match its id")
            raw = read_resource(item.resource.path, root=root, limit=32_768)
            if sha256(raw) != item.resource.sha256:
                raise ValueError("skill resource hash mismatch: " + item.id)
            text = raw.decode("utf-8")
            if not text.startswith("---\n") or "\n---\n" not in text[4:]:
                raise ValueError("invalid skill frontmatter: " + item.id)
            head, body = text[4:].split("\n---\n", 1)
            meta = yaml.load(head, Loader=UniqueLoader)
            if meta != {"name": item.id, "description": item.description} or not body.strip():
                raise ValueError("skill frontmatter does not match catalog: " + item.id)
            result["skills"][item.id] = (item, body.strip())
            result["resources"][item.resource.path] = item.resource.sha256
    return result


def card_text(card):
    lines = [f"[知识卡 {card.id}@{card.version}] {card.title}"]
    for label, values in (
        ("适用", card.applies_when), ("不适用", card.not_applicable_when),
        ("方法", card.guidance), ("验证", card.verification),
        ("禁止", card.hard_negatives),
    ):
        lines.append(label + "：\n" + "\n".join("- " + value for value in values))
    lines.append("本卡为通用方法，未证明当前候选功能正确；必须重新执行检查。")
    return "\n".join(lines)
