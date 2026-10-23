"""Assemble required messages and enforce the available context budget."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import time

from agent.core.model import ModelCallError
from agent.core.tokens import TokenCount, UnavailableCounter, positive_integer
from agent.prompts.builder import assemble_messages


def messages_hash(messages):
    return hashlib.sha256(json.dumps([dict(m) for m in messages], ensure_ascii=False,
                         sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class ContextLimitError(ModelCallError):
    def __init__(self, reason):
        super().__init__(reason, kind='context')


@dataclass(frozen=True)
class ContextAssembly:
    messages: list
    resources: dict
    count: TokenCount
    elapsed_s: float = 0.0

    def summary_dict(self):
        return dict(messages_sha256=messages_hash(self.messages), count=self.count.public_dict(),
                    elapsed_s=self.elapsed_s)


class ContextAssembler:
    def assemble(self, task, *, style, feedback='', parent_code='', counter=None, context_limit=None, output_reserve=8192,
                 template_options=None, strict=False):
        positive_integer(context_limit, 'context_limit', optional=True)
        positive_integer(output_reserve, 'output_reserve')
        started = time.monotonic()
        messages, resources = assemble_messages(task, style=style, feedback=feedback,
                                                parent_code=parent_code)
        counter = counter or UnavailableCounter()
        count = counter.count(messages, template_options=template_options)
        # Required messages are never silently
        # truncated to make an oversized request fit.
        if context_limit is not None:
            if count.status == 'exact' and count.value + output_reserve > context_limit:
                raise ContextLimitError('required_context_exceeds_limit')
            if strict and count.status != 'exact':
                raise ContextLimitError('required_context_tokens_unknown')
        return ContextAssembly(messages, resources, count, time.monotonic() - started)
