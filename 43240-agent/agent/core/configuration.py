"""Strict data-only configuration, field provenance and shared run assembly."""
from __future__ import annotations
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
import copy
import math
import os
import re
from .config import ModelConfig, ToolConfig

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / 'config/default.yaml'


class ConfigError(ValueError):
    pass


SCHEMA = {
    'schema_version': None, 'imports': None,
    'workflow': {'type': None},
    'services': {'model': {'backend': None, 'model': None, 'base_url': None,
                           'api_key_env': None, 'timeout_s': None},
                 'tools': {'part': None, 'bin_dir': None, 'temp_dir': None, 'keep_work': None}},
    'runtime': {'deadline_s': None, 'reserve_s': None, 'save_candidates': None,
                'recording': {'level': None, 'root': None}},
    'experiment': {'tasks': {'root': None, 'ids': None, 'list': None, 'exclude': None},
                   'modes': None, 'samples': None, 'solve_jobs': None, 'metric_jobs': None,
                   'metrics': None, 'output_root': None, 'tag': None, 'judge_timeout_s': None},
}
DEFAULTS = {'schema_version': 1, 'imports': [], 'workflow': {'type': 'single_generate'},
            'services': {'model': {'backend': 'mock', 'model': 'mock-model', 'base_url': '',
                                   'api_key_env': 'LLM_API_KEY', 'timeout_s': 180.0},
                         'tools': {'part': 'xczu3eg-sbva484-1-e', 'bin_dir': None,
                                   'temp_dir': '/tmp', 'keep_work': False}},
            'runtime': {'deadline_s': 360.0, 'reserve_s': 20.0, 'save_candidates': False,
                        'recording': {'level': 'full', 'root': None}}}
ENV_FIELDS = {'LLM_BACKEND': 'services.model.backend', 'LLM_MODEL': 'services.model.model',
              'LLM_BASE_URL': 'services.model.base_url', 'LLM_TIMEOUT_S': 'services.model.timeout_s',
              'AGENT_WORKFLOW': 'workflow.type', 'AGENT_DEADLINE_S': 'runtime.deadline_s',
              'AGENT_RESERVE_S': 'runtime.reserve_s', 'AGENT_RECORD_ROOT': 'runtime.recording.root',
              'AGENT_RECORD_LEVEL': 'runtime.recording.level', 'AGENT_SAVE_CANDIDATES': 'runtime.save_candidates',
              'RTL_PART': 'services.tools.part', 'VIVADO_BIN': 'services.tools.bin_dir',
              'AGENT_KEEP_WORK': 'services.tools.keep_work'}
PATH_FIELDS = {'services.tools.bin_dir', 'services.tools.temp_dir', 'runtime.recording.root',
               'experiment.tasks.root', 'experiment.tasks.list', 'experiment.tasks.exclude',
               'experiment.output_root'}


@dataclass(frozen=True)
class ConfigDocument:
    path: Path | None
    data: dict = field(repr=False)


@dataclass(frozen=True)
class RunOverrides:
    values: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkflowConfig:
    type: str
    imports: tuple[str, ...] = ()


@dataclass(frozen=True)
class ServicesConfig:
    model: ModelConfig
    tools: ToolConfig
    api_key_env: str


@dataclass(frozen=True)
class RuntimeConfig:
    deadline_s: float
    reserve_s: float
    recording_level: str
    recording_root: Path | None
    save_candidates: bool


@dataclass(frozen=True)
class AgentConfig:
    workflow: WorkflowConfig
    services: ServicesConfig
    runtime: RuntimeConfig


@dataclass(frozen=True)
class ResolvedConfig:
    agent: AgentConfig
    sources: Mapping[str, str]
    values: dict = field(repr=False)
    document: ConfigDocument = field(repr=False)

    def public_dict(self):
        from ..recording.redaction import Redactor
        return Redactor([self.agent.services.model.api_key]).copy(
            {'schema_version': 1, 'config_path': str(self.document.path) if self.document.path else None,
             'original': self.document.data, 'effective': self.values, 'sources': dict(self.sources)})


def _validate_keys(data, schema, prefix=''):
    if not isinstance(data, dict):
        raise ConfigError(f'{prefix or "config"} must be a mapping')
    for key, value in data.items():
        if not isinstance(key, str) or key not in schema:
            raise ConfigError(f'unknown field under {prefix or "config"}')
        if isinstance(schema[key], dict):
            _validate_keys(value, schema[key], f'{prefix}.{key}' if prefix else key)


def load_config(path: Path | None = None) -> ConfigDocument:
    import yaml
    class Loader(yaml.SafeLoader):
        def compose_node(self, parent, index):
            if self.check_event(yaml.AliasEvent):
                raise ConfigError("configuration aliases are not supported")
            return super().compose_node(parent, index)
        def construct_mapping(self, node, deep=False):
            result = {}
            for key_node, value_node in node.value:
                key = self.construct_object(key_node, deep=deep)
                if not isinstance(key, str) or key in result:
                    raise ConfigError('configuration keys must be unique strings')
                result[key] = self.construct_object(value_node, deep=deep)
            return result
    path = Path(path or DEFAULT_CONFIG).resolve()
    try:
        if path.stat().st_size > 1024 * 1024:
            raise ConfigError('configuration exceeds size limit')
        data = yaml.load(path.read_text(encoding='utf-8'), Loader=Loader)
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f'cannot load configuration ({type(exc).__name__})') from None
    _validate_keys(data, SCHEMA)
    if type(data.get('schema_version')) is not int or data['schema_version'] != 1:
        raise ConfigError('schema_version must be 1')
    return ConfigDocument(path, data)


def _flatten(data, prefix=''):
    for key, value in data.items():
        name = f'{prefix}.{key}' if prefix else key
        if isinstance(value, dict):
            yield from _flatten(value, name)
        else:
            yield name, value


def _set(data, name, value):
    parts = name.split('.')
    for part in parts[:-1]:
        data = data.setdefault(part, {})
    data[parts[-1]] = value


def positive(value, name, *, allow_zero=False):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or (value == 0 and not allow_zero):
        raise ConfigError(f'{name} must be a finite {"nonnegative" if allow_zero else "positive"} number')
    return float(value)


def string_list(value, name):
    if not isinstance(value, list) or any(not isinstance(v, str) or not v for v in value):
        raise ConfigError(f'{name} must be a list of nonempty strings')
    if len(set(value)) != len(value):
        raise ConfigError(f'{name} must not contain duplicates')
    return tuple(value)


def resolve_config(document: ConfigDocument, *, env: Mapping[str, str] | None = None,
                   overrides: RunOverrides | None = None) -> ResolvedConfig:
    env = os.environ if env is None else env
    caller = Path(env.get("AGENT_CALLER_CWD", os.getcwd()))
    values = copy.deepcopy(DEFAULTS)
    sources = {name: 'default' for name, _ in _flatten(values)}
    base = document.path.parent if document.path else Path.cwd()
    for name, value in _flatten(document.data):
        if name in PATH_FIELDS and value is not None:
            if not isinstance(value, str) or not value:
                raise ConfigError(f'{name} must be a nonempty path')
            value = str((base / value).resolve())
        _set(values, name, value)
        sources[name] = f'yaml:{document.path}'
    for key, name in ENV_FIELDS.items():
        if key not in env or not env[key].strip():
            continue
        value = env[key]
        if name.endswith('_s'):
            try: value = float(value)
            except ValueError: raise ConfigError(f'{key} must be numeric') from None
        if name.endswith(('save_candidates', 'keep_work')):
            if value not in ('0', '1'): raise ConfigError(f'{key} must be 0 or 1')
            value = value == '1'
        if name in PATH_FIELDS: value = str((caller / value).resolve())
        _set(values, name, value); sources[name] = f'env:{key}'
    for key in ('AGENT_TMP', 'EDA_TMP', 'TRACK_TMP'):
        if env.get(key):
            _set(values, 'services.tools.temp_dir', str((caller / env[key]).resolve()))
            sources['services.tools.temp_dir'] = f'env:{key}'
            break
    allowed = {name for name, _ in _flatten(DEFAULTS)} | PATH_FIELDS | {'imports'}
    for name, value in (overrides or RunOverrides()).values.items():
        if name not in allowed: raise ConfigError('unknown override field')
        if name in PATH_FIELDS and value is not None: value = str(Path(value).resolve())
        _set(values, name, value); sources[name] = 'cli'
    imports = string_list(values['imports'], 'imports')
    if any(name.split('.')[0] in ('dev','selftest') for name in imports):
        raise ConfigError('runtime imports must not depend on development or judge modules')
    if any(not re.fullmatch(r'[A-Za-z_]\w*(\.[A-Za-z_]\w*)*', name) for name in imports):
        raise ConfigError('imports must name local Python modules')
    name = values['workflow']['type']
    if not isinstance(name, str) or not re.fullmatch(r'[a-z][a-z0-9_-]*', name):
        raise ConfigError('workflow.type must be a registered name')
    m = values['services']['model']; t = values['services']['tools']; r = values['runtime']
    for key in ('backend', 'model', 'base_url', 'api_key_env'):
        if not isinstance(m[key], str): raise ConfigError(f'services.model.{key} must be a string')
    if not re.fullmatch(r'[A-Za-z_]\w*', m['api_key_env']): raise ConfigError('api_key_env must name an environment variable')
    positive(m['timeout_s'], 'services.model.timeout_s')
    positive(r['deadline_s'], 'runtime.deadline_s'); positive(r['reserve_s'], 'runtime.reserve_s', allow_zero=True)
    if type(r['save_candidates']) is not bool: raise ConfigError('runtime.save_candidates must be boolean')
    level = r['recording']['level']
    if level not in ('basic', 'full'): raise ConfigError('recording.level must be basic or full')
    for field_name in ('services.tools.bin_dir', 'services.tools.temp_dir', 'runtime.recording.root'):
        val = dict(_flatten(values))[field_name]
        if val is not None and (not isinstance(val, str) or not val): raise ConfigError(f'{field_name} must be a path')
    if t['temp_dir'] is None: raise ConfigError('tools.temp_dir must be a path')
    from urllib.parse import urlsplit
    if urlsplit(m['base_url']).query or urlsplit(m['base_url']).fragment:
        raise ConfigError('services.model.base_url must not contain query parameters or fragments')
    model = ModelConfig(m['backend'], m['model'], m['base_url'], env.get(m['api_key_env'], ''), m['timeout_s'])
    tools = ToolConfig(**t)
    runtime = RuntimeConfig(r['deadline_s'], r['reserve_s'], level,
                            Path(r['recording']['root']) if r['recording']['root'] else None, r['save_candidates'])
    return ResolvedConfig(AgentConfig(WorkflowConfig(name, imports), ServicesConfig(model, tools, m['api_key_env']), runtime),
                          sources, values, document)


def build_run_spec(task, config: ResolvedConfig, *, output_dir: Path, started_at: float,
                   hard_deadline_s: float | None = None):
    from ..supervision import RunSpec
    from ..runner import RunOptions
    from ..recording.recorder import RecordingConfig
    runtime = config.agent.runtime
    deadline = runtime.deadline_s
    snapshot = config.public_dict()
    if hard_deadline_s is not None:
        deadline = min(deadline, positive(hard_deadline_s, 'hard_deadline_s'))
        snapshot['effective']['runtime']['deadline_s'] = deadline
        snapshot['sources']['runtime.deadline_s'] = 'http_hard_limit' if deadline < runtime.deadline_s else snapshot['sources']['runtime.deadline_s']
        snapshot['hard_deadline_s'] = hard_deadline_s
    return RunSpec(task, config.agent.workflow.type,
                   RunOptions(output_dir, deadline, runtime.reserve_s,
                              RecordingConfig(runtime.recording_level, runtime.recording_root), runtime.save_candidates),
                   import_modules=config.agent.workflow.imports, started_at=started_at,
                   model_config=config.agent.services.model, tool_config=config.agent.services.tools,
                   configuration=snapshot)
