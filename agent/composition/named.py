"""Read literal component declarations and expand named choices without importing code."""
from __future__ import annotations

import ast
import copy
from dataclasses import dataclass
import json
from pathlib import Path

from agent.composition.validation import (ConfigError, DEPENDENCY_KINDS, IDENTIFIER,
                                          ROLE_PACKAGES, validate_assembly)


@dataclass(frozen=True)
class Declaration:
    name: str
    kind: str
    target: str
    roles: tuple[str, ...]
    defaults: dict


def _identifier(value):
    return isinstance(value, str) and IDENTIFIER.fullmatch(value) is not None


def _parameters(value):
    if not isinstance(value, dict) or any(not isinstance(key, str) or not key.isidentifier() for key in value):
        raise ConfigError('component default params must be a parameter mapping')
    try:
        json.dumps(value, allow_nan=False)
    except (ValueError, TypeError):
        raise ConfigError('component default params must contain finite JSON data') from None


def _literal(node):
    # Python permits repeated dict keys; metadata treats them as configuration errors.
    for descendant in ast.walk(node):
        if isinstance(descendant, ast.Dict):
            keys = []
            for key in descendant.keys:
                value = ast.literal_eval(key)
                if any(type(value) is type(previous) and value == previous for previous in keys):
                    raise ConfigError('component metadata mappings must have unique keys')
                keys.append(value)
    return ast.literal_eval(node)


def discover(root: Path | None = None) -> dict[str, Declaration]:
    """Only class-local literals are read; imports and constructors stay in the worker."""
    root = root or Path(__file__).resolve().parents[2]
    found = {}
    for kind, package in ROLE_PACKAGES.items():
        directory = root.joinpath(*package.split('.'))
        for path in sorted(directory.rglob('*.py')):
            if path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent.is_relative_to(directory)) or not path.resolve().is_relative_to(directory.resolve()):
                raise ConfigError('component declaration must stay inside its responsibility package')
            try:
                tree = ast.parse(path.read_text(encoding='utf-8'))
            except (OSError, SyntaxError, UnicodeError):
                raise ConfigError('cannot parse component declaration') from None
            for cls in tree.body:
                if not isinstance(cls, ast.ClassDef):
                    continue
                # Read only this class's literals: importing bases or evaluating
                # expressions here would run component code before supervision.
                fields = {}
                for statement in cls.body:
                    targets = statement.targets if isinstance(statement, ast.Assign) else (
                        [statement.target] if isinstance(statement, ast.AnnAssign) else [])
                    for target in targets:
                        if isinstance(target, ast.Name) and target.id in (
                                'component_name', 'assembly_roles', 'assembly_defaults'):
                            if target.id in fields:
                                raise ConfigError('component metadata must be declared once')
                            try:
                                fields[target.id] = _literal(statement.value)
                            except (ValueError, TypeError, SyntaxError):
                                raise ConfigError('component metadata must use Python literals') from None
                if 'component_name' not in fields:
                    continue
                name = fields['component_name']
                if not _identifier(name) or name in found:
                    raise ConfigError('component names must be unique lowercase identifiers')
                roles, defaults = fields.get('assembly_roles'), fields.get('assembly_defaults')
                if not isinstance(roles, list) or not roles or any(not _identifier(role) for role in roles) or len(set(roles)) != len(roles):
                    raise ConfigError(f'{name}: assembly_roles must be unique role names')
                if not isinstance(defaults, dict) or set(defaults) != {'params', 'dependencies'}:
                    raise ConfigError(f'{name}: assembly_defaults requires params and dependencies')
                _parameters(defaults['params'])
                if not isinstance(defaults['dependencies'], dict):
                    raise ConfigError(f'{name}: default dependencies must be a mapping')
                for slot, edge in defaults['dependencies'].items():
                    if not isinstance(slot, str) or not slot.isidentifier() or not isinstance(edge, dict) or set(edge) - {'component', 'id', 'params', 'when'}:
                        raise ConfigError(f'{name}: invalid default dependency declaration')
                    if not {'component', 'id'} <= set(edge) or not _identifier(edge['component']) or not _identifier(edge['id']):
                        raise ConfigError(f'{name}: default dependency requires component and id')
                    _parameters(edge.get('params', {}))
                    when = edge.get('when', {})
                    _parameters(when)
                    if any(key not in defaults['params'] for key in when):
                        raise ConfigError(f'{name}: dependency condition requires a declared default parameter')
                parts = path.relative_to(root).with_suffix('').parts
                # A package's __init__.py is imported by its package name.
                module = '.'.join(parts[:-1] if parts[-1] == '__init__' else parts)
                found[name] = Declaration(name, kind, f'{module}:{cls.name}', tuple(roles), defaults)
    # Resolve references after scanning every file so filesystem order cannot
    # determine whether a declared default dependency is available.
    for declaration in found.values():
        for edge in declaration.defaults['dependencies'].values():
            child = found.get(edge['component'])
            if child is None or child.kind not in DEPENDENCY_KINDS[declaration.kind]:
                raise ConfigError(f'{declaration.name}: invalid default dependency responsibility')
            if edge['id'] not in child.roles:
                raise ConfigError(f'{declaration.name}: default dependency does not declare its role')
    return found


def expand_named(data: dict, *, declarations: dict[str, Declaration] | None = None) -> dict:
    declarations = discover() if declarations is None else declarations
    workflow = data.get('workflow')
    if not isinstance(workflow, str) or workflow not in declarations or declarations[workflow].kind != 'workflow':
        raise ConfigError('workflow must name a discovered workflow component')
    selected = {'node': [], 'tool': []}
    for kind, field in (('node', 'nodes'), ('tool', 'tools')):
        names = data.get(field, [])
        if not isinstance(names, list) or any(not isinstance(name, str) for name in names):
            raise ConfigError(f'{field} must be a list of component names')
        if len(set(names)) != len(names):
            raise ConfigError(f'{field} must not contain duplicate selections')
        for name in names:
            if name not in declarations or declarations[name].kind != kind:
                raise ConfigError(f'{field} contains an unknown component selection')
        selected[kind] = names
    overrides = data.get('roles', {})
    if not isinstance(overrides, dict) or any(not _identifier(key) for key in overrides):
        raise ConfigError('roles must map component IDs to overrides')
    for override in overrides.values():
        if not isinstance(override, dict) or set(override) - {'component', 'params'}:
            raise ConfigError('role override supports component and params')
        _parameters(override.get('params', {}))
        if 'component' in override and (not isinstance(override['component'], str) or override['component'] not in declarations):
            raise ConfigError('role override contains an unknown component selection')
    _parameters(data.get('params', {}))
    used, used_roles, rows, active = set(), set(), {}, set()

    def build(identity, name, parameters=None):
        default = declarations[name]
        choices = [item for item in selected.get(default.kind, []) if identity in declarations[item].roles]
        override = overrides.get(identity, {})
        if identity in overrides:
            used_roles.add(identity)
        # A role override is explicit; a name list must identify one choice
        # without using list order as an implicit priority.
        if 'component' in override:
            name = override['component']
        elif len(choices) > 1:
            raise ConfigError(f'{identity}: ambiguous named component selections')
        elif choices:
            name = choices[0]
        declaration = declarations[name]
        if declaration.kind != default.kind or (identity != 'workflow' and identity not in declaration.roles):
            raise ConfigError(f'{identity}: component does not support the dependency role')
        if name in choices:
            used.add(name)
        # Detect cycles by instance ID, not class name: the same class may
        # appear at multiple points in a finite dependency graph.
        if identity in active:
            raise ConfigError('named assembly contains a dependency cycle')
        params = copy.deepcopy(declaration.defaults['params'])
        # Explicit root params survive replacement; dependency context defaults do not.
        if identity == 'workflow' or name == default.name:
            params.update(copy.deepcopy(parameters or {}))
        params.update(copy.deepcopy(override.get('params', {})))
        row = dict(id=identity, target=declaration.target, kind=declaration.kind, params=params, inject={})
        if identity in rows:
            # Sharing an ID means sharing an instance, so all parents must
            # agree on its implementation and effective parameters.
            if rows[identity]['target'] != row['target'] or rows[identity]['params'] != params:
                raise ConfigError(f'{identity}: conflicting defaults for a shared component ID')
            return identity
        if len(rows) >= 512:
            raise ConfigError('named assembly exceeds component limit')
        rows[identity] = row
        active.add(identity)
        for slot, edge in declaration.defaults['dependencies'].items():
            # Evaluate conditions after overrides; type checks keep True from
            # matching 1 even though Python considers those values equal.
            if not all(type(params.get(key)) is type(value) and params.get(key) == value for key, value in edge.get('when', {}).items()):
                continue
            row['inject'][slot] = build(edge['id'], edge['component'], edge.get('params'))
        active.remove(identity)
        return identity

    build('workflow', workflow, data.get('params'))
    # Reject ineffective selections instead of silently accepting a typo or
    # an override for a dependency disabled by its parent's final parameters.
    if used != set(selected['node'] + selected['tool']):
        raise ConfigError('named assembly contains unused component selections')
    if used_roles != set(overrides):
        raise ConfigError('named assembly contains unused role overrides')
    return validate_assembly(dict(root_id='workflow', components=list(rows.values())))
