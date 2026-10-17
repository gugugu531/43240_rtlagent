"""Validate the recorded generation requests accepted by initial replay."""
from agent.core.model import ModelRequest
from agent.prompts.builder import assemble_messages


def validate_initial_requests(task, requests, tokens, *, policy):
    if policy != "scheme_a":
        raise ValueError("unsupported initial request policy")
    expected, _ = assemble_messages(task, style='repair', use_skills=False)
    if not requests or len(requests) != tokens['calls']:
        raise ValueError('initial request accounting differs')
    for entry in requests:
        if set(entry) != {'call_id', 'request'}:
            raise ValueError('unsupported initial request fields')
        request = ModelRequest(**entry['request'])
        if [dict(m) for m in request.messages] != expected or request.purpose != 'generate':
            raise ValueError('initial messages differ from scheme A')
    expected_ids = [f'm{i:03d}' for i in range(1, len(requests) + 1)]
    if ([r['call_id'] for r in requests] != expected_ids
            or sorted(tokens['entries']) != expected_ids):
        raise ValueError('initial request IDs differ from accounting')
    return expected_ids
