"""Pure run boundary and conversion from a resolved component configuration."""
from __future__ import annotations
from dataclasses import dataclass, field
import json
import math
from pathlib import Path
from agent.core.assembly import AssemblySpec
from agent.core.config import ModelConfig, ToolConfig
from agent.core.task import TaskSpec
from agent.recording.recorder import RecordingConfig


@dataclass(frozen=True)
class RunOptions:
    output_dir: Path
    deadline_s: float = 900.0
    reserve_s: float = 20.0
    recording: RecordingConfig = field(default_factory=RecordingConfig)
    run_id: str | None = None


@dataclass(frozen=True)
class RunSpec:
    task: TaskSpec
    assembly: AssemblySpec
    options: RunOptions
    started_at: float | None = None
    model_config: ModelConfig | None = None
    tool_config: ToolConfig | None = None
    configuration: dict = field(default_factory=dict)

    def __post_init__(self):
        json.dumps(self.assembly.public_dict(), allow_nan=False)


def build_run_spec(task, config, output_dir, started_at=None, hard_deadline_s=None) -> RunSpec:
    runtime = config.agent.runtime
    deadline = runtime.deadline_s
    snapshot = config.public_dict()
    if hard_deadline_s is not None:
        if type(hard_deadline_s) not in (int, float) or not math.isfinite(hard_deadline_s) or hard_deadline_s <= 0:
            raise ValueError('hard_deadline_s must be positive and finite')
        deadline = min(deadline, hard_deadline_s)
        snapshot['effective']['runtime']['deadline_s'] = deadline
        if deadline < runtime.deadline_s:
            snapshot['sources']['runtime.deadline_s'] = 'http_hard_limit'
        snapshot['hard_deadline_s'] = hard_deadline_s
    options = RunOptions(Path(output_dir), deadline, runtime.reserve_s,
                         RecordingConfig(runtime.recording_level, runtime.recording_root))
    return RunSpec(task, config.agent.assembly, options, started_at,
                   config.agent.services.model, config.agent.services.tools, snapshot)
