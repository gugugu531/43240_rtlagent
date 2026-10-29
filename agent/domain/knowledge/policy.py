"""Knowledge modes and Skill admission, independent of workflow."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Mode = Literal["off", "shadow", "on"]


def route_skill_ids(kind, risks, sequential_skill="rtl-sequential-state-update"):
    selected = []
    mapping = {
        "fsm": "rtl-fsm-state-output",
        "sequential": sequential_skill,
        "protocol": sequential_skill,
        "combinational": "rtl-combinational-completeness",
    }
    if kind in mapping:
        selected.append(mapping[kind])
    if kind == "arithmetic" or set(risks) & {"width", "signed"}:
        selected.append("rtl-width-signed-arithmetic")
    return tuple(selected[:2])


class RetrievalOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    strategy: Literal["exact", "bm25", "dense", "hybrid"] = "exact"
    admission_policy: Literal["frozen-v1", "evidence-v1"] = "frozen-v1"
    fallback: Literal["empty", "exact"] = "empty"
    embedding_url: str = ""
    embedding_transport: Literal["http", "ssh"] = "http"
    embedding_ssh_host: str = ""
    embedding_ssh_port: int = Field(default=22, ge=1, le=65535)
    embedding_timeout_s: float = Field(default=2.0, gt=0, le=10)
    retrieve_k: int = Field(default=5, ge=1, le=32)
    inject_k: int = Field(default=1, ge=1, le=1)
    pre_generation: bool = False
    research_feedback: bool = False


def modes(skill_mode=None, rag_mode=None, *, skill_ids=(), rag=False):
    sm = skill_mode if skill_mode is not None else ("on" if skill_ids else "off")
    rm = rag_mode if rag_mode is not None else ("on" if rag else "off")
    if sm not in ("off", "shadow", "on") or rm not in ("off", "shadow", "on"):
        raise ValueError("knowledge mode must be off, shadow or on")
    if rag and rag_mode not in (None, "on"):
        raise ValueError("legacy rag=true conflicts with rag_mode")
    return sm, rm


def select_skills(assets, ids, phases, *, automatic=False):
    if len(ids) > 2 or len(set(ids)) != len(ids):
        raise ValueError("select at most two distinct skills")
    if not phases or not set(phases) <= {"generate", "repair"} or len(set(phases)) != len(phases):
        raise ValueError("invalid skill phases")
    selected, rejected, groups = [], [], set()
    for identity in ids:
        entry = assets["skills"].get(identity)
        reason = None
        if entry is None:
            reason = "unknown_skill"
        else:
            skill, _ = entry
            if skill.review_status == "frozen_rejected_fixed_ab":
                reason = "rejected_fixed_ab"
            elif automatic and skill.review_status != "frozen_default_fixed":
                reason = "not_approved_for_automatic_selection"
            elif skill.conflict_group in groups:
                reason = "conflicting_skill"
            elif not set(phases) <= set(skill.phases):
                reason = "unsupported_phase"
        if reason:
            if not automatic:
                raise ValueError(f"invalid explicit Skill {identity}: {reason}")
            rejected.append({"id": identity, "reason": reason})
        else:
            selected.append(identity)
            groups.add(skill.conflict_group)
    return selected, rejected


def assert_automatic_skill_allowed(identity):
    from .assets import load_assets

    _, rejected = select_skills(
        load_assets(skills=True), [identity], ["generate", "repair"], automatic=True
    )
    if rejected:
        raise ValueError(f"invalid automatic Skill {identity}: {rejected[0]['reason']}")


def validate_selection(params, *, automatic=False):
    """Validate graph-construction options without reading knowledge locks."""
    from .assets import load_assets

    ids = params.get("skill_ids", [])
    sm, rm = modes(
        params.get("skill_mode"),
        params.get("rag_mode"),
        skill_ids=ids,
        rag=params.get("rag", False),
    )
    options = RetrievalOptions.model_validate(params.get("retrieval", {}))
    if rm != "off" and options.strategy not in ("bm25", "dense", "hybrid"):
        raise ValueError("research_requires_bm25_dense_or_hybrid")
    if options.strategy in ("dense", "hybrid") and not options.embedding_url:
        raise ValueError("dense_retrieval_requires_embedding_url")
    budget = params.get("knowledge_max_tokens", 2048)
    if type(budget) is not int or not 0 <= budget <= 8192:
        raise ValueError("knowledge_max_tokens must be in 0..8192")
    select_skills({"skills": {}}, [], params.get("skill_phases", ["generate", "repair"]))
    if ids and sm != "off":
        select_skills(
            load_assets(skills=True),
            ids,
            params.get("skill_phases", ["generate", "repair"]),
            automatic=automatic,
        )
