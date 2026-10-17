"""Public interface comparison as an advisory or blocking check."""
from __future__ import annotations
import time
from agent.core.candidate import Candidate
from agent.core.components import Tool
from agent.core.interface import check_interface_result
from agent.core.tool import CheckOutcome


class InterfaceCheckTool(Tool[Candidate, CheckOutcome]):
    component_name = 'interface_check_tool'
    check_kind = 'interface'
    input_type = Candidate
    output_type = CheckOutcome

    def cache_identity(self, ctx) -> str:
        return 'python-interface-v1'

    def replay_identity(self, ctx) -> str:
        return 'python-interface-v1'

    def cache_request(self, input: Candidate):
        return {'code_hash': input.code_hash}

    def run(self, ctx, input: Candidate) -> CheckOutcome:
        started = time.monotonic()
        result = check_interface_result(input.code, ctx.task.interface, ctx.task.prompt)
        status = {'ok': 'passed', 'mismatch': 'failed', 'advisory': 'failed',
                  'skipped': 'skipped', 'parse_error': 'error'}[result.status]
        return CheckOutcome(status, result.summary, blocking=result.blocking, rc=result.rc,
                            elapsed_s=time.monotonic() - started, details=result.trace_dict())
