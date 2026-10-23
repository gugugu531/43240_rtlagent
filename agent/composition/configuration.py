"""Named input and expanded data configuration; classes load only in the worker."""
from __future__ import annotations
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
import copy
import hashlib
import json
import math
import os
import re
from agent.core.assembly import AssemblySpec
from agent.core.config import ModelConfig, ToolConfig
from agent.composition.validation import ConfigError, validate_assembly

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / 'config/presets/single_generate.yaml'

SCHEMA = {
    'schema_version': None, 'workflow': None, 'components': None,
    'nodes': None, 'tools': None, 'roles': None, 'params': None,
    'services': {'model': {'backend': None, 'model': None, 'base_url': None,
                           'api_key_env': None, 'timeout_s': None,
                           'tokenizer_dir': None, 'context_limit': None, 'strict_context': None,
                           'token_total_limit': None, 'token_output_limit': None, 'enable_thinking': None,
                           'tokenizer_sha256': None, 'template_sha256': None},
                 'tools': {'part': None, 'bin_dir': None, 'temp_dir': None, 'keep_work': None}},
    'runtime': {'deadline_s': None, 'reserve_s': None,
                'recording': {'level': None, 'root': None}},
    'experiment': {'tasks': {'root': None, 'ids': None, 'list': None, 'exclude': None},
                   'modes': None, 'samples': None, 'solve_jobs': None, 'metric_jobs': None,
                   'metrics': None, 'output_root': None, 'tag': None, 'judge_timeout_s': None},
}
DEFAULTS = {'schema_version': 2,
            'services': {'model': {'backend': 'mock', 'model': 'mock-model', 'base_url': '',
                                   'api_key_env': 'LLM_API_KEY', 'timeout_s': 180.0,
                                   'tokenizer_dir': None, 'context_limit': None, 'strict_context': False,
                                   'token_total_limit': None, 'token_output_limit': None, 'enable_thinking': None,
                                   'tokenizer_sha256': None, 'template_sha256': None},
                         'tools': {'part': 'xczu3eg-sbva484-1-e', 'bin_dir': None,
                                   'temp_dir': '/tmp', 'keep_work': False}},
            'runtime': {'deadline_s': 900.0, 'reserve_s': 20.0,
                        'recording': {'level': 'full', 'root': None}}}
ENV_FIELDS = {'LLM_BACKEND': 'services.model.backend', 'LLM_MODEL': 'services.model.model',
              'LLM_BASE_URL': 'services.model.base_url', 'LLM_TIMEOUT_S': 'services.model.timeout_s',
              'AGENT_DEADLINE_S': 'runtime.deadline_s',
              'AGENT_RESERVE_S': 'runtime.reserve_s', 'AGENT_RECORD_ROOT': 'runtime.recording.root',
              'AGENT_RECORD_LEVEL': 'runtime.recording.level',
              'RTL_PART': 'services.tools.part', 'VIVADO_BIN': 'services.tools.bin_dir',
              'AGENT_KEEP_WORK': 'services.tools.keep_work'}
PATH_FIELDS = {'services.model.tokenizer_dir', 'services.tools.bin_dir', 'services.tools.temp_dir', 'runtime.recording.root',
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


@dataclass(frozen=True)
class AgentConfig:
    assembly: AssemblySpec
    services: ServicesConfig
    runtime: RuntimeConfig


@dataclass(frozen=True)
class ResolvedConfig:
    agent: AgentConfig
    sources: Mapping[str, str]
    values: dict = field(repr=False)
    document: ConfigDocument = field(repr=False)

    @property
    def assembly(self):
        return self.agent.assembly

    def public_dict(self):
        assembly = self.assembly.public_dict()
        fingerprint = hashlib.sha256(json.dumps(assembly, sort_keys=True, ensure_ascii=False,
            separators=(',', ':'), allow_nan=False).encode()).hexdigest()
        return {'schema_version': 2, 'config_path': str(self.document.path) if self.document.path else None,
                'original': copy.deepcopy(self.document.data), 'effective': copy.deepcopy(self.values),
                'sources': dict(self.sources), 'assembly_sha256': fingerprint}

def _validate_keys(data, schema, prefix=''):
    if not isinstance(data, dict):
        raise ConfigError(f'{prefix or "config"} must be a mapping')
    for key, value in data.items():
        if not isinstance(key, str) or key not in schema:
            raise ConfigError(f'unknown field under {prefix or "config"}')
        if isinstance(schema[key], dict):
            _validate_keys(value, schema[key], f'{prefix}.{key}' if prefix else key)


def _assembly_data(data):
    components = data.get('components')
    if not isinstance(components, dict):
        raise ConfigError('components must be an ID mapping')
    rows = []
    for identity, component in components.items():
        if not isinstance(component, dict) or set(component) - {'class', 'kind', 'params', 'inject'}:
            raise ConfigError('unknown component field')
        if not {'class', 'kind'} <= set(component):
            raise ConfigError('component requires class and kind')
        rows.append(dict(id=identity, target=component['class'], kind=component['kind'],
                         params=copy.deepcopy(component.get('params', {})),
                         inject=copy.deepcopy(component.get('inject', {}))))
    return validate_assembly(dict(root_id=data.get('workflow'), components=rows))


def _document_assembly(data):
    _validate_keys(data, SCHEMA)
    version = data.get('schema_version', 3)
    if type(version) is not int or version not in (2, 3):
        raise ConfigError('schema_version must be 2 or 3')
    if version == 2:
        if set(data) & {'nodes', 'tools', 'roles', 'params'}:
            raise ConfigError('schema_version 2 requires expanded components only')
        # Saved experiments already contain exact class paths and bindings;
        # reloading them must not consult today's named-component defaults.
        return _assembly_data(data)
    if 'components' in data:
        raise ConfigError('schema_version 3 uses named selections instead of components')
    from agent.composition.named import expand_named
    return expand_named(data)


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
    _document_assembly(data)
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
    expanded = _document_assembly(document.data)
    env = os.environ if env is None else env
    if env.get('AGENT_WORKFLOW', '').strip():
        raise ConfigError('AGENT_WORKFLOW is unsupported; select a complete configuration with AGENT_CONFIG or --config')
    caller = Path(env.get("AGENT_CALLER_CWD", os.getcwd()))
    values = copy.deepcopy(DEFAULTS)
    values['workflow'] = expanded['root_id']
    # Persist a complete schema2 graph so reloading never consults named defaults.
    values['components'] = {row['id']: dict(kind=row['kind'], **{'class': row['target']},
                            params=copy.deepcopy(row['params']), inject=copy.deepcopy(row['inject']))
                            for row in expanded['components']}
    sources = {name: 'default' for name, _ in _flatten(values)}
    named_input = document.data.get('schema_version', 3) == 3
    assembly_source = 'component_metadata' if named_input else f'yaml:{document.path}'
    sources.update({name: assembly_source for name in sources if name.startswith('components.')})
    sources['workflow'] = f'yaml:{document.path}'
    base = document.path.parent if document.path else Path.cwd()
    for name, value in _flatten(document.data):
        if name.split('.')[0] in {'schema_version', 'workflow', 'components', 'nodes', 'tools', 'roles', 'params'}:
            continue
        if name in PATH_FIELDS and value is not None:
            if not isinstance(value, str) or not value:
                raise ConfigError(f'{name} must be a nonempty path')
            value = str((base / value).resolve())
        _set(values, name, copy.deepcopy(value))
        sources[name] = f'yaml:{document.path}'
    for key, name in ENV_FIELDS.items():
        if key not in env or not env[key].strip():
            continue
        value = env[key]
        if name.endswith('_s'):
            try: value = float(value)
            except ValueError: raise ConfigError(f'{key} must be numeric') from None
        if name.endswith('keep_work'):
            if value not in ('0', '1'): raise ConfigError(f'{key} must be 0 or 1')
            value = value == '1'
        if name in PATH_FIELDS: value = str((caller / value).resolve())
        _set(values, name, value); sources[name] = f'env:{key}'
    for key in ('AGENT_TMP', 'EDA_TMP', 'TRACK_TMP'):
        if env.get(key):
            _set(values, 'services.tools.temp_dir', str((caller / env[key]).resolve()))
            sources['services.tools.temp_dir'] = f'env:{key}'
            break
    allowed = {name for name, _ in _flatten(DEFAULTS)} | PATH_FIELDS
    for name, value in (overrides or RunOverrides()).values.items():
        if name not in allowed: raise ConfigError('unknown override field')
        if name in PATH_FIELDS and value is not None: value = str(Path(value).resolve())
        _set(values, name, value); sources[name] = 'cli'
    assembly_data = _assembly_data(values)
    for component in assembly_data['components']:
        sources[f"components.{component['id']}.params"] = assembly_source
    assembly = AssemblySpec.from_dict(assembly_data)
    values['components'] = {component.id: dict(kind=component.kind, **{'class': component.target},
                            params=component.public_dict()['params'], inject=component.public_dict()['inject'])
                            for component in assembly.components}
    for component in assembly_data['components']:
        explicit = (document.data.get('params', {}) if component['id'] == 'workflow' else {}) if named_input else component.get('params', {})
        explicit = dict(explicit)
        if named_input:
            explicit.update(document.data.get('roles', {}).get(component['id'], {}).get('params', {}))
        for field_name, _ in _flatten(component.get('params', {})):
            source = f'yaml:{document.path}' if field_name.split('.')[0] in explicit else assembly_source
            sources[f"components.{component['id']}.params.{field_name}"] = source
    m = values['services']['model']; t = values['services']['tools']; r = values['runtime']
    for key in ('backend', 'model', 'base_url', 'api_key_env'):
        if not isinstance(m[key], str): raise ConfigError(f'services.model.{key} must be a string')
    if not re.fullmatch(r'[A-Za-z_]\w*', m['api_key_env']): raise ConfigError('api_key_env must name an environment variable')
    positive(m['timeout_s'], 'services.model.timeout_s')
    positive(r['deadline_s'], 'runtime.deadline_s'); positive(r['reserve_s'], 'runtime.reserve_s', allow_zero=True)
    level = r['recording']['level']
    if level not in ('basic', 'full'): raise ConfigError('recording.level must be basic or full')
    for field_name in ('services.tools.bin_dir', 'services.tools.temp_dir', 'runtime.recording.root'):
        val = dict(_flatten(values))[field_name]
        if val is not None and (not isinstance(val, str) or not val): raise ConfigError(f'{field_name} must be a path')
    if t['temp_dir'] is None: raise ConfigError('tools.temp_dir must be a path')
    from urllib.parse import urlsplit
    if urlsplit(m['base_url']).query or urlsplit(m['base_url']).fragment:
        raise ConfigError('services.model.base_url must not contain query parameters or fragments')
    model = ModelConfig(m['backend'], m['model'], m['base_url'], env.get(m['api_key_env'], ''),
                        m['timeout_s'], baseline_model_name=env.get('MODEL_NAME', ''),
                        **{key: m[key] for key in ('tokenizer_dir', 'context_limit', 'strict_context',
                           'token_total_limit', 'token_output_limit', 'enable_thinking',
                           'tokenizer_sha256', 'template_sha256')})
    tools = ToolConfig(**t)
    runtime = RuntimeConfig(r['deadline_s'], r['reserve_s'], level,
                            Path(r['recording']['root']) if r['recording']['root'] else None)
    return ResolvedConfig(AgentConfig(assembly, ServicesConfig(model, tools, m['api_key_env']), runtime),
                          sources, values, document)
