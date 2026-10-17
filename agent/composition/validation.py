"""Validate assembly data without importing component implementations."""
from __future__ import annotations

import json
import re


class ConfigError(ValueError):
    pass


ROLE_PACKAGES = {'workflow': 'agent.workflows', 'node': 'agent.nodes', 'tool': 'agent.tools'}
DEPENDENCY_KINDS = {'workflow': {'workflow', 'node'}, 'node': {'node', 'tool'}, 'tool': {'tool'}}
IDENTIFIER = re.compile(r'[a-z][a-z0-9_-]*')
TARGET = re.compile(r'(agent(?:\.[a-z_][a-z0-9_]*)+):([A-Za-z_]\w*)')


def references(inject):
    for value in inject.values():
        yield from value if isinstance(value, (list, tuple)) else (value,)


def validate_assembly(data):
    if not isinstance(data, dict) or set(data) != {'root_id', 'components'}:
        raise ConfigError('assembly requires root_id and components')
    rows, root = data['components'], data['root_id']
    if not isinstance(rows, list) or not rows or len(rows) > 512:
        raise ConfigError('assembly.components must be a nonempty bounded list')
    components = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) - {'id', 'target', 'kind', 'params', 'inject'}:
            raise ConfigError('unknown component field')
        if not {'id', 'target', 'kind'} <= set(row):
            raise ConfigError('component requires id, target and kind')
        identity, target, kind = row['id'], row['target'], row['kind']
        if not isinstance(identity, str) or not IDENTIFIER.fullmatch(identity) or identity in components:
            raise ConfigError('component IDs must be unique lowercase identifiers')
        match = TARGET.fullmatch(target) if isinstance(target, str) else None
        if not isinstance(kind, str) or kind not in ROLE_PACKAGES or match is None or not (
                match[1] == ROLE_PACKAGES[kind] or match[1].startswith(ROLE_PACKAGES[kind] + '.')):
            raise ConfigError('component class must belong to its agent responsibility package')
        params, inject = row.get('params', {}), row.get('inject', {})
        if not isinstance(params, dict) or not isinstance(inject, dict):
            raise ConfigError('component params and inject must be mappings')
        if any(not isinstance(key, str) or not key.isidentifier() for key in (*params, *inject)):
            raise ConfigError('component parameter names must be identifiers')
        if params.keys() & inject.keys():
            raise ConfigError('component params must not overwrite injected dependencies')
        try:
            json.dumps(params, allow_nan=False)
        except (ValueError, TypeError):
            raise ConfigError('component params must contain finite JSON data') from None
        for value in inject.values():
            values = value if isinstance(value, list) else [value]
            if not values or any(not isinstance(ref, str) for ref in values):
                raise ConfigError('dependency must be one component ID or an ordered nonempty list')
            if len(set(values)) != len(values):
                raise ConfigError('dependency lists must not contain duplicate references')
        components[identity] = row
    if not isinstance(root, str) or root not in components or components[root]['kind'] != 'workflow':
        raise ConfigError('assembly root must reference a workflow')
    for row in rows:
        for slot, value in row.get('inject', {}).items():
            for ref in value if isinstance(value, list) else (value,):
                if ref not in components:
                    raise ConfigError(f"{row['id']}.{slot}: unknown dependency reference")
                if components[ref]['kind'] not in DEPENDENCY_KINDS[row['kind']]:
                    raise ConfigError(f"{row['id']}.{slot}: dependency violates component responsibility direction")
    # An edge to the current DFS path is a cycle; an edge to a completed
    # component is legal sharing and must not be rejected.
    active, visited = set(), set()

    def visit(identity):
        if identity in active:
            raise ConfigError('assembly contains a dependency cycle')
        if identity in visited:
            return
        active.add(identity)
        for ref in references(components[identity].get('inject', {})):
            visit(ref)
        active.remove(identity)
        visited.add(identity)

    visit(root)
    # Every configured component must belong to the chosen workflow graph.
    if visited != components.keys():
        raise ConfigError('assembly contains unreachable components')
    return data
