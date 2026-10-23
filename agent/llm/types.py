"""Shared model values, errors and configuration lookup; no client dependency."""

from dataclasses import asdict, dataclass, field


class ModelError(RuntimeError):
    def __init__(
        self, message: str, *, kind: str = "response", call_id: str | None = None
    ):
        super().__init__(message)
        self.kind, self.call_id = kind, call_id


@dataclass(frozen=True)
class Reply:
    call_id: str
    content: str
    finish_reason: str | None
    tokens_in: int | None
    tokens_out: int | None
    tool_calls: list[dict] = field(default_factory=list)
    reasoning: dict = field(default_factory=dict)
    model: str | None = None

    def model_dump(self, *, mode="python"):
        return asdict(self)


def _get(config, name, default=None):
    return (
        config.get(name, default)
        if isinstance(config, dict)
        else getattr(config, name, default)
    )
