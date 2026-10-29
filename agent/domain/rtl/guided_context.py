"""Prompt-only task views for guided checker construction."""

from agent.domain.rtl.specification import source_catalog


def public_context(task):
    """Expose original public text and interface without candidate or tool data."""
    return {
        "task_id": task.id,
        "top": task.top,
        "source_catalog": [
            {"id": item["id"], "text": item["text"]}
            for item in source_catalog(task.prompt + "\n" + task.interface)
        ],
        "expected_interface": task.expected_interface.public_dict(),
    }
