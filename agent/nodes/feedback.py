"""Turn one bounded failure observation into model-facing feedback."""
from __future__ import annotations

from dataclasses import dataclass
import re

from agent.core.components import Component
from agent.core.registry import NODE_REGISTRY


_DIAGNOSTIC_CODE_RE = re.compile(r"\[([A-Za-z][A-Za-z0-9_-]*\s+\d+-\d+)\]")
_CLASSIFICATIONS = {'code', 'extraction'}


@dataclass(frozen=True)
class FeedbackInput:
    source_id: str
    stage: str
    status: str
    classification: str
    summary: str

    def summary_dict(self) -> dict[str, str]:
        return {
            'source_id': self.source_id,
            'stage': self.stage,
            'status': self.status,
            'classification': self.classification,
        }


@dataclass(frozen=True)
class StructuredFeedback:
    source_id: str
    stage: str
    classification: str
    diagnostic_codes: tuple[str, ...]
    text: str

    def summary_dict(self) -> dict[str, object]:
        return {
            'source_id': self.source_id,
            'stage': self.stage,
            'classification': self.classification,
            'diagnostic_codes': list(self.diagnostic_codes),
            'text_bytes': len(self.text.encode('utf-8')),
        }


@NODE_REGISTRY.register('structured_feedback')
@dataclass(frozen=True)
class StructuredFeedbackNode(Component):
    """Keep the actionable excerpt and make its attribution explicit.

    This node deliberately does not read full logs, retrieve knowledge, reflect,
    or inspect development-only testbenches. Those are separate experiments.
    """

    max_summary_chars: int = 1600

    def __post_init__(self):
        if (isinstance(self.max_summary_chars, bool)
                or not isinstance(self.max_summary_chars, int)
                or self.max_summary_chars <= 0):
            raise ValueError('max_summary_chars must be a positive integer')

    def run(self, ctx, input: FeedbackInput) -> StructuredFeedback:
        if input.classification not in _CLASSIFICATIONS:
            raise ValueError('structured feedback requires a code or extraction failure')
        excerpt = input.summary.strip() or '(no actionable excerpt)'
        if len(excerpt) > self.max_summary_chars:
            excerpt = excerpt[:self.max_summary_chars].rstrip() + '\n[摘要已截断]'
        codes = tuple(dict.fromkeys(_DIAGNOSTIC_CODE_RE.findall(excerpt)))
        code_text = ', '.join(codes) if codes else '(none)'
        text = (
            '结构化诊断：\n'
            f'- 证据编号：{input.source_id or "(unknown)"}\n'
            f'- 阶段：{input.stage}\n'
            f'- 状态：{input.status}\n'
            f'- 归因：{input.classification}\n'
            f'- 稳定错误码：{code_text}\n'
            '- 可操作摘要：\n'
            f'{excerpt}\n'
            '- 修复边界：只修复上述问题，保持题面接口和已经正确的逻辑；'
            '不要猜测隐藏 testbench 或参考实现。'
        )
        return StructuredFeedback(input.source_id, input.stage, input.classification, codes, text)
