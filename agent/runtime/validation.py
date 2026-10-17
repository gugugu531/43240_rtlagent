"""Runtime checks for the declared component input and output contracts."""
from typing import Any

def validate_component_value(component, field: str, value) -> None:
    expected = getattr(component, field, object)
    if expected in (Any, object):
        return
    if not isinstance(value, expected):
        raise TypeError(f'{type(component).__name__} {field} does not match {type(value).__name__}')
