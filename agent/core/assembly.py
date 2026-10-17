"""Pure, serializable component assembly data; validation belongs to composition."""
from __future__ import annotations
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from agent.core.model import _freeze, _thaw


@dataclass(frozen=True)
class ComponentConfig:
    id: str
    target: str
    kind: str
    params: Mapping[str, Any] = field(default_factory=dict)
    inject: Mapping[str, str | tuple[str, ...]] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, 'params', _freeze(dict(self.params)))
        object.__setattr__(self, 'inject', _freeze(dict(self.inject)))

    @classmethod
    def from_dict(cls, value: dict) -> ComponentConfig:
        return cls(**value)

    def public_dict(self) -> dict:
        return dict(id=self.id, target=self.target, kind=self.kind,
                    params=_thaw(self.params), inject=_thaw(self.inject))

    def __reduce__(self):
        return (type(self).from_dict, (self.public_dict(),))


@dataclass(frozen=True)
class AssemblySpec:
    root_id: str
    components: tuple[ComponentConfig, ...]

    def __post_init__(self):
        object.__setattr__(self, 'components', tuple(self.components))

    @classmethod
    def from_dict(cls, value: dict) -> AssemblySpec:
        return cls(value['root_id'], tuple(ComponentConfig.from_dict(item)
                                          for item in value['components']))

    def public_dict(self) -> dict:
        return dict(root_id=self.root_id, components=[item.public_dict() for item in self.components])
