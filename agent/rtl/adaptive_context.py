"""Prompt-only views; original source binding and validation remain unchanged."""

from agent.rtl.specification import source_catalog


def public_context(task):
    # Present each original paragraph once, with the same IDs used by the validator.
    # Explicit fields prevent candidate/observation data from entering checker calls.
    return {
        "task_id": task.id,
        "top": task.top,
        "source_catalog": [
            {"id": item["id"], "text": item["text"]}
            for item in source_catalog(task.prompt + "\n" + task.interface)
        ],
        "expected_interface": task.expected_interface.public_dict(),
    }


def prompt_schema(schema):
    """Drop display titles only, retaining all constraints, descriptions and defaults."""
    if not isinstance(schema, dict):
        return schema
    result = {}
    for key, value in schema.items():
        if key == "title":
            continue
        if key in ("$defs", "definitions", "properties", "patternProperties", "dependentSchemas"):
            value = {name: prompt_schema(item) for name, item in value.items()}
        elif key in ("allOf", "anyOf", "oneOf", "prefixItems"):
            value = [prompt_schema(item) for item in value]
        elif key in ("items", "additionalProperties", "unevaluatedProperties", "contains",
                     "propertyNames", "not", "if", "then", "else"):
            value = prompt_schema(value)
        result[key] = value
    return result
