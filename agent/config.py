"""Strict YAML → environment → CLI settings. No runtime downloads."""

import hashlib
import json
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
import yaml

ROOT = Path(__file__).resolve().parent.parent


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Component(StrictModel):
    use: str
    params: dict = Field(default_factory=dict)


class ModelConfig(StrictModel):
    backend: Literal["openai", "mock", "replay"] = "openai"
    base_url: str = "http://127.0.0.1:8000/v1"
    model: str = ""
    api_key: str = ""
    timeout_s: float = Field(default=840, gt=0)
    max_model_len: int = Field(default=32768, gt=0)
    tokenizer_protocol: Literal["vllm", "llama_cpp"] = "vllm"
    structured_outputs: bool = True
    replay_path: str | None = None


class ModelProfile(StrictModel):
    """Optional per-role model override; disabled entries fall back to `model`."""

    enabled: bool = False
    model: str = ""
    base_url: str | None = None
    timeout_s: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def enabled_requires_model(self):
        if self.enabled and not self.model:
            raise ValueError("enabled model profile requires a model name")
        return self


class Services(StrictModel):
    model: ModelConfig = Field(default_factory=ModelConfig)
    profiles: dict[str, ModelProfile] = Field(default_factory=dict)


class Recording(StrictModel):
    level: Literal["basic", "full"] = "full"
    root: str | None = None
    burr_tracker: bool = False


class AuxiliaryBudget(StrictModel):
    planning_s: float = Field(default=150, gt=0)
    building_s: float = Field(default=240, gt=0)
    acceptance_s: float = Field(default=150, gt=0)
    recovery_s: float = Field(default=150, gt=0)
    minimum_request_s: float = Field(default=20, gt=0)
    acceptance_reserve_s: float = Field(default=60, ge=0)


class Runtime(StrictModel):
    deadline_s: float = Field(default=900, gt=0)
    reserve_s: float = Field(default=20, ge=0)
    max_steps: int = Field(default=1000, gt=0)
    recording: Recording = Field(default_factory=Recording)
    auxiliary: AuxiliaryBudget = Field(default_factory=AuxiliaryBudget)

    @model_validator(mode="after")
    def check_reserve(self):
        if self.reserve_s >= self.deadline_s:
            raise ValueError("reserve_s must be smaller than deadline_s")
        return self


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        extra="forbid",
        env_prefix="RTLAGENT_",
        env_nested_delimiter="__",
        allow_inf_nan=False,
    )
    workflow: str = "guided_verify"
    params: dict = Field(default_factory=dict)
    nodes: dict[str, Component] = Field(default_factory=dict)
    tools: dict[str, Component] = Field(default_factory=dict)
    plugins: list[str] = Field(default_factory=list)
    services: Services = Field(default_factory=Services)
    runtime: Runtime = Field(default_factory=Runtime)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        return env_settings, init_settings


class UniqueLoader(yaml.SafeLoader):
    def compose_node(self, parent, index):
        if self.check_event(yaml.AliasEvent):
            raise ValueError("YAML aliases are not supported")
        return super().compose_node(parent, index)


def _mapping(loader, node, deep=False):
    result = {}
    for key, value in node.value:
        name = loader.construct_object(key, deep=deep)
        if not isinstance(name, str) or name in result:
            raise ValueError(f"invalid or duplicate configuration key: {name!r}")
        result[name] = loader.construct_object(value, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def assign(data, dotted, value):
    keys = dotted.split(".")
    for key in keys[:-1]:
        data = data.setdefault(key, {})
    data[keys[-1]] = value


ENV_FIELDS = {
    "LLM_BACKEND": "services.model.backend",
    "LLM_BASE_URL": "services.model.base_url",
    "LLM_MODEL": "services.model.model",
    "LLM_API_KEY": "services.model.api_key",
    "AGENT_DEADLINE_S": "runtime.deadline_s",
    "AGENT_RESERVE_S": "runtime.reserve_s",
    "AGENT_RECORD_ROOT": "runtime.recording.root",
    "AGENT_RECORD_LEVEL": "runtime.recording.level",
}


def load_config(path=None, overrides=None):
    path = Path(path or ROOT / "config/guided_verify.yaml").resolve()
    raw = path.read_text(encoding="utf-8")
    data = yaml.load(raw, Loader=UniqueLoader) or {}
    if not isinstance(data, dict):
        raise ValueError("configuration must be a mapping")
    yaml_data = json.loads(json.dumps(data))
    environment = {
        k: v
        for k, v in os.environ.items()
        if k in ENV_FIELDS or k.startswith("RTLAGENT_")
    }
    for key, dotted in ENV_FIELDS.items():
        if key in environment:
            assign(data, dotted, environment[key])
    config = Config(**data)
    effective = config.model_dump()
    for dotted, value in (overrides or {}).items():
        assign(effective, dotted, value)
    # Validate changed roots without re-reading environment after CLI overrides.
    for root in {dotted.split(".")[0] for dotted in (overrides or {})}:
        annotation = Config.model_fields[root].annotation
        setattr(config, root, TypeAdapter(annotation).validate_python(effective[root]))
    for i, plugin in enumerate(config.plugins):
        candidate = Path(plugin)
        if not candidate.is_absolute():
            config.plugins[i] = str((path.parent / candidate).resolve())
    for obj, key in (
        (config.runtime.recording, "root"),
        (config.services.model, "replay_path"),
    ):
        value = getattr(obj, key)
        if value and not Path(value).is_absolute():
            setattr(obj, key, str((path.parent / value).resolve()))
    evidence = dict(
        path=str(path),
        yaml=yaml_data,
        environment=environment,
        cli=overrides or {},
        effective=config.model_dump(),
    )
    evidence["sha256"] = hashlib.sha256(
        json.dumps(config.model_dump(), sort_keys=True).encode()
    ).hexdigest()
    return config, evidence
