"""Preserve legacy messages while packing optional complete context pieces."""
from __future__ import annotations

from dataclasses import dataclass, field
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
class ContextPiece:
    id: str
    text: str
    source_ids: tuple[str, ...] = ()

    @property
    def sha256(self):
        return hashlib.sha256(self.text.encode()).hexdigest()


@dataclass(frozen=True)
class ContextAssembly:
    messages: list
    resources: dict
    count: TokenCount
    pieces: tuple[dict, ...] = ()
    elapsed_s: float = 0.0

    def summary_dict(self):
        return dict(messages_sha256=messages_hash(self.messages), count=self.count.public_dict(),
                    pieces=list(self.pieces), elapsed_s=self.elapsed_s)


class ContextAssembler:
    def assemble(self, task, *, style, feedback='', parent_code='', selected_skills=None,
                 optional_pieces=(), counter=None, context_limit=None, output_reserve=8192,
                 template_options=None, strict=False):
        positive_integer(context_limit, 'context_limit', optional=True)
        positive_integer(output_reserve, 'output_reserve')
        started = time.monotonic()
        messages, resources = assemble_messages(task, style=style, feedback=feedback,
                                                parent_code=parent_code, selected_skills=selected_skills)
        counter = counter or UnavailableCounter()
        count = counter.count(messages, template_options=template_options)
        # Required messages, including selected skills, are never silently
        # truncated to make an oversized request fit.
        if context_limit is not None:
            if count.status == 'exact' and count.value + output_reserve > context_limit:
                raise ContextLimitError('required_context_exceeds_limit')
            if strict and count.status != 'exact':
                raise ContextLimitError('required_context_tokens_unknown')
        manifest = []
        seen = set()
        for piece in optional_pieces:
            if not piece.id or piece.id in seen:
                raise ValueError('context piece IDs must be nonempty and unique')
            seen.add(piece.id)
            reason = 'included'
            # Try a copy: rejecting a piece must leave accepted messages and
            # their token count unchanged. Pieces are kept or omitted whole.
            trial = [dict(m) for m in messages]
            trial[-1]['content'] += '\n\n' + piece.text
            next_count = counter.count(trial, template_options=template_options)
            if not piece.text:
                reason = 'empty_piece'
            elif context_limit is not None and next_count.status != 'exact':
                reason = 'tokens_unknown'
            elif context_limit is not None and next_count.value + output_reserve > context_limit:
                reason = 'context_limit'
            if reason == 'included':
                messages, count = trial, next_count
            manifest.append(dict(id=piece.id, sha256=piece.sha256, source_ids=list(piece.source_ids),
                                 status=reason))
        return ContextAssembly(messages, resources, count, tuple(manifest), time.monotonic() - started)
