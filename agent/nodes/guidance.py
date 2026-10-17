"""Own-error repair guidance, separate from feedback and generation."""
from dataclasses import dataclass
import time

from agent.core.components import Node
from agent.core.diagnostic import diagnostics_from_check
from agent.core.state import CheckResult
from agent.services.knowledge import load_corpus, retrieve_repair_guides


@dataclass(frozen=True)
class RepairGuidanceNode(Node[CheckResult, tuple]):
    component_name = 'repair_guidance'
    assembly_roles = ['guidance']
    assembly_defaults = {'params': {'corpus_path': None, 'limit': 2, 'max_chars': 2400}, 'dependencies': {}}
    input_type = CheckResult
    output_type = tuple
    corpus_path: str | None = None
    limit: int = 2
    max_chars: int = 2400

    def run(self, ctx, check):
        started = time.monotonic()
        if check.classify() != 'code':
            ctx.emit('repair_guidance', source_id=check.id, reason='not_code_failure', hits=[])
            return ()
        path = self.corpus_path
        if not path:
            ctx.emit('repair_guidance', source_id=check.id, reason='corpus_not_configured', hits=[])
            return ()
        diagnostics = diagnostics_from_check(check)
        codes = tuple(d.code for d in diagnostics if d.code and d.severity == 'ERROR')
        try:
            corpus = load_corpus(path)
            result = retrieve_repair_guides(corpus, codes=codes,
                tool=check.details.get('diagnostic_tool'), version=check.details.get('tool_version'),
                diagnostics=diagnostics, limit=self.limit, max_chars=self.max_chars)
        except (OSError, ValueError, TypeError, KeyError):
            ctx.emit('repair_guidance', source_id=check.id, reason='corpus_unavailable', hits=[],
                     elapsed_s=time.monotonic() - started)
            return ()
        pieces = result.pop('pieces')
        ctx.emit('repair_guidance', source_id=check.id, **result, elapsed_s=time.monotonic() - started)
        return pieces
