"""Fail-closed port semantics for warning-driven candidate replacement only.

This is deliberately not the general interface checker or an HDL elaborator.
Support simple ANSI four-state ports with literal ranges; everything outside
that grammar is unknown. Only wire/reg/logic storage spelling is ignored.
"""
from __future__ import annotations
import re


_IDENTIFIER = r'[A-Za-z_][A-Za-z0-9_$]*'
_RANGE = r'\[\s*(-?\d+)\s*:\s*(-?\d+)\s*\]'
_DIMENSIONS = rf'(?:{_RANGE}\s*)*'
_PORT = re.compile(
    rf'\s*(?:(?P<direction>input|output|inout)\b\s*'
    rf'(?:(?:wire|reg|logic)\b\s*)?'
    rf'(?:(?P<sign>signed|unsigned)\b\s*)?'
    rf'(?P<packed>{_DIMENSIONS}))?'
    rf'(?P<name>{_IDENTIFIER})\s*(?P<unpacked>{_DIMENSIONS})\s*')
_DECLARATION = re.compile(
    r'\b(?:input|output|inout|wire|tri\w*|wand|wor|uwire|supply[01]|'
    r'reg|logic|bit|var|integer|int|shortint|longint|byte|time|real|'
    r'shortreal|realtime|genvar|typedef|parameter|localparam)\b([^;]*);')


def port_signature(code: str, top: str):
    """Return ordered (name, direction, signed, packed, unpacked), or None.

    Preserve range bounds/order, not just bit count. Implicit unsigned equals
    explicit unsigned. Inherited ANSI direction/type/ranges are resolved;
    unpacked dimensions belong to each declarator and are never inherited.
    Parameterization, preprocessing, non-ANSI declarations, user/two-state/net
    types outside wire/reg/logic, and possible body redeclarations fail closed.
    """
    cleaned = re.sub(r'//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"',
                     lambda m: re.sub(r'[^\n]', ' ', m[0]), code)
    if '`' in cleaned or '/*' in cleaned:
        return None
    module = re.search(rf'\bmodule\s+(?P<name>{_IDENTIFIER})\s*'
                       r'\((?P<ports>[^()]*)\)\s*;', cleaned)
    # Do not skip an unsupported first module to find a convenient later one.
    first = re.search(r'\bmodule\b', cleaned)
    if not module or not first or module.start() != first.start() or module['name'] != top:
        return None
    end = re.search(r'\bendmodule\b', cleaned[module.end():])
    if end is None:
        return None
    body = cleaned[module.end():module.end() + end.start()]
    result, context, names = [], None, set()
    for item in module['ports'].split(','):
        port = _PORT.fullmatch(item)
        if port is None or port['name'] in names:
            return None
        if port['direction']:
            context = (port['direction'], port['sign'] == 'signed',
                       tuple((int(a), int(b)) for a, b in re.findall(_RANGE, port['packed'])))
        if context is None:
            return None  # Non-ANSI headers need body declarations, not guesses.
        names.add(port['name'])
        unpacked = tuple((int(a), int(b)) for a, b in re.findall(_RANGE, port['unpacked']))
        result.append((port['name'], *context, unpacked))
    if not result:
        return None
    # Even a simple-looking ANSI header is insufficient if the body can modify
    # a port's declaration. Conservatively reject scope/initializer ambiguity.
    for declaration in _DECLARATION.finditer(body):
        if names.intersection(re.findall(_IDENTIFIER, declaration[1])):
            return None
    return tuple(result)
